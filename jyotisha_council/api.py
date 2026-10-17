"""HTTP API for the React chat app.

    uvicorn api:app --port 8000

POST /api/chat streams Server-Sent Events for one chat turn:
  thinking -> [profile] -> [council_started -> agent (working/done) x5 -> reading] -> reply -> end
"""

import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chat import get_session, run_turn
from common import explain_llm_error, missing_key, normalize_language
from guardrails import detect_language
from store import SESSION_ID, delete_sessions_for, forget_person, ledger_for, set_outcome

app = FastAPI(title="Jyotisha Council API")


class ChatRequest(BaseModel):
    session_id: str
    message: str
    language: str | None = None  # the interface language the person picked


class Outcome(BaseModel):
    outcome: str  # "happened" | "did_not_happen"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    if not SESSION_ID.match(req.session_id):
        raise HTTPException(400, "Invalid session id")
    return StreamingResponse(chat_stream(req), media_type="text/event-stream")


def chat_stream(req: ChatRequest):
    if problem := missing_key():
        yield sse("error", {"message": problem})
        return

    session = get_session(req.session_id)
    # Reply in the language the person writes in; otherwise in the interface language they picked.
    written = {"ne": "Nepali", "ja": "Japanese"}.get(detect_language(req.message))
    if written or req.language:
        session.profile["language"] = written or normalize_language(req.language)
    events: queue.Queue = queue.Queue()
    session.emit = lambda event, data: events.put((event, data))

    def work() -> None:
        try:
            reply = run_turn(session, req.message.strip())
            events.put(("reply", {"text": reply}))
        except Exception as exc:
            events.put(("error", {"message": explain_llm_error(exc)}))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    yield sse("thinking", {})
    while (item := events.get()) is not None:
        yield sse(*item)
    yield sse("end", {"profile": session.profile, "missing": session.missing()})


@app.get("/api/ledger")
def ledger(name: str) -> list[dict]:
    return ledger_for(name)


@app.post("/api/ledger/{entry_id}/outcome")
def outcome(entry_id: int, body: Outcome) -> dict:
    if body.outcome not in ("happened", "did_not_happen"):
        raise HTTPException(400, "outcome must be 'happened' or 'did_not_happen'")
    entry = set_outcome(entry_id, body.outcome)
    if entry is None:
        raise HTTPException(404, "No such ledger entry")
    return entry


@app.delete("/api/person")
def forget(name: str) -> dict:
    """Delete-on-request: birth details, readings and chat transcripts for this name."""
    result = forget_person(name)
    result["chats_deleted"] = delete_sessions_for(name)
    return result


# Serve the built React app (frontend/dist) when it exists: one server for everything.
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        return FileResponse(DIST / "index.html")
