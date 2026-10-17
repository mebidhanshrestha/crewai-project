"""Persistence: Prediction Ledger, encrypted birth profiles, chat sessions, delete-on-request.

Birth details are personal data, so profiles are encrypted at rest with Fernet
(AES-128 + HMAC). The key comes from PROFILE_KEY in .env, or is generated once into
data/.profile_key (git-ignored). In production the key would live in a secrets manager.
"""

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# Where readings, profiles and chats are written. Vercel's code folder is read-only, so there
# they go to /tmp, which is temporary: it resets whenever Vercel starts a fresh instance.
DATA = Path(os.getenv("JYOTISHA_DATA_DIR")
            or ("/tmp/jyotisha" if os.getenv("VERCEL") else Path(__file__).resolve().parent / "data"))
DATA.mkdir(parents=True, exist_ok=True)
LEDGER_PATH = DATA / "ledger.json"
PROFILES_PATH = DATA / "profiles.enc"
KEY_PATH = DATA / ".profile_key"
SESSIONS_DIR = DATA / "sessions"
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_lock = threading.RLock()  # one writer at a time across concurrent readings


# --- Prediction Ledger --------------------------------------------------------

def read_ledger() -> list[dict]:
    with _lock:
        return json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else []


def write_ledger(entries: list[dict]) -> None:
    with _lock:
        LEDGER_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


def append_prediction(name: str, question: str, answer: str, rule_ids: list[str]) -> None:
    """Called by code after the Guardian approves, never by an agent."""
    with _lock:
        entries = read_ledger()
        entries.append({
            "id": max((e["id"] for e in entries), default=0) + 1,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "name": name,
            "question": question,
            "answer": answer,
            "rule_ids": sorted(rule_ids),
            "outcome": None,  # filled in later: "happened" / "did_not_happen"
        })
        write_ledger(entries)


def set_outcome(entry_id: int, outcome: str) -> dict | None:
    with _lock:
        entries = read_ledger()
        for e in entries:
            if e["id"] == entry_id:
                e["outcome"] = outcome
                write_ledger(entries)
                return e
    return None


def ledger_for(name: str) -> list[dict]:
    return [e for e in read_ledger() if e["name"].lower() == name.strip().lower()]


# --- Encrypted profiles -----------------------------------------------------------

def _fernet() -> Fernet:
    key = os.getenv("PROFILE_KEY")
    if not key:
        with _lock:
            if not KEY_PATH.exists():
                KEY_PATH.write_bytes(Fernet.generate_key())
                KEY_PATH.chmod(0o600)
            key = KEY_PATH.read_bytes().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def load_profiles() -> dict:
    with _lock:
        if not PROFILES_PATH.exists():
            return {}
        try:
            return json.loads(_fernet().decrypt(PROFILES_PATH.read_bytes()))
        except InvalidToken:
            raise RuntimeError("profiles.enc cannot be decrypted with the current PROFILE_KEY")


def save_profile(profile: dict) -> None:
    with _lock:
        profiles = load_profiles()
        profiles[profile["name"].lower()] = profile
        PROFILES_PATH.write_bytes(_fernet().encrypt(json.dumps(profiles, ensure_ascii=False).encode()))


def get_profile(name: str) -> dict | None:
    return load_profiles().get(name.strip().lower())


def forget_person(name: str) -> dict:
    """Delete-on-request: remove the person's profile and every ledger entry."""
    key = name.strip().lower()
    with _lock:
        profiles = load_profiles()
        had_profile = profiles.pop(key, None) is not None
        PROFILES_PATH.write_bytes(_fernet().encrypt(json.dumps(profiles, ensure_ascii=False).encode()))
        entries = read_ledger()
        kept = [e for e in entries if e["name"].lower() != key]
        write_ledger(kept)
    return {"profile_deleted": had_profile, "readings_deleted": len(entries) - len(kept)}


# --- Chat sessions (survive a server restart) ----------------------------------

def _session_path(session_id: str) -> Path:
    if not SESSION_ID.match(session_id):
        raise ValueError("Invalid session id")
    return SESSIONS_DIR / f"{session_id}.json"


def load_session(session_id: str) -> dict | None:
    path = _session_path(session_id)
    return json.loads(path.read_text()) if path.exists() else None


def save_session(session_id: str, data: dict) -> None:
    with _lock:
        SESSIONS_DIR.mkdir(exist_ok=True)
        _session_path(session_id).write_text(json.dumps(data, ensure_ascii=False))


def delete_sessions_for(name: str) -> int:
    """Chat transcripts contain birth details too, so forgetting someone removes them."""
    removed = 0
    with _lock:
        for path in SESSIONS_DIR.glob("*.json") if SESSIONS_DIR.exists() else []:
            data = json.loads(path.read_text())
            if (data.get("profile", {}).get("name") or "").lower() == name.strip().lower():
                path.unlink()
                removed += 1
    return removed
