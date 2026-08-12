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
from datetime import datetime, timezone

from sortdvr import __version__
from sortdvr.classify import REVIEW, classify, refine
from sortdvr.config import Config
from sortdvr.dispatcharr import Dispatcharr, DispatcharrError
from sortdvr.llm import build_prompt, second_pass
from sortdvr.models import Recording
from sortdvr.mover import move
from sortdvr.naming import plan
from sortdvr.state import State


def _buckets(cfg: Config, recs: list[Recording]):
    ready, waiting, pending = [], [], []
    for r in recs:
        if not r.has_file():
            pending.append(r)
        elif not r.is_ready(cfg.comskip_enabled):
            waiting.append(r)
        else:
            ready.append(r)
    return ready, waiting, pending


def _run(cfg: Config, api: Dispatcharr, state: State, go: bool, pass_no: int) -> None:
    """Full pipeline: classify -> (LLM) -> plan -> move. Dry-run unless go=True."""
    recs = [Recording.from_api(d) for d in api.recordings()]
    ready, waiting, pending = _buckets(cfg, recs)
    mode = "GO (moving files)" if go else "DRY-RUN (no moves)"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"\n-- SortDVR v{__version__} | pass #{pass_no} | {now} | {mode} --")
    print(f"   recordings: {len(recs)} | ready: {len(ready)} | "
          f"recording/comskip: {len(waiting)} | scheduled: {len(pending)}")

    for r in sorted(ready, key=lambda x: x.start_time, reverse=True):
        if state.is_routed(r.id):
            print(f"\n> {r.title!r} - already routed, skipping")
            continue
        ch = api.channel_name(r.channel_id) if r.channel_id else ""
        print(f"\n> {r.title!r}  ch={ch!r}")
        print(f"   file: {r.file_name}")

        d0 = classify(r, ch, cfg)
        print(f"   pass 1 (deterministic) → {d0.type}  ({d0.reason})")

        llm = None
        if d0.needs_second_pass:
            if cfg.verbose:
                print(f"   pass 2 (LLM: {cfg.provider}) prompt:")
                for line in build_prompt(r, ch).splitlines():
                    print(f"       | {line}")
            llm = second_pass(r, ch, cfg)
            if llm:
                print(f"   pass 2 → {llm.type} conf={llm.confidence:.2f} "
                      f"title={llm.clean_title!r} year={llm.year or '-'}")
                if cfg.verbose and llm.reasoning:
                    print(f"       reasoning: {llm.reasoning}")
            else:
                print(f"   pass 2 → no result (provider={cfg.provider}); kept deterministic")
        else:
            print("   pass 2 → skipped (deterministic result is confident)")

        d = refine(d0, llm)
        p = plan(r, d, ch, cfg, llm=llm)
        res = move(p, go=go)
        st = "routed" if res.status == "moved" else ("review" if d.type == REVIEW else "classified")
        state.record(r.id, st, decision=d.type, confidence=d.confidence,
                     dest=res.dest, title=r.title)

        print(f"   result: {d.type} → {res.dest}")
        if res.status == "moved":
            print("   MOVED")
        elif res.status == "dry-run":
            print("   not moved (SORTDVR_GO=false - dry-run)")
        else:
            print(f"   {res.status}: {res.detail}")


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

    # Print arbitrary recording titles safely regardless of console encoding.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    go = args.go or os.environ.get("SORTDVR_GO", "").strip().lower() in ("1", "true", "yes", "on")

    cfg = Config.from_env()
    print("=" * 64)
    print(f" SortDVR v{__version__} - DVR recording classifier/router")
    print(" Routes finished Dispatcharr recordings into TV / Movie / Sport.")
    print(f" Dispatcharr : {cfg.dispatcharr_url}")
    print(f" Provider    : {cfg.provider}   Comskip: {cfg.comskip_enabled}   "
          f"Move(GO): {go}   Verbose: {cfg.verbose}")
    print(f" Command     : {args.command}   Poll: {cfg.poll_interval}s")
    print("=" * 64)

    api = Dispatcharr(cfg.dispatcharr_url, cfg.api_key)
    state = State(cfg.db_path)
    try:
        if args.command == "scan":
            _scan(cfg, api, state)
        elif args.command == "run":
            _run(cfg, api, state, go, pass_no=1)
        else:
            pass_no = 1
            while True:
                _run(cfg, api, state, go, pass_no)
                pass_no += 1
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
