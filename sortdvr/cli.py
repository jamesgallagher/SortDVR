"""SortDVR CLI.

v1 = the API-first spine, dry-run only: poll recordings, apply the completion
gate, resolve the channel, and print the intended classification. Nothing is
moved yet — that lands once the classifier is validated against live data.
"""

from __future__ import annotations

import argparse
import sys
import time

from sortdvr.classify import classify
from sortdvr.config import Config
from sortdvr.dispatcharr import Dispatcharr, DispatcharrError
from sortdvr.models import Recording


def _scan(cfg: Config, api: Dispatcharr) -> None:
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
        tag = " (2nd-pass)" if d.needs_second_pass else ""
        bcast = cfg.broadcaster_for(ch)
        extra = f"  broadcaster={bcast}" if d.type == "SPORT" and bcast else ""
        print(f"[{d.type:<6}] {d.confidence:.2f}{tag}  {r.title!r}  ch={ch!r}{extra}")
        print(f"           why:  {d.reason}")
        print(f"           file: {r.file_name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sortdvr", description="DVR classifier/router")
    ap.add_argument("command", choices=["scan", "watch"],
                    help="scan once, or watch on POLL_INTERVAL")
    args = ap.parse_args(argv)

    cfg = Config.from_env()
    api = Dispatcharr(cfg.dispatcharr_url, cfg.api_key)
    try:
        if args.command == "scan":
            _scan(cfg, api)
        else:
            while True:
                _scan(cfg, api)
                time.sleep(cfg.poll_interval)
    except DispatcharrError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
