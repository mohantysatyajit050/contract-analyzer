"""
In-memory store for contract analysis sessions.

This is a placeholder so the API is runnable without a database. Swap for
Postgres/Redis before this goes anywhere near production -- state will be
lost on every server restart and won't work across multiple workers.
"""
from typing import Dict

_sessions: Dict[str, dict] = {}


def save_session(state: dict) -> None:
    _sessions[state["session_id"]] = state


def get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise KeyError(f"Unknown session_id: {session_id}")
    return _sessions[session_id]