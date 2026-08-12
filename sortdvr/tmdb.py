"""TMDB pass 3 — authoritative movie title + year.

The LLM must never guess a year (it hallucinates and can't know recent films).
Instead we search TMDB by the LLM's clean title, then disambiguate candidates
against the EPG description (TMDB carries plot overviews), preferring releases
on/before the recording date. Returns a Movie or None; any failure leaves the
LLM/EPG values in place. Tests monkeypatch ``_get``.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from sortdvr import __version__

_SEARCH = "https://api.themoviedb.org/3/search/movie"
_UA = f"SortDVR/{__version__}"


@dataclass
class Movie:
    title: str
    year: str


def _get(url: str, params: dict) -> dict:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 3}


def lookup(title: str, description: str, api_key: str,
           record_year: int | None = None) -> Movie | None:
    if not title or not api_key:
        return None
    try:
        data = _get(_SEARCH, {"api_key": api_key, "query": title})
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
        print(f"   [tmdb] lookup failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None

    results = data.get("results") or []
    if not results:
        return None

    desc = _tokens(description)

    def score(m: dict) -> float:
        overlap = len(desc & _tokens(m.get("overview", ""))) if desc else 0
        pop = float(m.get("popularity") or 0)
        yr = (m.get("release_date") or "")[:4]
        # a broadcast can't be of an unreleased film — penalise later years
        future = record_year and yr.isdigit() and int(yr) > record_year
        return overlap * 100 + pop - (1e6 if future else 0)

    best = max(results, key=score)
    yr = (best.get("release_date") or "")[:4]
    return Movie(title=best.get("title") or title, year=yr if yr.isdigit() else "")
