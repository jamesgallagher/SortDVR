"""SortDVR CLI.

v1 = the API-first spine, dry-run only: poll recordings, apply the completion
gate, resolve the channel, and print the intended classification. Nothing is
moved yet — that lands once the classifier is validated against live data.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from sortdvr.classify import REVIEW, classify, refine
from sortdvr.config import Config
from sortdvr.dispatcharr import Dispatcharr, DispatcharrError
from sortdvr.llm import second_pass
from sortdvr.models import Recording
from sortdvr.mover import move
from sortdvr.naming import plan
from sortdvr.state import State


def _ready(cfg: Config, api: Dispatcharr) -> list[Recording]:
    recs = [Recording.from_api(d) for d in api.recordings()]
    return [r for r in recs if r.has_file() and r.is_ready(cfg.comskip_enabled)]


def _run(cfg: Config, api: Dispatcharr, state: State, go: bool) -> None:
    """Full pipeline: classify -> plan -> move. Dry-run unless go=True."""
    mode = "GO (moving files)" if go else "dry-run (no moves)"
    print(f"== route: {mode} ==")
    for r in sorted(_ready(cfg, api), key=lambda x: x.start_time, reverse=True):
        if state.is_routed(r.id):
            continue
        ch = api.channel_name(r.channel_id) if r.channel_id else ""
        d = classify(r, ch, cfg)
        llm = second_pass(r, ch, cfg) if d.needs_second_pass else None
        d = refine(d, llm)
        p = plan(r, d, ch, cfg, llm=llm)
        res = move(p, go=go)
        if res.status == "moved":
            st = "routed"
        elif d.type == REVIEW:
            st = "review"
        else:
            st = "classified"
        state.record(r.id, st, decision=d.type, confidence=d.confidence,
                     dest=res.dest, title=r.title)
        print(f"[{d.type:<6}] {res.status:<15} {r.title!r}")
        print(f"           -> {res.dest}")
        if res.detail:
            print(f"           ({res.detail})")


def _scan(cfg: Config, api: Dispatcharr, state: State) -> None:
    recs = [Recording.from_api(d) for d in api.recordings()]
    ready, waiting, pending = [], [], []
    for r in recs:
        if not r.has_file():
            pending.append(r)
        elif not r.is_ready(cfg.comskip_enabled):
            waiting.append(r)
        else:
            ready.append(r)

    print(
        f"recordings: {len(recs)} | ready: {len(ready)} | "
        f"recording/comskip: {len(waiting)} | scheduled/no-file: {len(pending)}"
    )
    print("-" * 88)
    for r in sorted(ready, key=lambda x: x.start_time, reverse=True):
        ch = api.channel_name(r.channel_id) if r.channel_id else ""
        d = classify(r, ch, cfg)
        p = plan(r, d, ch, cfg)
        seen = " [routed]" if state.is_routed(r.id) else ""
        state.record(r.id, "classified", decision=d.type, confidence=d.confidence,
                     dest=p.dest_path, title=r.title)
        tag = " (2nd-pass)" if d.needs_second_pass else ""
        print(f"[{d.type:<6}] {d.confidence:.2f}{tag}  {r.title!r}  ch={ch!r}{seen}")
        print(f"           why:  {d.reason}")
        if p.note:
            print(f"           note: {p.note}")
        print(f"           ->    {p.dest_path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sortdvr", description="DVR classifier/router")
    ap.add_argument("command", choices=["scan", "run", "watch"],
                    help="scan: inspect (read-only). run: one routing pass. "
                         "watch: routing loop on POLL_INTERVAL.")
    ap.add_argument("--go", action="store_true",
                    help="actually move files (run/watch); default is dry-run. "
                         "Can also be set via env SORTDVR_GO=true.")
    args = ap.parse_args(argv)

    go = args.go or os.environ.get("SORTDVR_GO", "").strip().lower() in ("1", "true", "yes", "on")

    cfg = Config.from_env()
    api = Dispatcharr(cfg.dispatcharr_url, cfg.api_key)
    state = State(cfg.db_path)
    try:
        if args.command == "scan":
            _scan(cfg, api, state)
        elif args.command == "run":
            _run(cfg, api, state, go)
        else:
            while True:
                _run(cfg, api, state, go)
                time.sleep(cfg.poll_interval)
    except DispatcharrError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
