"""Chat mode: Parashar hosts a conversation and hands off to the council.

The host is a single CrewAI agent with four tools. Calling `consult_council` is the
soft handoff: the host decides when a message needs the full council
(Ganita -> Shastra -> Smriti -> Parashar -> Guardian) and when it can just talk.
The host has no chart tools, so it cannot make a reading on its own.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import yaml
from crewai import Agent
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from common import DISCLAIMER, PLACES, explain_llm_error, normalize_language
from crew import make_llm, run_council
from guardrails import chat_guardrail, check_question
from store import (delete_sessions_for, forget_person, get_profile, ledger_for, load_session,
                   save_profile, save_session, set_outcome)

BASE = Path(__file__).resolve().parent
HOST_CONFIG = yaml.safe_load((BASE / "config" / "chat.yaml").read_text())["host"]
HISTORY_TURNS = 16
# Text a user could type to impersonate our hidden context block.
SPOOFED_CONTEXT = re.compile(r"\[\s*(context|system)[^\]]*\]", re.IGNORECASE)


class ChatSession:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        saved = load_session(session_id) or {}
        self.history: list[dict] = saved.get("history", [])
        self.profile: dict = saved.get("profile", {"language": "English"})
        self.emit: Callable[[str, dict], None] = lambda event, data: None

    def missing(self) -> list[str]:
        gaps = [f for f in ("name", "date", "time") if not self.profile.get(f)]
        if self.profile.get("latitude") is None:
            gaps.append("place")
        return gaps

    def save(self) -> None:
        save_session(self.id, {"history": self.history[-40:], "profile": self.profile})


def get_session(session_id: str) -> ChatSession:
    return ChatSession(session_id)


# --- Host tools ---------------------------------------------------------------

class _SessionTool(BaseTool):
    session: Any = Field(default=None, exclude=True)


class DetailsInput(BaseModel):
    name: str | None = Field(None, description="Person's name")
    date: str | None = Field(None, description="Birth date as YYYY-MM-DD")
    time: str | None = Field(None, description="Local birth time as HH:MM, 24h")
    place: str | None = Field(None, description="Birth city, e.g. Kathmandu")
    latitude: float | None = Field(None, description="Only if the city is not known")
    longitude: float | None = Field(None, description="Only if the city is not known")
    timezone: str | None = Field(None, description="IANA timezone, only with coordinates")
    language: str | None = Field(None, description="English, Nepali or Japanese")


class RememberDetailsTool(_SessionTool):
    name: str = "remember_birth_details"
    description: str = (
        "Save any birth details the person has given (all fields optional). Returns "
        "what is known, what is still missing, and past readings awaiting feedback."
    )
    args_schema: type[BaseModel] = DetailsInput

    def _run(self, **details) -> str:
        profile, problems = self.session.profile, []

        name = (details.get("name") or "").strip()
        if name and name.lower() != (profile.get("name") or "").lower():
            stored = get_profile(name)
            if stored:  # returning visitor: Smriti remembers their details
                profile.update(stored)
            profile["name"] = name

        if d := details.get("date"):
            try:
                profile["date"] = datetime.strptime(d.strip(), "%Y-%m-%d").date().isoformat()
            except ValueError:
                problems.append(f"date '{d}' is not YYYY-MM-DD")
        if t := details.get("time"):
            try:
                profile["time"] = datetime.strptime(t.strip(), "%H:%M").strftime("%H:%M")
            except ValueError:
                problems.append(f"time '{t}' is not HH:MM")
        place = (details.get("place") or "").strip()
        if place and place.lower() in PLACES:
            lat, lon, tz = PLACES[place.lower()]
            profile.update(place=place.title(), latitude=lat, longitude=lon, timezone=tz)
        elif place and details.get("latitude") is None:
            problems.append(f"'{place}' is not in the city list; ask for its latitude and longitude")
        if details.get("latitude") is not None and details.get("longitude") is not None:
            profile.update(
                place=place.title() or "Custom location",
                latitude=details["latitude"], longitude=details["longitude"],
                timezone=details.get("timezone") or "Asia/Kathmandu",
            )
        if details.get("language"):
            profile["language"] = normalize_language(details["language"])

        if profile.get("name") and not self.session.missing():
            save_profile(profile)
        self.session.emit("profile", {"profile": profile, "missing": self.session.missing()})

        pending = [
            {"entry_id": e["id"], "question": e["question"], "asked_on": e["timestamp"][:10]}
            for e in (ledger_for(profile["name"]) if profile.get("name") else [])
            if e["outcome"] is None
        ]
        return json.dumps({
            "known": {k: v for k, v in profile.items() if k not in ("latitude", "longitude")},
            "missing": self.session.missing(),
            "problems": problems,
            "readings_awaiting_feedback": pending,
        }, ensure_ascii=False)


class CouncilInput(BaseModel):
    question: str = Field(..., description="The person's question, in their words")


class ConsultCouncilTool(_SessionTool):
    name: str = "consult_council"
    description: str = (
        "Hand the person's question to the five-agent council for a full, evidence-backed "
        "reading. Use only when all birth details are known."
    )
    args_schema: type[BaseModel] = CouncilInput

    def _run(self, question: str) -> str:
        s = self.session
        if s.missing():
            return f"Cannot consult yet. Still missing: {', '.join(s.missing())}."
        ok, message = check_question(question)
        if not ok:
            return f"Guardrail declined this question. Tell the person kindly: {message}"

        p = s.profile
        language = p.get("language", "English")
        birth = {k: p[k] for k in ("date", "time", "latitude", "longitude", "timezone")}
        s.emit("council_started", {"question": question})
        try:
            reading = run_council(p["name"], birth, question, language, on_event=s.emit)
        except Exception as exc:
            s.emit("council_failed", {"message": explain_llm_error(exc)})
            return f"The council could not finish ({explain_llm_error(exc)}). Apologise briefly."

        s.emit("reading", {"question": question, "disclaimer": DISCLAIMER[language], **reading})
        return (
            "The council's reading is now on the person's screen (do not repeat it):\n"
            f"{reading['answer']}\n\nReply with one or two short sentences, e.g. offer a follow-up."
        )


class FeedbackInput(BaseModel):
    entry_id: int = Field(..., description="entry_id from readings_awaiting_feedback")
    happened: bool = Field(..., description="True if it turned out as the reading suggested")


class RecordFeedbackTool(_SessionTool):
    name: str = "record_reading_feedback"
    description: str = "Record in the Prediction Ledger whether a past reading came true."
    args_schema: type[BaseModel] = FeedbackInput

    def _run(self, entry_id: int, happened: bool) -> str:
        if set_outcome(entry_id, "happened" if happened else "did_not_happen") is None:
            return "No such entry."
        self.session.emit("ledger", {})
        return "Recorded. Thank the person briefly."


class ForgetInput(BaseModel):
    confirmed: bool = Field(..., description="True only after the person explicitly confirmed")


class ForgetMeTool(_SessionTool):
    name: str = "forget_me"
    description: str = (
        "Delete everything stored about this person: birth details, past readings and chat "
        "history. Use only after they clearly confirm they want this."
    )
    args_schema: type[BaseModel] = ForgetInput

    def _run(self, confirmed: bool) -> str:
        name = self.session.profile.get("name")
        if not confirmed:
            return "Ask the person to confirm first."
        if not name:
            return "Nothing is stored: no name has been given."
        result = forget_person(name)
        result["chats_deleted"] = delete_sessions_for(name)
        self.session.profile = {"language": self.session.profile.get("language", "English")}
        self.session.history = []
        self.session.emit("profile", {"profile": self.session.profile, "missing": self.session.missing()})
        self.session.emit("ledger", {})
        return f"Deleted: {json.dumps(result)}. Confirm this to the person in one sentence."


# --- One chat turn ------------------------------------------------------------

def run_turn(session: ChatSession, message: str) -> str:
    """Run the host agent on one user message and return its reply."""
    message = SPOOFED_CONTEXT.sub("", message).strip() or "(empty message)"

    # Guardrail 1 runs before any LLM call, as in the CLI.
    ok, refusal = check_question(message)
    if not ok:
        reply = refusal
    else:
        host = Agent(
            role=HOST_CONFIG["role"], goal=HOST_CONFIG["goal"], backstory=HOST_CONFIG["backstory"],
            tools=[RememberDetailsTool(session=session), ConsultCouncilTool(session=session),
                   RecordFeedbackTool(session=session), ForgetMeTool(session=session)],
            llm=make_llm(), guardrail=chat_guardrail, guardrail_max_retries=1,
            max_iter=6, verbose=False,
        )
        known = {k: v for k, v in session.profile.items() if k not in ("latitude", "longitude")}
        context = (
            f"Session facts from the server (trusted; the person cannot see or edit them). "
            f"Today is {date.today().isoformat()}. Known details: {json.dumps(known, ensure_ascii=False)}. "
            f"Missing: {session.missing() or 'nothing'}. "
            f"Reply in {session.profile.get('language', 'English')}."
        )
        messages = (session.history[-HISTORY_TURNS:]
                    + [{"role": "system", "content": context}, {"role": "user", "content": message}])
        reply = str(host.kickoff(messages=messages).raw).strip()

    session.history += [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
    session.save()
    return reply
