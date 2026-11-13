"""The AI writer the Brain thinks with.

Reuses the writers the studio already has (Ollama, Gemini, Hugging Face). There is
no rule-based fallback here on purpose: if no AI writer is connected the Brain says
so instead of pretending.
"""
from __future__ import annotations

import json
import logging
import re

from ..config import settings
from ..providers.llm import WRITERS, NetworkError, WriterError


log = logging.getLogger(__name__)


class BrainUnavailable(RuntimeError):
    pass


NO_LLM_HELP = (
    "The AI Director needs an AI writer, and none is connected yet. The free option: create a key at "
    "https://aistudio.google.com/apikey, put GEMINI_API_KEY=your-key in the .env file, and restart the app. "
    "(Ollama running on your own computer also works.)"
)


def available_llms() -> list:
    """Connected AI writers, best first. LLM_PROVIDER, when it names one, goes first."""
    order = ["gemini", "ollama", "huggingface"]
    if settings.llm_provider in order:
        order.remove(settings.llm_provider)
        order.insert(0, settings.llm_provider)
    return [WRITERS[n] for n in order if WRITERS[n].available()]


def pick_llm():
    """The connected AI writer, or None."""
    ws = available_llms()
    return ws[0] if ws else None


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
        # other connected writers to switch to if this one cannot be reached
        self.backups = [w for w in available_llms() if w is not self.writer] if writer is None else []
        self.calls = 0
        self.switched: list[str] = []

    def _complete(self, prompt: str) -> str:
        while True:
            try:
                return self.writer.complete(prompt)
            except NetworkError as e:
                if not self.backups:
                    raise
                old, self.writer = self.writer, self.backups.pop(0)
                self.switched.append(f"{old.label} could not be reached, switched to {self.writer.label}")
                log.warning("%s; switching AI writer: %s", e, self.writer.label)
                self.calls += 1

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
            text = self._complete(prompt if i == 0 else prompt + "\n\nYour last reply was not valid JSON. Reply with JSON only.")
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
