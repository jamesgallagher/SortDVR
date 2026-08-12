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

v1, in progress. The full pipeline is built and tested — poll recordings →
gate on `completed` + Comskip done → resolve channel → classify → plan Plex/sport
path → **move** (MOVE, mtime preserved, never overwrites). Validated against live
data. Moves are **dry-run by default**; pass `--go` to act. Still to come: LLM
second pass, orphan/backstop watcher, Comskip max-wait hardening.

> **Where it runs:** SortDVR must run where it can see the files Dispatcharr
> wrote — mount the recordings share at the **same path** the API reports in
> `file_path` (`/data/recordings`). It reaches Dispatcharr over the network but
> needs the files locally to move them.

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

- `sortdvr scan` — inspect (read-only): ready recordings + planned destinations.
- `sortdvr run` — one routing pass. Dry-run unless `--go`.
- `sortdvr watch` — routing loop every `POLL_INTERVAL`. Dry-run unless `--go`.

`--go` is what actually moves files. Always watch a dry-run first.

## Deploy (Docker)

```bash
echo "DISPATCHARR_API_KEY=your-key" > .env   # gitignored
docker compose up -d --build                 # starts in dry-run
docker compose logs -f sortdvr               # confirm the planned moves look right
```

Then enable moving by uncommenting `command: ["sortdvr","watch","--go"]` in
`docker-compose.yml` and `docker compose up -d`. Edit the volume paths to match
your host; `/data/recordings` must equal Dispatcharr's `file_path` root.

| Extra var | Default | Notes |
|-----------|---------|-------|
| `DB_PATH` | `sortdvr.db` | SQLite state; set to a mounted path in Docker |
