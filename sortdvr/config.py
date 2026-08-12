"""SortDVR configuration — loaded from the environment (.env supported).

Decisions baked in (see design.md): API is required and is the source of truth;
TZ defaults to UTC to match Dispatcharr; the second pass is gemini|groq|none.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


# Channel-name keyword -> dedicated type. A strong bias, never an override
# (a sports channel still airs studio/panel TV), applied below whitelist + S/E.
DEFAULT_MOVIE_CHANNEL_KEYWORDS = ("cinema", "movies", "film")
DEFAULT_SPORT_CHANNEL_KEYWORDS = (
    "sport", "sports", "espn", "supersport", "kayo", "eurosport", "fox league",
)

# Channel-name (lowercased) -> short broadcaster tag, appended to sport handoff
# filenames so same-game-different-broadcaster recordings are both kept (§9.8).
# Longest/most-specific keys first — matching walks these in order.
DEFAULT_BROADCASTER_MAP: tuple[tuple[str, str], ...] = (
    ("sky sport new zealand", "Sky NZ"),
    ("nz | sky", "Sky NZ"),  # channels are named "NZ | SKY Sport 1"
    ("sky sports", "Sky"),
    ("sky sport", "Sky"),
    ("sky cinema", "Sky"),
    ("fox", "Fox"),
    ("tnt", "TNT"),
    ("premier sport", "Premier"),
    ("supersport", "SuperSport"),
    ("stan", "Stan"),
    ("kayo", "Kayo"),
)


@dataclass
class Config:
    dispatcharr_url: str
    api_key: str
    # Defaults are the standard container mount targets, so the destination env
    # vars are optional — the volume mount alone is enough (see the Unraid template).
    inbox: str = "/data/recordings"
    tv_dir: str = "/media/TV_Shows"
    movie_dir: str = "/media/Movies"
    sport_dir: str = "/watch"
    tz: str = "UTC"
    provider: str = "none"  # gemini | groq | none
    llm_api_key: str = ""
    comskip_enabled: bool = True
    settle_minutes: int = 15
    poll_interval: int = 30
    db_path: str = "sortdvr.db"
    whitelist: tuple[str, ...] = ()
    movie_channel_keywords: tuple[str, ...] = DEFAULT_MOVIE_CHANNEL_KEYWORDS
    sport_channel_keywords: tuple[str, ...] = DEFAULT_SPORT_CHANNEL_KEYWORDS
    broadcaster_map: tuple[tuple[str, str], ...] = DEFAULT_BROADCASTER_MAP

    def broadcaster_for(self, channel_name: str) -> str:
        """Short broadcaster tag for a channel name, or "" if unmapped."""
        n = channel_name.lower()
        for needle, tag in self.broadcaster_map:
            if needle in n:
                return tag
        return ""

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv()
        url = os.environ.get("DISPATCHARR_URL", "").rstrip("/")
        key = os.environ.get("DISPATCHARR_API_KEY", "")
        if not url or not key:
            raise SystemExit(
                "DISPATCHARR_URL and DISPATCHARR_API_KEY are required "
                "(set them in .env — see .env.example)"
            )
        whitelist = tuple(
            s.strip() for s in os.environ.get("TV_WHITELIST", "").split(",") if s.strip()
        )
        return cls(
            dispatcharr_url=url,
            api_key=key,
            inbox=os.environ.get("INBOX", "/data/recordings"),
            tv_dir=os.environ.get("TV_DIR", "/media/TV_Shows"),
            movie_dir=os.environ.get("MOVIE_DIR", "/media/Movies"),
            sport_dir=os.environ.get("SPORT_DIR", "/watch"),
            tz=os.environ.get("TZ", "UTC"),
            provider=os.environ.get("LLM_PROVIDER", "none").lower(),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            comskip_enabled=os.environ.get("COMSKIP_ENABLED", "true").lower() != "false",
            settle_minutes=int(os.environ.get("SETTLE_MINUTES", "15")),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "30")),
            db_path=os.environ.get("DB_PATH", "sortdvr.db"),
            whitelist=whitelist,
        )
