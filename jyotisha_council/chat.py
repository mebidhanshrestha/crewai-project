"""Chat mode: Parashar is the orchestrator. It talks to the person and does the handoffs.

Parashar has one handoff tool per specialist agent and decides the order itself:
handoff_to_ganita (chart) -> handoff_to_shastra (rules) -> [handoff_to_smriti (history),
optional] -> Parashar writes the draft -> handoff_to_guardian (review). Code enforces what
must not be skipped: the Guardian refuses a draft until Ganita and Shastra have run, and
a draft citing unmatched rules is handed back to Parashar with the reason.
Parashar has no chart tools of its own, so it cannot make a reading without the council.
"""

import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import yaml
from crewai import Agent
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from common import DISCLAIMER, PLACES, normalize_language
from crew import make_llm
from observability import agent_span
from guardrails import (check_citations, check_question, detect_language, make_chat_guardrail,
                        make_safety_guardrail)
from store import (DATA, append_prediction, delete_sessions_for, forget_person, get_profile,
                   ledger_for, load_session, save_profile, save_session, set_outcome)
from tools import ChartCalculatorTool, LedgerRecallTool, RuleLookupTool, new_state

BASE = Path(__file__).resolve().parent
HOST_CONFIG = yaml.safe_load((BASE / "config" / "chat.yaml").read_text())["host"]
AGENTS_CONFIG = yaml.safe_load((BASE / "config" / "agents.yaml").read_text())
HANDOFFS = yaml.safe_load((BASE / "config" / "handoffs.yaml").read_text())
SPECIALIST_TOOLS = {"ganita": ChartCalculatorTool, "shastra": RuleLookupTool, "smriti": LedgerRecallTool}
HISTORY_TURNS = 8  # messages of history sent with each turn (4 exchanges)
# Agents that only fetch data need little reasoning; the writer and the reviewer get a bit more.
AGENT_EFFORT = {"ganita": "minimal", "smriti": "minimal", "shastra": "low", "guardian": "low"}
AGENT_LABEL = {"ganita": "Ganita", "shastra": "Shastra", "smriti": "Smriti", "guardian": "Guardian"}
FOLLOW_UP = {
    "English": "The council's reading is above. Would you like to look at timing, or ask another question?",
    "Nepali": "परिषद्को पढाइ माथि छ। समयबारे हेर्न चाहनुहुन्छ, वा अर्को प्रश्न सोध्नुहुन्छ?",
    "Japanese": "評議会の鑑定は上のとおりです。タイミングについて詳しく見ますか、それとも別の質問をしますか？",
}
# Text a user could type to impersonate our hidden context block.
SPOOFED_CONTEXT = re.compile(r"\[\s*(context|system)[^\]]*\]", re.IGNORECASE)


class ChatSession:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        saved = load_session(session_id) or {}
        self.history: list[dict] = saved.get("history", [])
        self.profile: dict = saved.get("profile", {"language": "English"})
        self.emit: Callable[[str, dict], None] = lambda event, data: None
        self.reading: dict | None = None  # the reading being orchestrated in this turn
        self.delivered_reading = False    # set when the Guardian approves a reading this turn
        self.host_llm = None

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


class NoArgs(BaseModel):
    pass


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


# --- Handoff tools: the orchestrator calls each specialist agent itself -------------------

def _run_specialist(session: "ChatSession", key: str, prompt: str, guardrail=None) -> str:
    """Hand one job to a specialist agent and report it to the UI as a handoff."""
    r = session.reading
    llm = make_llm(AGENT_EFFORT.get(key))
    tools = [SPECIALIST_TOOLS[key](state=r["state"])] if key in SPECIALIST_TOOLS else []
    agent = Agent(config=AGENTS_CONFIG[key], tools=tools, llm=llm, allow_delegation=False,
                  max_iter=3, guardrail=guardrail, guardrail_max_retries=2, verbose=False)
    session.emit("agent", {"agent": key, "state": "working"})
    started = time.perf_counter()
    with agent_span(f"agent: {AGENT_LABEL[key]}"):
        output = str(agent.kickoff(prompt).raw).strip()
    r["seconds"][key] = round(r["seconds"].get(key, 0) + time.perf_counter() - started, 1)
    r["llms"].setdefault(key, []).append(llm)
    session.emit("agent", {"agent": key, "state": "done", "output": output})
    return output


