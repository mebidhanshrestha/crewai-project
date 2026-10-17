"""Run the behaviour evals in evals/cases.yaml against the real model.

    cd jyotisha_council
    python ../evals/run_evals.py              # all cases
    python ../evals/run_evals.py greeting_en  # one case

Costs real API credit (a few cents per council reading). Writes evals/last_results.json.
Unit tests check the code; these check how the agents actually behave, so run them
after any prompt, model or tool change.
"""

import json
import re
import sys
import time
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "jyotisha_council"))

from chat import ChatSession, run_turn  # noqa: E402
from common import missing_key  # noqa: E402
from guardrails import RULE_ID, check_question, detect_language, find_unsafe  # noqa: E402
from store import delete_sessions_for, forget_person, get_profile  # noqa: E402


def run_case(case: dict) -> dict:
    session = ChatSession(f"eval-{uuid.uuid4()}")
    events: list[tuple[str, dict]] = []
    session.emit = lambda event, data: events.append((event, data))
    replies, started = [], time.perf_counter()
    for turn in case["turns"]:
        replies.append(run_turn(session, turn))
    seconds = round(time.perf_counter() - started, 1)

    readings = [d for e, d in events if e == "reading"]
    last_turn, last_reply = case["turns"][-1], replies[-1]
    checks = {}
    for key, want in case["expect"].items():
        if key == "council":
            checks[key] = bool(readings) == want
        elif key == "blocked":
            checks[key] = (not check_question(last_turn)[0]) == want
        elif key == "reply_language":
            checks[key] = detect_language(last_reply) == want
        elif key == "reading_language":
            checks[key] = bool(readings) and detect_language(readings[-1]["answer"]) == want
        elif key == "citations_valid":
            checks[key] = bool(readings) and all(
                set(RULE_ID.findall(r["answer"])) <= set(r["rules"]) and RULE_ID.search(r["answer"])
                for r in readings)
        elif key == "reply_safe":
            checks[key] = all(find_unsafe(r) is None for r in replies)
        elif key == "reply_mentions_any":
            checks[key] = any(w.lower() in last_reply.lower() for w in want)
        elif key == "profile_complete":
            checks[key] = not session.missing()
        elif key == "forgotten":
            checks[key] = get_profile(want) is None
        else:
            checks[key] = False

    metrics = readings[-1]["metrics"] if readings else None
    return {"id": case["id"], "passed": all(checks.values()), "checks": checks,
            "seconds": seconds, "council_metrics": metrics, "last_reply": last_reply[:300],
            "reading": readings[-1]["answer"] if readings else None}


def main() -> None:
    if problem := missing_key():
        sys.exit(problem)
    cases = yaml.safe_load((ROOT / "cases.yaml").read_text())
    if len(sys.argv) > 1:
        cases = [c for c in cases if c["id"] in sys.argv[1:]]

    results = []
    for case in cases:
        try:
            r = run_case(case)
        except Exception as exc:  # a crash is a failed case, not a failed run
            r = {"id": case["id"], "passed": False, "checks": {}, "error": str(exc)[:300]}
        results.append(r)
        mark = "PASS" if r["passed"] else "FAIL"
        failed = [k for k, v in r.get("checks", {}).items() if not v] or r.get("error", "")
        print(f"{mark}  {r['id']:36} {r.get('seconds', '-')}s  {failed or ''}", flush=True)

    # Remove everything the evals stored.
    for name in {n for c in cases for n in re.findall(r"Eval [A-Za-z]+", " ".join(c["turns"]))}:
        forget_person(name)
        delete_sessions_for(name)

    passed = sum(r["passed"] for r in results)
    council = [r["council_metrics"] for r in results if r.get("council_metrics")]
    summary = {
        "passed": passed, "total": len(results),
        "avg_reading_seconds": round(sum(m["seconds_total"] for m in council) / len(council), 1) if council else None,
        "avg_reading_tokens": round(sum(m["total_tokens"] for m in council) / len(council)) if council else None,
        "avg_reading_llm_calls": round(sum(m["llm_calls"] for m in council) / len(council), 1) if council else None,
    }
    print(f"\n{passed}/{len(results)} passed. Readings: {summary}")
    (ROOT / "last_results.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
