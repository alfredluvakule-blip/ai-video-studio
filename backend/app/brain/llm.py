"""The AI writer the Brain thinks with.

Reuses the writers the studio already has (Ollama, Gemini, Hugging Face). There is
no rule-based fallback here on purpose: if no AI writer is connected the Brain says
so instead of pretending.
"""
from __future__ import annotations

import json
import re

from ..config import settings
from ..providers.llm import WRITERS, WriterError


class BrainUnavailable(RuntimeError):
    pass


NO_LLM_HELP = (
    "The AI Director needs an AI writer, and none is connected yet. The free option: create a key at "
    "https://aistudio.google.com/apikey, put GEMINI_API_KEY=your-key in the .env file, and restart the app. "
    "(Ollama running on your own computer also works.)"
)


def pick_llm():
    """The connected AI writer, or None. Honors LLM_PROVIDER when it names an AI writer."""
    choice = settings.llm_provider
    if choice in WRITERS and choice != "template" and WRITERS[choice].available():
        return WRITERS[choice]
    for name in ("gemini", "ollama", "huggingface"):
        if WRITERS[name].available():
            return WRITERS[name]
    return None


def status() -> dict:
    w = pick_llm()
    return {"available": bool(w), "name": w.name if w else None, "label": w.label if w else None,
            "help": None if w else NO_LLM_HELP}


def parse_json(text: str):
    """The first JSON object or array in a model reply (models sometimes add prose or code fences)."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise WriterError("the AI reply contained no JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start : end + 1])
    except Exception as e:
        raise WriterError(f"the AI reply was not valid JSON ({e})") from e


class Brain:
    """A session with one AI writer that counts the calls it makes (usage tracking)."""

    def __init__(self, writer=None):
        self.writer = writer or pick_llm()
        if not self.writer:
            raise BrainUnavailable(NO_LLM_HELP)
        self.calls = 0

    @property
    def label(self) -> str:
        return self.writer.label

    @property
    def name(self) -> str:
        return self.writer.name

    def ask_json(self, prompt: str, expect: type = dict, attempts: int = 2):
        """Ask for JSON. A reply that is not usable JSON is retried once (bounded)."""
        last: Exception | None = None
        for i in range(attempts):
            self.calls += 1
            text = self.writer.complete(prompt if i == 0 else prompt + "\n\nYour last reply was not valid JSON. Reply with JSON only.")
            try:
                data = parse_json(text)
            except WriterError as e:
                last = e
                continue
            if expect is dict and isinstance(data, list) and data and isinstance(data[0], dict) and len(data) == 1:
                data = data[0]
            if expect is list and isinstance(data, dict):
                for v in data.values():  # {"scenes": [...]} is fine too
                    if isinstance(v, list):
                        data = v
                        break
            if isinstance(data, expect):
                return data
            last = WriterError(f"expected a JSON {expect.__name__}, got {type(data).__name__}")
        raise WriterError(str(last))


def clean(v, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]
