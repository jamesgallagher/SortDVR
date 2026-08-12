"""First-pass deterministic classifier cascade.

Order (first match wins), per design.md §4:
  1. whitelist (optional escape hatch)
  2. clean season/episode -> TV
  3. versus + sport token, or dedicated sport channel -> SPORT
  4. dedicated movie channel, or (YYYY) in title -> MOVIE
  5. otherwise -> REVIEW (hand to the LLM second pass when configured)

Sport is invisible to EPG categories, so it is never decided by category — only
by these signals. The LLM second pass (gemini|groq|none) is a TODO; for now
`needs_second_pass` flags the calls that would benefit from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sortdvr.config import Config
from sortdvr.models import Recording

TV = "TV"
MOVIE = "MOVIE"
SPORT = "SPORT"
REVIEW = "REVIEW"

# "X v Y" / "X vs Y" — an ambiguity trigger, NOT sport on its own (movies like
# "Ford v Ferrari", "Kramer vs Kramer" match this too).
_VERSUS = re.compile(r"\b(?:v|vs)\b", re.IGNORECASE)
_YEAR = re.compile(r"\((?:19|20)\d{2}\)")
# Real sport signals that corroborate a versus pattern.
_SPORT_TOKENS = re.compile(
    r"\b(?:NRL|AFL|EPL|NBA|NFL|UFC|F1|Formula\s*1|rugby|cricket|tennis|golf|"
    r"netball|soccer|grand\s*prix|test\s*match|highlights|qualifying|"
    r"semi[\s-]*final|final|league|round\s*\d+)\b",
    re.IGNORECASE,
)


@dataclass
class Decision:
    type: str
    confidence: float
    reason: str
    needs_second_pass: bool = False


def _channel_type(name: str, cfg: Config) -> str | None:
    n = name.lower()
    if any(k in n for k in cfg.movie_channel_keywords):
        return MOVIE
    if any(k in n for k in cfg.sport_channel_keywords):
        return SPORT
    return None


def classify(rec: Recording, channel_name: str, cfg: Config) -> Decision:
    title = rec.title
    text = f"{title} {rec.description}"
    llm = cfg.provider != "none"

    # 1. whitelist
    if title and any(w.lower() in title.lower() for w in cfg.whitelist):
        return Decision(TV, 0.99, "whitelist")

    # 2. clean season/episode
    if rec.season and rec.episode:
        return Decision(TV, 0.97, f"S{rec.season:02d}E{rec.episode:02d}")

    ctype = _channel_type(channel_name, cfg)
    versus = bool(_VERSUS.search(title))
    sport_token = bool(_SPORT_TOKENS.search(text))

    # 3. sport — versus needs a corroborating sport token; movie channels veto
    if versus and sport_token and ctype != MOVIE:
        return Decision(SPORT, 0.9, "versus + sport token")
    if ctype == SPORT:
        return Decision(SPORT, 0.75, "dedicated sport channel", needs_second_pass=llm)

    # 4. movie
    if ctype == MOVIE:
        return Decision(MOVIE, 0.8, "dedicated movie channel", needs_second_pass=llm)
    if _YEAR.search(title):
        return Decision(MOVIE, 0.7, "year in title", needs_second_pass=llm)

    # 5. ambiguous
    return Decision(REVIEW, 0.0, "no deterministic signal", needs_second_pass=llm)


def refine(decision: Decision, llm) -> Decision:
    """Apply an LLM second-pass result (``sortdvr.llm.LLMResult`` or None).

    Only promotes an ambiguous REVIEW to a confident type; it never overrides a
    confident deterministic signal (those never request a second pass). Movie
    title/year enrichment is applied separately in ``naming.plan``.
    """
    if llm is None:
        return decision
    if decision.type == REVIEW and llm.confidence >= 0.6:
        return Decision(llm.type, llm.confidence, "llm second pass")
    return decision
