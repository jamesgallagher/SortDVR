"""LLM second pass — refine ambiguous classifications and clean movie titles.

Providers: ``groq`` (OpenAI-compatible) | ``gemini`` (REST) | ``none``. Any
failure (bad provider, network, malformed JSON) returns ``None`` so the
deterministic decision stands — a wrong guess is worse than falling back
(mirrors SpoilerFreePlexSports' design). Uses the stdlib; no SDK dependency.

Tests monkeypatch ``_call`` to avoid network.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from sortdvr import __version__
from sortdvr.config import Config
from sortdvr.models import Recording

# Groq/Gemini sit behind Cloudflare, which 403s the default urllib User-Agent
# as bot traffic. A real UA is required or every call fails.
_USER_AGENT = f"SortDVR/{__version__}"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Models are set in config (groq_model / gemini_model). llama-3.3-70b-versatile
# is decommissioned 2026-08-16; gemini-1.5/2.0-flash are retired. Both the
# gpt-oss and current gemini-flash models are reasoning/thinking models — see
# _groq (reasoning_effort) and _gemini (thinkingBudget).

SYSTEM = (
    "You classify a single recorded TV broadcast as exactly one of: movie, sport, tv. "
    "Sport means a real competition between real teams/competitors. Titles like "
    "'Batman v Superman' or 'Kramer vs Kramer' are movies, not sport.\n"
    "- movie/tv: return a clean title (and release year for movies if you are certain; "
    "leave year null rather than guessing).\n"
    "- sport: extract, from the title AND description, the fields a sports database "
    "needs. Use FULL names as a sports database would list them. 'sport' is the sport "
    "itself (Rugby, Cricket, Soccer, Motorsport...). For team events fill home_team and "
    "away_team (in 'A v B', A is home); leave them empty for non-team events (races, "
    "tours, tennis) and put the specific session in event_name. 'competition' is the "
    "league/tournament/series.\n"
    "Respond ONLY as JSON."
)
SCHEMA_HINT = (
    '{"type":"movie|sport|tv","confidence":0.0,"clean_title":"","year":null,'
    '"sport":"","competition":"","home_team":"","away_team":"","event_name":"",'
    '"reasoning":""}'
)

_TYPE_MAP = {"movie": "MOVIE", "sport": "SPORT", "tv": "TV"}


@dataclass
class LLMResult:
    type: str  # MOVIE | SPORT | TV
    confidence: float
    clean_title: str = ""
    year: str = ""
    sport: str = ""
    competition: str = ""
    home_team: str = ""
    away_team: str = ""
    event_name: str = ""
    reasoning: str = ""


def build_prompt(rec: Recording, channel_name: str) -> str:
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
        headers={**headers, "Content-Type": "application/json", "User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _groq(prompt: str, cfg: Config) -> str:
    body = {
        "model": cfg.groq_model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    # gpt-oss are reasoning models: in JSON mode they intermittently spend the
    # whole budget on hidden reasoning and return EMPTY content (Groq then 400s
    # json_validate_failed). "low" effort fixes it for mechanical tasks and is
    # faster/cheaper. Scoped so a non-gpt-oss override isn't sent an unknown param.
    if cfg.groq_model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
    out = _post(GROQ_URL, {"Authorization": f"Bearer {cfg.llm_api_key}"}, body)
    return out["choices"][0]["message"]["content"]


def _gemini(prompt: str, cfg: Config) -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg.gemini_model}:generateContent?key={cfg.llm_api_key}")
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0,
            # gemini-flash is a thinking model — disable it for mechanical tasks
            # (Gemini's equivalent of Groq reasoning_effort=low): reliable, faster.
            "thinkingConfig": {"thinkingBudget": 0},
        },
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
        data = json.loads(_call(build_prompt(rec, channel_name), cfg))
        typ = _TYPE_MAP.get(str(data.get("type", "")).lower())
        if not typ:
            return None
        year = data.get("year")
        return LLMResult(
            type=typ,
            confidence=float(data.get("confidence") or 0),
            clean_title=str(data.get("clean_title") or ""),
            year=str(year) if year else "",
            sport=str(data.get("sport") or ""),
            competition=str(data.get("competition") or ""),
            home_team=str(data.get("home_team") or ""),
            away_team=str(data.get("away_team") or ""),
            event_name=str(data.get("event_name") or ""),
            reasoning=str(data.get("reasoning") or ""),
        )
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode(errors="replace") if hasattr(e, "read") else ""
        print(f"   [llm] {cfg.provider} HTTP {e.code}: {body}", file=sys.stderr)
        return None
    except Exception as e:  # never let a second-pass failure break routing
        print(f"   [llm] {cfg.provider} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None
