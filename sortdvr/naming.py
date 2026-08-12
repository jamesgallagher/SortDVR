"""Destination-path planning per classification (pure, filesystem-free).

- TV/Movie -> Plex-format paths; Plex finishes from the name (timestamp stripped).
- Sport    -> raw handoff name for SpoilerFree: matchup (+variant) + broadcaster
              + recorder timestamp (YYYYMMDD_HHMMSS). Minimal cleaning; the mover
              preserves mtime (SpoilerFree's fallback date anchor).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sortdvr.classify import MOVIE, REVIEW, SPORT, TV, Decision
from sortdvr.config import Config
from sortdvr.models import Recording

_ILLEGAL = re.compile(r'[\\/:*?"<>|]+')
_YEAR = re.compile(r"\((?:19|20)\d{2}\)")
_VERSUS = re.compile(r"\b(?:v|vs)\b", re.IGNORECASE)
# Leading capital, up to a versus, then the opponent — stops at sentence end
# (no '.' in the trailing class) so we don't swallow the rest of the description.
_VERSUS_CLAUSE = re.compile(r"([A-Za-z][\w'&\- ]*\b(?:v|vs)\b[\w'&\- ]+)")


def safe(name: str) -> str:
    """Strip filesystem-illegal characters; keep spaces, -, (), &, apostrophes."""
    return _ILLEGAL.sub("", name or "").strip()


def timestamp(rec: Recording) -> str:
    """Recorder start as YYYYMMDD_HHMMSS (UTC) — matches SpoilerFree's regex."""
    try:
        dt = datetime.fromisoformat(rec.start_time.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
    except (ValueError, AttributeError):
        m = re.search(r"(20\d{6}_\d{6})", rec.file_name)  # fall back to filename
        return m.group(1) if m else ""


@dataclass
class Plan:
    type: str
    rel_path: str        # relative to this type's destination dir
    dest_dir: str        # configured dir ("" if unset)
    source_path: str     # file_path from the API
    preserve_mtime: bool
    note: str = ""

    @property
    def dest_path(self) -> str:
        if not self.dest_dir:
            return self.rel_path
        return str(PurePosixPath(self.dest_dir) / self.rel_path)


def _movie_year(title: str) -> str:
    m = _YEAR.search(title)
    return m.group(0)[1:-1] if m else ""


def _sport_matchup(rec: Recording) -> str:
    """Fallback matchup when the LLM gave nothing: prefer a versus clause from
    the title, else lift one from the description (the 'The Hundred' case)."""
    title = rec.title.strip()
    if _VERSUS.search(title):
        return title
    m = _VERSUS_CLAUSE.search(rec.description or "")
    if m:
        clause = m.group(1).strip().rstrip(".")
        return f"{title} - {clause}" if title else clause
    return title  # competition-only; SpoilerFree still attempts identification


def _sport_name(rec: Recording, llm) -> str:
    """Gold-standard sport name for TheSportsDB matching (design research):
    ``{Competition} - {Home} vs {Away} ({Sport})``. Teams + sport are what the
    matcher keys on; competition is a helpful extra. Falls back to the raw
    matchup when the LLM is absent or gave no usable participants.
    """
    if llm and llm.type == SPORT and ((llm.home_team and llm.away_team) or llm.event_name):
        core = f"{llm.home_team} vs {llm.away_team}" if llm.home_team and llm.away_team \
            else llm.event_name.strip()
        name = f"{llm.competition.strip()} - {core}" if llm.competition.strip() else core
        if llm.sport.strip():
            name = f"{name} ({llm.sport.strip()})"
        return safe(name)
    return safe(_sport_matchup(rec))


def plan(rec: Recording, decision: Decision, channel_name: str, cfg: Config,
         llm=None, movie=None) -> Plan:
    t = decision.type

    if t == TV:
        show = safe(rec.title)
        season, episode = rec.season or 0, rec.episode or 0
        base = f"{show} - S{season:02d}E{episode:02d}"
        sub = safe(rec.sub_title)
        if sub:
            base += f" - {sub}"
        rel = f"{show}/Season {season:02d}/{base}.mkv"
        return Plan(TV, rel, cfg.tv_dir, rec.file_path, preserve_mtime=False)

    if t == MOVIE:
        # priority: TMDB (authoritative) > LLM clean title > EPG title
        if movie and movie.title:
            title, year = safe(movie.title), movie.year
        elif llm and llm.clean_title:
            title, year = safe(llm.clean_title), (llm.year or _movie_year(rec.title))
        else:
            title, year = safe(_YEAR.sub("", rec.title).strip()), _movie_year(rec.title)
        if year:
            name = f"{title} ({year})"
            return Plan(MOVIE, f"{name}/{name}.mkv", cfg.movie_dir, rec.file_path, False)
        return Plan(MOVIE, f"{title}/{title}.mkv", cfg.movie_dir, rec.file_path, False,
                    note="no year; TMDB had no confident match")

    if t == SPORT:
        parts = _sport_name(rec, llm)
        bcast = cfg.broadcaster_for(channel_name)
        if bcast:
            parts += f" - {bcast}"
        ts = timestamp(rec)
        if ts:
            parts += f"_{ts}"
        return Plan(SPORT, f"{parts}.mkv", cfg.sport_dir, rec.file_path, preserve_mtime=True)

    return Plan(REVIEW, safe(rec.file_name) or f"recording_{rec.id}.mkv", "",
                rec.file_path, preserve_mtime=True, note="needs review / second pass")
