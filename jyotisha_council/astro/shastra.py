"""Shastra: deterministic rule engine. Matches chart facts against rules.json.

Confidence is not "how many rules matched": most rules fire for a large share of
people, so counting them inflates confidence (the Barnum effect). Instead each
rule is weighted by how rare it is in a population of random charts
(data/base_rates.json, built by scripts/base_rates.py), and a chart's evidence
for a topic is ranked against that population.
"""

import json
import math
import re
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
RULES_PATH = DATA / "rules.json"
BASE_RATES_PATH = DATA / "base_rates.json"
TOPICS = ["general", "career", "marriage", "wealth", "education", "travel"]
LANGUAGES = {"English": "en", "Nepali": "ne", "Japanese": "ja"}
RULE_ID = re.compile(r"R-[A-Z]{3}-[A-Z0-9]{2,3}")


@lru_cache(maxsize=1)
def load_rules() -> list[dict]:
    return json.loads(RULES_PATH.read_text())["rules"]


@lru_cache(maxsize=1)
def load_base_rates() -> dict | None:
    return json.loads(BASE_RATES_PATH.read_text()) if BASE_RATES_PATH.exists() else None


def lang_code(language: str) -> str:
    return LANGUAGES.get(language, "en")


def _holds(cond: dict, chart: dict) -> bool:
    planets = chart["planets"]
    kind = cond["type"]
    if kind == "planet_in_house":
        return planets[cond["planet"]]["house"] in cond["houses"]
    if kind == "planet_dignity":
        return planets[cond["planet"]]["dignity"] in cond["dignity"]
    if kind == "house_lord_in_house":
        lord = chart["house_lords"][cond["house"]]
        return planets[lord]["house"] in cond["houses"]
    if kind == "planet_from_planet":
        offset = (planets[cond["planet"]]["house"] - planets[cond["from"]]["house"]) % 12 + 1
        return offset in cond["houses"]
    if kind == "mahadasha":
        return chart["dasha"]["mahadasha"] == cond["lord"]
    raise ValueError(f"Unknown condition type: {kind}")


def matching_rule_ids(chart: dict, topic: str) -> list[str]:
    return [r["id"] for r in load_rules()
            if topic in r["topics"] and all(_holds(c, chart) for c in r["conditions"])]


def specificity(rule_ids: list[str], rates: dict) -> float:
    """Information in bits: rare rules count for more. Dasha rules always match one, so they score 0."""
    return sum(-math.log2(max(rates[i], 1e-3)) for i in rule_ids if not i.startswith("R-DAS"))


def match_rules(chart: dict, topic: str, language: str = "English") -> list[dict]:
    """Return every rule for `topic` whose conditions all hold, with its evidence."""
    topic = topic if topic in TOPICS else "general"
    code = lang_code(language)
    rates = (load_base_rates() or {}).get("rule_rates", {})
    by_id = {r["id"]: r for r in load_rules()}
    matched = []
    for rule_id in matching_rule_ids(chart, topic):
        rule = by_id[rule_id]
        matched.append({
            "rule_id": rule_id,
            "name": rule["name"],
            "label": rule["label"][code],
            "tone": rule["tone"],
            "reading": rule["reading"],
            "how_common": rates.get(rule_id),  # share of people this rule fits
            "evidence": [_describe(c, chart) for c in rule["conditions"]],
        })
    return matched


def evidence_strength(chart: dict, topic: str) -> dict:
    """Rank this chart's evidence for `topic` against the population of random charts."""
    base = load_base_rates()
    if base is None:
        return {"strength": "unknown", "percentile": None,
                "explanation": "Base rates not computed; run scripts/base_rates.py."}
    topic = topic if topic in TOPICS else "general"
    score = specificity(matching_rule_ids(chart, topic), base["rule_rates"])
    quantiles = base["topic_score_quantiles"][topic]
    percentile = round(100 * bisect_right(quantiles, score) / len(quantiles))
    strength = "strong" if percentile >= 75 else "moderate" if percentile >= 40 else "limited"
    return {
        "strength": strength,
        "percentile": percentile,
        "explanation": (f"The chart evidence for {topic} is more specific than about {percentile}% "
                        "of charts, because rules that fit most people count for little."),
    }


def humanize(text: str, language: str = "English") -> str:
    """Swap rule IDs for their plain-language labels, for readers who don't need the codes."""
    code = lang_code(language)
    labels = {r["id"]: r["label"][code] for r in load_rules()}
    text = re.sub(r"\[\s*(R-[A-Z]{3}-[A-Z0-9]{2,3}(?:\s*,\s*R-[A-Z]{3}-[A-Z0-9]{2,3})*)\s*\]",
                  lambda m: "(" + "; ".join(labels.get(i.strip(), i.strip()) for i in m.group(1).split(",")) + ")",
                  text)
    return RULE_ID.sub(lambda m: labels.get(m.group(0), m.group(0)), text)


def _describe(cond: dict, chart: dict) -> str:
    """Human-readable 'why' for Evidence Mode."""
    p = chart["planets"]
    kind = cond["type"]
    if kind == "planet_in_house":
        name = cond["planet"]
        return f"{name} in house {p[name]['house']} ({p[name]['sign']})"
    if kind == "planet_dignity":
        name = cond["planet"]
        return f"{name} is {p[name]['dignity']} in {p[name]['sign']}"
    if kind == "house_lord_in_house":
        lord = chart["house_lords"][cond["house"]]
        return f"Lord of house {cond['house']} is {lord}, placed in house {p[lord]['house']}"
    if kind == "planet_from_planet":
        offset = (p[cond["planet"]]["house"] - p[cond["from"]]["house"]) % 12 + 1
        return f"{cond['planet']} is in house {offset} counted from {cond['from']}"
    if kind == "mahadasha":
        return f"Running {chart['dasha']['mahadasha']} mahadasha until {chart['dasha']['mahadasha_until']}"
    return kind
