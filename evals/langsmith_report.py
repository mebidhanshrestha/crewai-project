"""Summarise a LangSmith project: where do the tokens and the time go?

    python ../evals/langsmith_report.py jyotisha-baseline [jyotisha-optimized]
    python ../evals/langsmith_report.py jyotisha-optimized@2026-10-18T13:24:53   # only runs since then

Groups every LLM call by the agent that made it (the nearest CrewAI agent span above it)
and prints input/output tokens, reasoning tokens and latency. Pass two projects to compare.
"""

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jyotisha_council"))
import common  # noqa: E402,F401  (loads .env for the LangSmith key)
from langsmith import Client  # noqa: E402

AGENT_KEYS = {"parashar": "Parashar (orchestrator)", "ganita": "Ganita", "shastra": "Shastra",
              "smriti": "Smriti", "guardian": "Guardian"}


def agent_of(run, by_id) -> str:
    """Walk up the trace to the nearest span that names an agent."""
    node = by_id.get(run.parent_run_id)
    while node is not None:
        name = node.name.lower()
        for key, label in AGENT_KEYS.items():
            if key in name:
                return label
        node = by_id.get(node.parent_run_id)
    return "unattributed (no agent spans)"


def summarise(project: str) -> dict:
    project, _, since = project.partition("@")
    kwargs = {"start_time": datetime.fromisoformat(since).replace(tzinfo=timezone.utc)} if since else {}
    runs = list(Client().list_runs(project_name=project, **kwargs))
    by_id = {r.id: r for r in runs}
    rows = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "reasoning": 0, "seconds": 0.0})
    for r in runs:
        if r.run_type != "llm":
            continue
        row = rows[agent_of(r, by_id)]
        row["calls"] += 1
        row["in"] += r.prompt_tokens or 0
        row["out"] += r.completion_tokens or 0
        details = (r.completion_token_details or {}) if hasattr(r, "completion_token_details") else {}
        row["reasoning"] += details.get("reasoning", 0) or 0
        if r.end_time and r.start_time:
            row["seconds"] += (r.end_time - r.start_time).total_seconds()
    return dict(rows)


def show(project: str, rows: dict) -> None:
    total = {k: sum(r[k] for r in rows.values()) for k in ("calls", "in", "out", "reasoning", "seconds")}
    print(f"\n{project}: {total['calls']} LLM calls, {total['in'] + total['out']:,} tokens "
          f"({total['in']:,} in / {total['out']:,} out, {total['reasoning']:,} reasoning), "
          f"{total['seconds']:.0f}s of LLM time")
    print(f"  {'agent':24} {'calls':>5} {'in':>8} {'out':>8} {'reason':>8} {'secs':>6}  share")
    for name, r in sorted(rows.items(), key=lambda kv: -(kv[1]['in'] + kv[1]['out'])):
        share = (r["in"] + r["out"]) / max(total["in"] + total["out"], 1)
        print(f"  {name:24} {r['calls']:5d} {r['in']:8,d} {r['out']:8,d} {r['reasoning']:8,d} "
              f"{r['seconds']:6.0f}  {share:5.0%}")


if __name__ == "__main__":
    for project in sys.argv[1:]:
        show(project, summarise(project))
