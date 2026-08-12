"""TMDB pass tests. `_get` is monkeypatched — no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sortdvr.tmdb as tmdb_mod  # noqa: E402
from sortdvr.tmdb import lookup  # noqa: E402

# Two films named "Normal" — only the description disambiguates them.
NORMAL = {"results": [
    {"title": "Normal", "release_date": "2003-02-01",
     "overview": "A long-married couple faces a life-changing revelation.", "popularity": 6},
    {"title": "Normal", "release_date": "2025-09-01",
     "overview": "An interim sheriff in a small Minnesota town uncovers a botched "
                 "bank robbery conspiracy.", "popularity": 40},
]}
DESC = ("The new sheriff of a small town in Minnesota uncovers a dark secret "
        "while investigating a botched bank robbery")


def test_disambiguates_by_description(monkeypatch):
    monkeypatch.setattr(tmdb_mod, "_get", lambda u, p: NORMAL)
    m = lookup("Normal", DESC, "key", record_year=2026)
    assert m.title == "Normal" and m.year == "2025"


def test_no_key_returns_none():
    assert lookup("Normal", DESC, "", 2026) is None


def test_no_results_returns_none(monkeypatch):
    monkeypatch.setattr(tmdb_mod, "_get", lambda u, p: {"results": []})
    assert lookup("Zzzznope", "", "key") is None


def test_future_release_penalised(monkeypatch):
    monkeypatch.setattr(tmdb_mod, "_get", lambda u, p: {"results": [
        {"title": "X", "release_date": "2030-01-01", "overview": "", "popularity": 100},
        {"title": "X", "release_date": "2020-01-01", "overview": "", "popularity": 1},
    ]})
    m = lookup("X", "", "key", record_year=2026)  # can't record an unreleased film
    assert m.year == "2020"
