"""LLM second-pass tests. `_call` is monkeypatched — no network."""

import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sortdvr.llm as llm_mod  # noqa: E402
from sortdvr.classify import MOVIE, REVIEW, SPORT, Decision, refine  # noqa: E402
from sortdvr.config import Config  # noqa: E402
from sortdvr.llm import LLMResult, second_pass  # noqa: E402
from sortdvr.models import Recording  # noqa: E402
from sortdvr.naming import plan  # noqa: E402

CFG_GROQ = Config(dispatcharr_url="x", api_key="x", provider="groq",
                  llm_api_key="k", movie_dir="/movies")
CFG_NONE = Config(dispatcharr_url="x", api_key="x", provider="none")


def _rec(**program) -> Recording:
    return Recording.from_api({
        "id": 1, "channel": 1, "start_time": "2026-01-01T00:00:00Z",
        "custom_properties": {
            "status": "completed", "comskip": {"status": "completed"},
            "file_path": "/x.mkv", "file_name": "x.mkv", "program": program,
        },
    })


def test_none_provider_returns_none():
    assert second_pass(_rec(title="X"), "ch", CFG_NONE) is None


def test_parses_provider_json(monkeypatch):
    monkeypatch.setattr(llm_mod, "_call", lambda p, c: json.dumps(
        {"type": "movie", "confidence": 0.9, "clean_title": "Normal",
         "year": 2009, "reasoning": "a film"}))
    r = second_pass(_rec(title="Normal"), "Sky Cinema", CFG_GROQ)
    assert r.type == "MOVIE" and r.clean_title == "Normal"
    assert r.year == "2009" and r.confidence == 0.9


def test_malformed_json_returns_none(monkeypatch):
    monkeypatch.setattr(llm_mod, "_call", lambda p, c: "not json at all")
    assert second_pass(_rec(title="X"), "ch", CFG_GROQ) is None


def test_network_error_returns_none(monkeypatch):
    def boom(p, c):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(llm_mod, "_call", boom)
    assert second_pass(_rec(title="X"), "ch", CFG_GROQ) is None


def test_refine_promotes_confident_review():
    out = refine(Decision(REVIEW, 0.0, "no signal"), LLMResult("SPORT", 0.8))
    assert out.type == "SPORT" and "llm" in out.reason


def test_refine_ignores_low_confidence():
    out = refine(Decision(REVIEW, 0.0, "no signal"), LLMResult("SPORT", 0.3))
    assert out.type == REVIEW


def test_refine_overrides_weak_deterministic():
    # footy panel show on a sports channel: SPORT 0.75, LLM confidently says TV
    out = refine(Decision(SPORT, 0.75, "dedicated sport channel"), LLMResult("TV", 0.9))
    assert out.type == "TV" and "override" in out.reason


def test_refine_keeps_confident_deterministic():
    # a confident deterministic call is never overridden
    out = refine(Decision(SPORT, 0.9, "versus + sport token"), LLMResult("TV", 0.95))
    assert out.type == SPORT


def test_movie_plan_uses_llm_title_and_year():
    p = plan(_rec(title="Normal"), Decision(MOVIE, 0.8, "movie channel"),
             "Sky Cinema", CFG_GROQ, llm=LLMResult("MOVIE", 0.9, clean_title="Normal", year="2009"))
    assert p.rel_path == "Normal (2009)/Normal (2009).mkv"


if __name__ == "__main__":
    print("run with pytest (uses monkeypatch)")
