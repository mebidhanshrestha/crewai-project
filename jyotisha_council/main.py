"""Run a consultation with the Jyotisha Council in the terminal.

    python main.py                       # interactive
    python main.py --name Sita --date 1998-04-12 --time 06:30 --place Kathmandu \
        --question "Should I take the Japan job offer?" --language Japanese
"""

import argparse
import sys

from common import DISCLAIMER, PLACES, explain_llm_error, missing_key, normalize_language
from astro.shastra import humanize
from guardrails import check_question
from store import ledger_for, set_outcome


def ask(prompt: str, default: str | None = None) -> str:
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or (default or "")


def resolve_place(place: str) -> tuple[float, float, str]:
    if place.lower() in PLACES:
        return PLACES[place.lower()]
    print(f"'{place}' is not in the built-in list. Please enter coordinates.")
    return float(ask("Latitude")), float(ask("Longitude")), ask("Timezone", "Asia/Kathmandu")


def review_past_predictions(name: str) -> None:
    """Prediction Ledger: ask 'did this happen?' about earlier answers."""
    pending = [e for e in ledger_for(name) if e["outcome"] is None]
    if not pending:
        return
    print(f"\nWelcome back, {name}. You have {len(pending)} earlier reading(s) without feedback.")
    for e in pending:
        print(f"\n  [{e['timestamp'][:10]}] You asked: {e['question']}")
        reply = ask("  Did things turn out as the reading suggested? (y / n / skip)", "skip").lower()
        if reply in ("y", "n"):
            set_outcome(e["id"], "happened" if reply == "y" else "did_not_happen")


def main() -> None:
    parser = argparse.ArgumentParser(description="Consult the Jyotisha Council")
    parser.add_argument("--name")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--time", help="HH:MM, 24h local time")
    parser.add_argument("--place", help=f"One of: {', '.join(PLACES)}")
    parser.add_argument("--question")
    parser.add_argument("--language", help="English, Nepali or Japanese")
    parser.add_argument("--quiet", action="store_true", help="Hide the agents' step-by-step log")
    args = parser.parse_args()

    if problem := missing_key():
        sys.exit(problem)

    print("=== Jyotisha Council ===")
    name = args.name or ask("Your name")
    review_past_predictions(name)
    date = args.date or ask("Birth date (YYYY-MM-DD)")
    time = args.time or ask("Birth time (HH:MM, 24h)")
    place = args.place or ask(f"Birth place ({', '.join(p.title() for p in PLACES)}, or any other)", "Kathmandu")
    latitude, longitude, timezone = resolve_place(place)
    question = args.question or ask("Your question")
    language = normalize_language(args.language or ask("Answer language (English / Nepali / Japanese)", "English"))

    # Guardrail 1: refuse off-limits questions before spending a single LLM call.
    ok, message = check_question(question)
    if not ok:
        print(f"\n{message}")
        return

    from crew import run_council  # imported late so --help works without a key

    birth = {"date": date, "time": time, "latitude": latitude, "longitude": longitude, "timezone": timezone}
    try:
        reading = run_council(name, birth, question, language, verbose=not args.quiet)
    except Exception as exc:
        sys.exit(f"\nThe council could not finish: {explain_llm_error(exc)}")

    from observability import flush_traces
    flush_traces()
    m = reading["metrics"]
    print("\n" + "=" * 60 + f"\n{humanize(reading['answer'], language)}\n\n_{DISCLAIMER[language]}_\n" + "=" * 60)
    print(f"{m['seconds_total']}s · {m['llm_calls']} LLM calls · {m['total_tokens']:,} tokens")
    print("Saved to your Prediction Ledger. Next visit, I'll ask how it turned out.")


if __name__ == "__main__":
    main()
