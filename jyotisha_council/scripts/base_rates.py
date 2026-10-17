"""Build data/base_rates.json: how often each rule fires in a population of random charts.

    python scripts/base_rates.py            # 3000 charts, fixed seed, ~1 minute

Births are sampled uniformly from 1960-2010 at six cities across Nepal and North India.
The result feeds Shastra's confidence: a rule that fits half of everyone tells you
little about one person, so it carries little weight.
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astro.ganita import compute_chart  # noqa: E402
from astro.shastra import BASE_RATES_PATH, TOPICS, load_rules, matching_rule_ids, specificity  # noqa: E402

N = 3000
SEED = 7
CITIES = [
    (27.7172, 85.3240, "Asia/Kathmandu"),  # Kathmandu
    (28.2096, 83.9856, "Asia/Kathmandu"),  # Pokhara
    (26.4525, 87.2718, "Asia/Kathmandu"),  # Biratnagar
    (28.0500, 81.6167, "Asia/Kathmandu"),  # Nepalgunj
    (28.6139, 77.2090, "Asia/Kolkata"),    # Delhi
    (25.3176, 82.9739, "Asia/Kolkata"),    # Varanasi
]


def main() -> None:
    rng = random.Random(SEED)
    start, span = datetime(1960, 1, 1), 50 * 365 * 24 * 60
    charts = []
    for _ in range(N):
        when = start + timedelta(minutes=rng.randrange(span))
        lat, lon, tz = rng.choice(CITIES)
        charts.append(compute_chart(when.strftime("%Y-%m-%d"), when.strftime("%H:%M"), lat, lon, tz))

    fired = {r["id"]: 0 for r in load_rules()}
    per_topic = {t: [] for t in TOPICS}
    for chart in charts:
        seen = set()
        for topic in TOPICS:
            ids = matching_rule_ids(chart, topic)
            per_topic[topic].append(ids)
            seen.update(ids)
        for rule_id in seen:
            fired[rule_id] += 1
    rates = {k: round(v / N, 4) for k, v in fired.items()}

    quantiles = {}
    for topic, all_ids in per_topic.items():
        scores = sorted(specificity(ids, rates) for ids in all_ids)
        quantiles[topic] = [round(scores[min(int(q / 100 * N), N - 1)], 4) for q in range(101)]

    BASE_RATES_PATH.write_text(json.dumps({
        "n_charts": N, "seed": SEED, "years": "1960-2010",
        "cities": "Kathmandu, Pokhara, Biratnagar, Nepalgunj, Delhi, Varanasi",
        "rule_rates": rates,
        "topic_score_quantiles": quantiles,
    }, indent=1) + "\n")

    print(f"Wrote {BASE_RATES_PATH.name} from {N} charts")
    for r in load_rules():
        if not r["id"].startswith("R-DAS"):
            print(f"  {r['id']:9} {rates[r['id']]:6.1%}  {r['tone']:10} {r['label']['en']}")


if __name__ == "__main__":
    main()
