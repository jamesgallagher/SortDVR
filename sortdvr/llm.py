"""LLM second pass — refine ambiguous classifications and clean movie titles.

Providers: ``groq`` (OpenAI-compatible) | ``gemini`` (REST) | ``none``. Any
failure (bad provider, network, malformed JSON) returns ``None`` so the
deterministic decision stands — a wrong guess is worse than falling back
(mirrors SpoilerFreePlexSports' design). Uses the stdlib; no SDK dependency.

Tests monkeypatch ``_call`` to avoid network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from sortdvr.config import Config
from sortdvr.models import Recording

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-1.5-flash"

SYSTEM = (
    "You classify a single recorded TV broadcast as exactly one of: movie, sport, tv. "
    "Sport means a real competition between real teams/competitors. Titles like "
    "'Batman v Superman' or 'Kramer vs Kramer' are movies, not sport. If it is a movie "
    "or tv show, return a clean title (and release year for movies). Respond ONLY as JSON."
)
SCHEMA_HINT = '{"type":"movie|sport|tv","confidence":0.0,"clean_title":"","year":null,"reasoning":""}'

_TYPE_MAP = {"movie": "MOVIE", "sport": "SPORT", "tv": "TV"}


@dataclass
class LLMResult:
    type: str  # MOVIE | SPORT | TV
    confidence: float
    clean_title: str = ""
    year: str = ""
    reasoning: str = ""


def _build_prompt(rec: Recording, channel_name: str) -> str:
    lines = [f"Filename: {rec.file_name}", f"Title: {rec.title}", f"Channel: {channel_name}"]
    if rec.sub_title:
        lines.append(f"Sub-title: {rec.sub_title}")
    if rec.description:
        lines.append(f"Description: {rec.description}")
    if rec.start_time:
        lines.append(f"Recorded (UTC): {rec.start_time}")
    lines.append(f"Respond only as JSON matching: {SCHEMA_HINT}")
    return "\n".join(lines)


def _post(url: str, headers: dict, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _groq(prompt: str, cfg: Config) -> str:
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    out = _post(GROQ_URL, {"Authorization": f"Bearer {cfg.llm_api_key}"}, body)
    return out["choices"][0]["message"]["content"]


def _gemini(prompt: str, cfg: Config) -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={cfg.llm_api_key}")
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0},
    }
    out = _post(url, {}, body)
    return out["candidates"][0]["content"]["parts"][0]["text"]


def _call(prompt: str, cfg: Config) -> str:
    if cfg.provider == "groq":
        return _groq(prompt, cfg)
    if cfg.provider == "gemini":
        return _gemini(prompt, cfg)
    raise ValueError(f"unknown LLM provider: {cfg.provider}")


def second_pass(rec: Recording, channel_name: str, cfg: Config) -> LLMResult | None:
    """Return a refined classification, or None to keep the deterministic one."""
    if cfg.provider == "none" or not cfg.llm_api_key:
        return None
    try:
        data = json.loads(_call(_build_prompt(rec, channel_name), cfg))
        typ = _TYPE_MAP.get(str(data.get("type", "")).lower())
        if not typ:
            return None
        year = data.get("year")
        return LLMResult(
            type=typ,
            confidence=float(data.get("confidence") or 0),
            clean_title=str(data.get("clean_title") or ""),
            year=str(year) if year else "",
            reasoning=str(data.get("reasoning") or ""),
        )
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None