class _ReadingTool(_SessionTool):
    def _reading_or_error(self) -> str | None:
        if self.session.reading is None:
            if isinstance(self, HandoffGuardianTool):
                raise ValueError("No reading in progress. Start with handoff_to_ganita.")
            return "No reading in progress. Start with handoff_to_ganita."
        return None


class GanitaInput(BaseModel):
    question: str = Field(..., description="The person's question, in their words")


class HandoffGanitaTool(_ReadingTool):
    name: str = "handoff_to_ganita"
    description: str = "Step 1 of a reading: Ganita computes the person's chart for their question."
    args_schema: type[BaseModel] = GanitaInput

    def _run(self, question: str) -> str:
        s = self.session
        if s.missing():
            return f"Cannot start yet. Still missing: {', '.join(s.missing())}."
        ok, message = check_question(question)
        if not ok:
            return f"Guardrail declined this question. Tell the person kindly: {message}"
        p = s.profile
        birth = {k: p[k] for k in ("date", "time", "latitude", "longitude", "timezone")}
        s.reading = {"question": question, "state": new_state(birth, p.get("language", "English")),
                     "llms": {}, "seconds": {}, "started": time.perf_counter(), "smriti": False}
        s.emit("council_started", {"question": question})
        return _run_specialist(s, "ganita", HANDOFFS["ganita"])


class ShastraInput(BaseModel):
    topics: list[str] = Field(..., description="1-2 of: general, career, marriage, wealth, education, travel")


class HandoffShastraTool(_ReadingTool):
    name: str = "handoff_to_shastra"
    description: str = "Step 2: Shastra matches classical rules for 1-2 topics and ranks the evidence."
    args_schema: type[BaseModel] = ShastraInput

    def _run(self, topics: list[str]) -> str:
        if problem := self._reading_or_error():
            return problem
        r = self.session.reading
        if r["state"]["chart"] is None:
            return "Ganita has not computed the chart yet. Call handoff_to_ganita first."
        prompt = HANDOFFS["shastra"].format(question=r["question"], topics=", ".join(topics[:2]))
        return _run_specialist(self.session, "shastra", prompt)


class HandoffSmritiTool(_ReadingTool):
    name: str = "handoff_to_smriti"
    description: str = "Optional: Smriti checks past readings, only if history could matter."
    args_schema: type[BaseModel] = NoArgs

    def _run(self, **_) -> str:
        if problem := self._reading_or_error():
            return problem
        r = self.session.reading
        r["smriti"] = True
        prompt = HANDOFFS["smriti"].format(name=self.session.profile["name"], question=r["question"])
        return _run_specialist(self.session, "smriti", prompt)


class GuardianInput(BaseModel):
    draft: str = Field(..., description="Your full draft reading, in the required structure")


