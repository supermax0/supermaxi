"""Privacy filter: nothing patient-related or clinical may reach an external model."""
from __future__ import annotations

import re

from modules.ai_tutor.chat.knowledge import load
from modules.ai_tutor.chat.normalize import analyze

MAX_LLM_CHARS = 300
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_NUMBER = re.compile(r"\+?\d[\d\s\-]{4,}\d")

# Concept tokens that signal patient identity or clinical content.
_PHI_TOKENS = frozenset({"c:patient", "c:diagnosis"})
_PHI_FLAGS = frozenset({"m:medical"})


def redact(message: str) -> str:
    """Strip contact data and digit sequences; cap the length."""
    cleaned = _URL.sub("[رابط]", _EMAIL.sub("[بريد]", message))
    cleaned = _NUMBER.sub("[رقم]", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()[:MAX_LLM_CHARS]


def allow_llm(message: str) -> bool:
    """False for messages that mention patients or clinical matters: those are answered deterministically only."""
    a = analyze(message, set(load().vocabulary))
    return not (_PHI_TOKENS & set(a.tokens)) and not (_PHI_FLAGS & a.flags)


def build_llm_payload(message: str, context: dict, knowledge=None) -> dict:
    """Everything an external model may see: sanitised text + registry ids/titles/aliases + page/step ids."""
    kb = knowledge or load()
    return {
        "message": redact(message),
        "page": context.get("page"),
        "active_tutorial": context.get("active_tutorial"),
        "intents": [
            {"id": e.id, "title": e.title_ar, "aliases": list(e.aliases[:4])}
            for e in kb.entries.values()
        ],
    }
