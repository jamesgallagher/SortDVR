"""Destination-path planning tests, driven by the frozen live fixture."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sortdvr.classify import SPORT, Decision, classify  # noqa: E402
from sortdvr.config import Config  # noqa: E402
from sortdvr.llm import LLMResult  # noqa: E402
from sortdvr.models import Recording  # noqa: E402
from sortdvr.naming import Plan, plan  # noqa: E402
from sortdvr.tmdb import Movie  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "recordings_20260812.json"
CFG = Config(dispatcharr_url="x", api_key="x",
             tv_dir="/tv", movie_dir="/movies", sport_dir="/sport")


def _recs() -> dict[int, Recording]:
    return {r["id"]: Recording.from_api(r) for r in json.loads(FIX.read_text())}


def _plan(rec: Recording, channel: str) -> Plan:
    return plan(rec, classify(rec, channel, CFG), channel, CFG)


def test_tv_plex_path():
    p = _plan(_recs()[79], "Channel 9")  # has EPG sub_title "Family Bathroom Week (2)"
    assert p.type == "TV"
    assert p.rel_path == "The Block/Season 22/The Block - S22E07 - Family Bathroom Week (2).mkv"
    assert p.dest_path == "/tv/" + p.rel_path
    assert p.preserve_mtime is False


def test_movie_no_year_flags_enrichment():
    p = _plan(_recs()[88], "Sky Cinema Premiere")  # "Normal", no year in title
    assert p.type == "MOVIE"
    assert p.rel_path == "Normal/Normal.mkv"
    assert "year" in p.note


def test_sport_nz_broadcaster_and_timestamp():
    p = _plan(_recs()[87], "NZ | SKY Sport 1")
    assert p.type == "SPORT"
    assert re.fullmatch(r"Sharks v All Blacks - Sky NZ_20\d{6}_\d{6}\.mkv", p.rel_path), p.rel_path
    assert p.dest_dir == "/sport"
    assert p.preserve_mtime is True  # mtime is SpoilerFree's fallback date anchor


def test_sport_supersport_strips_illegal_colon():
    p = _plan(_recs()[86], "SuperSport Grandstand FHD")  # title has a ':'
    assert p.type == "SPORT"
    assert ":" not in p.rel_path
    assert " - SuperSport_" in p.rel_path
    assert re.search(r"_20\d{6}_\d{6}\.mkv$", p.rel_path)


def test_sport_matchup_from_description():
    """Competition-titled sport (no versus in the title) lifts the matchup from
    the description and keeps the competition — the 'The Hundred' case."""
    synthetic = Recording.from_api({
        "id": 999, "channel": 1, "start_time": "2026-08-12T11:00:00Z",
        "custom_properties": {
            "status": "completed", "comskip": {"status": "completed"},
            "file_path": "/data/recordings/x.mkv", "file_name": "x.mkv",
            "program": {
                "title": "The Hundred",
                "description": ("Manchester Super Giants Women v Sunrisers Leeds Women. "
                                "A chance to see the match at Emirates Old Trafford."),
            },
        },
    })
    p = plan(synthetic, classify(synthetic, "Sky Sports Cricket", CFG), "Sky Sports Cricket", CFG)
    assert p.type == "SPORT"
    assert p.rel_path.startswith(
        "The Hundred - Manchester Super Giants Women v Sunrisers Leeds Women")
    assert "A chance to see" not in p.rel_path  # description tail not swallowed


def test_sport_gold_standard_from_llm():
    """Competition + full teams + sport, from the LLM's structured extraction."""
    rec = _recs()[87]  # 'Sharks v All Blacks' on NZ | SKY Sport 1
    llm = LLMResult("SPORT", 0.9, sport="Rugby", competition="Greatest Rivalry Tour",
                    home_team="Sharks", away_team="All Blacks")
    p = plan(rec, Decision(SPORT, 0.75, "dedicated sport channel"),
             "NZ | SKY Sport 1", CFG, llm=llm)
    assert re.fullmatch(
        r"Greatest Rivalry Tour - Sharks vs All Blacks \(Rugby\) - Sky NZ_20\d{6}_\d{6}\.mkv",
        p.rel_path), p.rel_path


def _sport_rec(title: str, description: str = "") -> Recording:
    return Recording.from_api({
        "id": 1, "channel": 1, "start_time": "2026-08-11T16:13:00Z",
        "custom_properties": {"program": {"title": title, "description": description}},
    })


def test_sport_highlights_tag_from_title():
    rec = _sport_rec("Sharks v All Blacks HLS")
    llm = LLMResult("SPORT", 0.9, sport="Rugby", competition="Greatest Rivalry Tour",
                    home_team="Sharks", away_team="All Blacks")
    p = plan(rec, Decision(SPORT, 0.9, "versus"), "Sky Sport", CFG, llm=llm)
    assert "(HLS)" in p.rel_path, p.rel_path


def test_sport_no_highlights_tag_from_description_prose():
    # "Highlights from the final..." is prose about a full match — must NOT tag
    rec = _sport_rec("UEFA Conference League Final",
                     "Highlights from the 2026 final where Crystal Palace won.")
    llm = LLMResult("SPORT", 0.9, sport="Soccer", competition="UEFA Conference League",
                    home_team="Crystal Palace", away_team="", event_name="Final")
    p = plan(rec, Decision(SPORT, 0.9, "sport channel"), "TNT Sports", CFG, llm=llm)
    assert "(HLS)" not in p.rel_path, p.rel_path
    assert "Crystal Palace" in p.rel_path, p.rel_path  # single known team kept


def test_sport_mini_tag_from_title():
    rec = _sport_rec("EPL Arsenal v Chelsea Mini")
    llm = LLMResult("SPORT", 0.9, sport="Soccer", competition="English Premier League",
                    home_team="Arsenal", away_team="Chelsea")
    p = plan(rec, Decision(SPORT, 0.9, "versus"), "Sky Sports", CFG, llm=llm)
    assert "(Mini)" in p.rel_path, p.rel_path


def test_sport_no_double_highlights_tag():
    # fallback keeps 'Highlights' from the title; don't also append (HLS)
    rec = _sport_rec("Formula 1 Highlights Miami GP", "Highlights package")
    p = plan(rec, Decision(SPORT, 0.9, "versus"), "Sky Sports", CFG, llm=None)
    assert "(hls)" not in p.rel_path.lower()
    assert "highlights" in p.rel_path.lower()


def test_movie_prefers_tmdb_over_llm_and_epg():
    p = plan(_recs()[88], Decision("MOVIE", 0.8, "movie channel"), "Sky Cinema Premiere",
             CFG, llm=LLMResult("MOVIE", 0.9, clean_title="Normal"),
             movie=Movie(title="Normal", year="2025"))
    assert p.rel_path == "Normal (2025)/Normal (2025).mkv"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