class HandoffGuardianTool(_ReadingTool):
    name: str = "handoff_to_guardian"
    description: str = "Last step: the Guardian reviews your draft; the approved reading is shown to the person."
    args_schema: type[BaseModel] = GuardianInput
    # The approved result ends the turn, saving the orchestrator a call just to say "anything else?".
    # Failures are raised, and CrewAI never turns a failed tool into the answer, so a rejected
    # draft still goes back to Parashar with the reason.
    result_as_answer: bool = True

    def _run(self, draft: str) -> str:
        if problem := self._reading_or_error():
            return problem
        s, r = self.session, self.session.reading
        state = r["state"]
        if state["chart"] is None or not state["matched_rule_ids"]:
            raise ValueError("The evidence is missing. Call handoff_to_ganita and handoff_to_shastra first.")
        # Soft handoff back: an unsupported draft returns to the writer with the reason.
        if problem := check_citations(draft, state["matched_rule_ids"]):
            raise ValueError(f"Draft returned to you, not reviewed. {problem} Fix it and send it again.")

        if not r["smriti"]:
            s.emit("agent", {"agent": "smriti", "state": "skipped"})
        s.emit("agent", {"agent": "parashar", "state": "done", "output": draft})
        language = state["language"]
        prompt = HANDOFFS["guardian"].format(name=s.profile["name"], language=language, draft=draft)
        answer = _run_specialist(s, "guardian", prompt, guardrail=make_safety_guardrail(state))

        append_prediction(s.profile["name"], r["question"], answer, sorted(state["matched_rule_ids"]))
        s.delivered_reading = True
        metrics = _metrics(s)
        s.emit("reading", {"question": r["question"], "disclaimer": DISCLAIMER[language], "answer": answer,
                           "chart": state["chart"], "rules": state["matches"], "strength": state["strength"],
                           "metrics": metrics})
        s.reading = None
        return FOLLOW_UP.get(language, FOLLOW_UP["English"])


def _metrics(session: "ChatSession") -> dict:
    """Seconds, LLM calls and tokens for this reading, per agent (Parashar = the orchestrator)."""
    r = session.reading
    usage = {k: [llm.get_token_usage_summary() for llm in llms] for k, llms in r["llms"].items()}
    if session.host_llm is not None:
        usage["parashar"] = [session.host_llm.get_token_usage_summary()]
    tokens = {k: sum(u.total_tokens for u in us) for k, us in usage.items()}
    flat = [u for us in usage.values() for u in us]
    metrics = {
        "seconds_total": round(time.perf_counter() - r["started"], 1),
        "seconds_by_agent": r["seconds"],
        "tokens_by_agent": tokens,
        "llm_calls": sum(u.successful_requests for u in flat),
        "prompt_tokens": sum(u.prompt_tokens for u in flat),
        "completion_tokens": sum(u.completion_tokens for u in flat),
        "total_tokens": sum(u.total_tokens for u in flat),
        "model": make_llm().model,
    }
    with (DATA / "metrics.jsonl").open("a") as f:
        f.write(json.dumps({"timestamp": datetime.now().isoformat(timespec="seconds"),
                            "mode": "orchestrator", **metrics}) + "\n")
    return metrics


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

def run_turn(session: ChatSession, message: str, interface_language: str | None = None) -> str:
    """Run the host agent on one user message and return its reply.

    Reply language: the script the person writes in (Nepali, Japanese) wins; otherwise the
    interface language they picked; otherwise whatever was saved before.
    """
    message = SPOOFED_CONTEXT.sub("", message).strip() or "(empty message)"
    session.delivered_reading = False
    written = {"ne": "Nepali", "ja": "Japanese"}.get(detect_language(message))
    if written or interface_language:
        session.profile["language"] = written or normalize_language(interface_language)

    # Guardrail 1 runs before any LLM call, as in the CLI.
    ok, refusal = check_question(message)
    if not ok:
        reply = refusal
    else:
        session.host_llm = make_llm("low")
        host = Agent(
            role=HOST_CONFIG["role"], goal=HOST_CONFIG["goal"], backstory=HOST_CONFIG["backstory"],
            tools=[RememberDetailsTool(session=session),
                   HandoffGanitaTool(session=session), HandoffShastraTool(session=session),
                   HandoffSmritiTool(session=session), HandoffGuardianTool(session=session),
                   RecordFeedbackTool(session=session), ForgetMeTool(session=session)],
            llm=session.host_llm, guardrail=make_chat_guardrail(session), guardrail_max_retries=2,
            max_iter=12, verbose=False,
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
        try:
            with agent_span("agent: Parashar (orchestrator)"):
                reply = str(host.kickoff(messages=messages).raw).strip()
        finally:
            if session.reading is not None:  # the orchestrator stopped before the Guardian
                session.emit("council_failed", {"message": "The reading was not completed."})
                session.reading = None

    session.history += [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
    session.save()
    return reply
