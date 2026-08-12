# SortDVR

Classifies each finished Dispatcharr DVR recording as **TV**, **Movie**, or **Sport**
and moves it to the right place so Plex (TV/Movie) and
[SpoilerFreePlexSports](https://github.com/jamesgallagher/SpoilerFreePlexSports)
(Sport) can take over. SortDVR does identification + routing only.

- **TV / Movie →** Plex-format path; Plex finishes from the filename.
- **Sport →** dropped raw (filename minimally cleaned, broadcaster tag + timestamp kept,
  mtime preserved) into SpoilerFree's watch folder, which does its own identification.
- Anything it can't confidently place goes to a review queue — never guessed into Sport.

The **Dispatcharr API is the source of truth** (detection, completion gating, metadata);
the filename is a best-effort fallback. See
[design.md](../DispatcharrRecordarr/design.md) for the full design.

## Status

v1, in progress. The API-first spine is built and validated against live data:
poll recordings → gate on `completed` + Comskip done → resolve channel → classify.
**Dry-run only** so far (`scan` prints intended actions; nothing is moved yet).

## Setup

```bash
cp .env.example .env   # then fill in DISPATCHARR_URL + DISPATCHARR_API_KEY
python -m sortdvr.cli scan
```

`.env` is gitignored — never commit real keys.

## Config (env / `.env`)

| Var | Default | Notes |
|-----|---------|-------|
| `DISPATCHARR_URL` | — | required, e.g. `http://192.168.0.148:9191` |
| `DISPATCHARR_API_KEY` | — | required; sent as `X-API-Key` |
| `TV_DIR` / `MOVIE_DIR` / `SPORT_DIR` | — | move destinations |
| `TZ` | `UTC` | matches Dispatcharr |
| `LLM_PROVIDER` | `none` | `gemini` \| `groq` \| `none` (second pass) |
| `LLM_API_KEY` | — | if a provider is set |
| `COMSKIP_ENABLED` | `true` | gate waits for `comskip.status` |
| `SETTLE_MINUTES` | `15` | backstop timer for orphan files |
| `POLL_INTERVAL` | `30` | seconds, for `watch` |
| `TV_WHITELIST` | — | comma-separated show names forced to TV |

## Commands

- `sortdvr scan` — one pass, print intended classifications (dry-run).
- `sortdvr watch` — repeat every `POLL_INTERVAL`.
