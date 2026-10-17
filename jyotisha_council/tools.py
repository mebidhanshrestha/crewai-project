"""CrewAI tools. Each one wraps deterministic code so the LLM never invents data.

Every consultation gets its own `state` dict (see new_state), shared by its tools and
guardrails, so concurrent readings never see each other's charts. The birth details
are put into state by code, so Ganita's tool takes no arguments: the LLM cannot
mistype a date or a coordinate on the way to the ephemeris.
"""

import json
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from astro.ganita import compute_chart
from astro.shastra import TOPICS, evidence_strength, match_rules
from store import ledger_for


def new_state(birth: dict, language: str = "English") -> dict:
    """birth: date, time, latitude, longitude, timezone."""
    return {"birth": birth, "language": language, "chart": None,
            "matched_rule_ids": set(), "matches": {}, "strength": {}}


class _StateTool(BaseTool):
    state: Any = Field(default=None, exclude=True)


# --- Ganita -----------------------------------------------------------------

class NoInput(BaseModel):
    pass


class ChartCalculatorTool(_StateTool):
    name: str = "chart_calculator"
    description: str = (
        "Computes this person's sidereal (Lahiri) birth chart with Swiss Ephemeris from their "
        "verified birth details: lagna, planet signs/houses/dignities, Moon nakshatra and running "
        "Vimshottari dasha. Takes no arguments."
    )
    args_schema: type[BaseModel] = NoInput

    def _run(self, **_) -> str:
        b = self.state["birth"]
        try:
            chart = compute_chart(b["date"], b["time"], b["latitude"], b["longitude"], b["timezone"])
        except Exception as exc:  # bad date/time/timezone: tell the agent, don't crash
            return f"ERROR: could not compute chart ({exc})."
        self.state["chart"] = chart
        return json.dumps(chart, indent=1)


# --- Shastra ----------------------------------------------------------------

class RuleInput(BaseModel):
    topic: str = Field(..., description=f"One of: {', '.join(TOPICS)}")


class RuleLookupTool(_StateTool):
    name: str = "rule_lookup"
    description: str = (
        "Matches the computed chart against the classical rule library for one topic. Returns "
        "each matched rule (ID, plain label, tone, reading, how common it is, chart evidence) and "
        "an evidence strength ranked against a population of random charts."
    )
    args_schema: type[BaseModel] = RuleInput

    def _run(self, topic: str) -> str:
        chart = self.state["chart"]
        if chart is None:
            return "ERROR: no chart computed yet. The chart must be calculated first."
        topic = topic.strip().lower()
        matches = match_rules(chart, topic, self.state["language"])
        strength = evidence_strength(chart, topic)
        self.state["matched_rule_ids"].update(m["rule_id"] for m in matches)
        self.state["matches"].update({m["rule_id"]: m for m in matches})
        self.state["strength"][topic] = strength
        for_writer = [  # copies, so the UI keeps the numeric share
            {**m, "how_common": f"fits about {round(m['how_common'] * 100)}% of people"}
            if m["how_common"] is not None else m
            for m in matches
        ]
        return json.dumps({"topic": topic, "evidence_strength": strength, "matches": for_writer},
                          indent=1, ensure_ascii=False)


# --- Smriti -----------------------------------------------------------------

class MemoryInput(BaseModel):
    name: str = Field(..., description="The person's name exactly as given")


class LedgerRecallTool(_StateTool):
    name: str = "ledger_recall"
    description: str = (
        "Returns this person's past questions, past answers and recorded outcomes "
        "from the Prediction Ledger."
    )
    args_schema: type[BaseModel] = MemoryInput

    def _run(self, name: str) -> str:
        mine = ledger_for(name)
        if not mine:
            return "No past consultations for this person. This is their first visit."
        return json.dumps(mine[-5:], indent=1, ensure_ascii=False)
