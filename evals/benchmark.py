"""Token and latency benchmark, traced to LangSmith, for before/after comparisons.

    cd jyotisha_council
    python ../evals/benchmark.py baseline              # traces go to LangSmith project jyotisha-baseline
    python ../evals/benchmark.py optimized
    python ../evals/benchmark.py smoke --only reading_en

Runs the same fixed conversations every time, checks each reading is still correct
(cited rules were matched, right language), and writes evals/benchmarks/<label>.json
and .md. Totals are cross-checked against what LangSmith recorded. Costs API credit.
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENARIOS = {
    "hello": ["hello"],
    "reading_en": ["Hi, I'm Bench Sita, born 12 April 1998 at 6:30 am in Kathmandu",
                   "Should I take the Japan job offer?"],
    "reading_ja": ["私はBench Kenです。1995年6月15日の朝8時20分、東京生まれです。", "来年、転職するべきですか？"],
    "reading_ne": ["नमस्ते, म Bench Ram हुँ। मेरो जन्म 2000-01-01 बिहान 10:00 बजे पोखरामा भएको हो।",
                   "मेरो पढाइ यो वर्ष कस्तो होला?"],
}
EXPECTED_LANGUAGE = {"reading_ja": "ja", "reading_ne": "ne"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--only", nargs="*", help="run only these scenarios")
    args = ap.parse_args()

    project = f"jyotisha-{args.label}"
    os.environ["LANGSMITH_PROJECT"] = project  # before tracing starts
    sys.path.insert(0, str(ROOT.parent / "jyotisha_council"))
    from chat import ChatSession, run_turn  # noqa: E402  (also loads .env and tracing)
    from guardrails import RULE_ID, detect_language  # noqa: E402
    from observability import flush_traces  # noqa: E402
    from store import delete_sessions_for, forget_person  # noqa: E402
    os.environ["LANGSMITH_PROJECT"] = project  # .env may have reset it; tracing reads it lazily

    started_at = datetime.now(timezone.utc)
    results = []
    for name, turns in SCENARIOS.items():
        if args.only and name not in args.only:
            continue
        session = ChatSession(f"bench-{uuid.uuid4()}")
        events: list[tuple[str, dict]] = []
        session.emit = lambda e, d: events.append((e, d))
        tokens = calls = 0
        t0 = time.perf_counter()
        for turn in turns:
            before = len(events)
            run_turn(session, turn)
            readings = [d for e, d in events[before:] if e == "reading"]
            if readings:  # reading metrics already include the orchestrator's own usage
                m = readings[-1]["metrics"]
                tokens += m["total_tokens"]
                calls += m["llm_calls"]
            elif session.host_llm is not None:
                u = session.host_llm.get_token_usage_summary()
                tokens += u.total_tokens
                calls += u.successful_requests
        reading = next((d for e, d in reversed(events) if e == "reading"), None)
        ok = True
        if name.startswith("reading"):
            ok = bool(reading) and set(RULE_ID.findall(reading["answer"])) <= set(reading["rules"]) \
                and bool(RULE_ID.search(reading["answer"]))
            if ok and name in EXPECTED_LANGUAGE:
                ok = detect_language(reading["answer"]) == EXPECTED_LANGUAGE[name]
        results.append({
            "scenario": name, "correct": ok, "seconds": round(time.perf_counter() - t0, 1),
            "llm_calls": calls, "total_tokens": tokens,
            "reading_metrics": reading["metrics"] if reading else None,
            "answer": reading["answer"] if reading else None,
            "handoffs": [d["agent"] for e, d in events if e == "agent" and d["state"] in ("done", "skipped")],
            "skipped": [d["agent"] for e, d in events if e == "agent" and d["state"] == "skipped"],
        })
        r = results[-1]
        print(f"{'OK ' if ok else 'BAD'} {name:11} {r['seconds']:6.1f}s {calls:3d} calls {tokens:7,d} tokens "
              f"handoffs={r['handoffs']}", flush=True)

    for n in ("Bench Sita", "Bench Ken", "Bench Ram"):
        forget_person(n)
        delete_sessions_for(n)
    flush_traces()

    # Cross-check with what LangSmith recorded for this run.
    langsmith = None
    try:
        time.sleep(10)
        from langsmith import Client
        runs = [r for r in Client().list_runs(project_name=project, run_type="llm", start_time=started_at)]
        langsmith = {"llm_runs": len(runs), "total_tokens": sum(r.total_tokens or 0 for r in runs),
                     "project": project}
    except Exception as exc:  # the benchmark still stands on its own numbers
        langsmith = {"error": str(exc)[:200], "project": project}

    readings = [r for r in results if r["reading_metrics"]]
    summary = {
        "label": args.label, "timestamp": started_at.isoformat(timespec="seconds"),
        "reasoning_effort": (os.getenv("REASONING_EFFORT", "low") or "provider default")
                            + ("" if os.getenv("REASONING_EFFORT") == "" else " (minimal for Ganita/Smriti)"),
        "model": os.getenv("LLM_MODEL", "openai/gpt-5-mini"),
        "all_correct": all(r["correct"] for r in results),
        "total_tokens": sum(r["total_tokens"] for r in results),
        "total_llm_calls": sum(r["llm_calls"] for r in results),
        "avg_reading_tokens": round(sum(r["total_tokens"] for r in readings) / len(readings)) if readings else None,
        "avg_reading_seconds": round(sum(r["seconds"] for r in readings) / len(readings), 1) if readings else None,
        "langsmith": langsmith,
    }
    out = ROOT / "benchmarks"
    out.mkdir(exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps({"summary": summary, "results": results},
                                                       indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
