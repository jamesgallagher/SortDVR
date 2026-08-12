"""Lifecycle-gate regression tests against a frozen live snapshot.

Fixture captured from Dispatcharr 192.168.0.148 on 2026-08-12; it happens to
include the whole lifecycle at once: in-flight (status=recording, file exists),
done (completed + comskip terminal), and scheduled (no status/file yet). This
pins the completed/in-flight/comskip gating so it can't silently regress.

Run: `python -m pytest -q`  (or `python tests/test_gate.py` standalone).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sortdvr.models import Recording  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "recordings_20260812.json"

# recording id -> expected bucket, given COMSKIP_ENABLED=True
EXPECTED = {
    90: "waiting",  # Ace Ventura — status=recording (in-flight, file exists)
    91: "waiting",  # The Block   — status=recording (in-flight)
    88: "ready",    # Normal            — completed + comskip completed
    86: "ready",    # SHA v NZL         — completed + comskip completed
    87: "ready",    # Sharks v All Blacks — completed + comskip completed
    79: "ready",    # The Block S22E07  — completed + comskip completed
    83: "pending",  # The Block — scheduled (no status/file)
    80: "pending",  # scheduled
    81: "pending",  # scheduled
}


def _bucket(rec: Recording, comskip_enabled: bool = True) -> str:
    if not rec.has_file():
        return "pending"
    if not rec.is_ready(comskip_enabled):
        return "waiting"
    return "ready"


def _load() -> list[Recording]:
    return [Recording.from_api(d) for d in json.loads(FIXTURE.read_text())]


def test_every_recording_bucketed_as_expected():
    recs = {r.id: r for r in _load()}
    assert set(recs) == set(EXPECTED)
    for rid, expected in EXPECTED.items():
        assert _bucket(recs[rid]) == expected, f"rec {rid} expected {expected}"


def test_bucket_counts():
    buckets = [_bucket(r) for r in _load()]
    assert buckets.count("ready") == 4
    assert buckets.count("waiting") == 2
    assert buckets.count("pending") == 3


def test_inflight_never_ready():
    """A recording still in progress must never gate ready, file or not."""
    r = {x.id: x for x in _load()}[90]
    assert r.status == "recording"
    assert r.has_file() is True
    assert r.is_ready(comskip_enabled=True) is False


def test_completed_requires_comskip_when_enabled():
    r = {x.id: x for x in _load()}[88]
    assert r.status == "completed" and r.comskip_status == "completed"
    assert r.is_ready(comskip_enabled=True) is True


def test_completed_without_comskip_holds_when_enabled():
    """Guards the race window: completed but comskip not yet terminal → wait.
    Synthesised (the snapshot caught no mid-comskip recording) by dropping the
    comskip block from a completed recording.
    """
    r = {x.id: x for x in _load()}[88]
    r.raw["custom_properties"].pop("comskip", None)
    assert r.is_ready(comskip_enabled=True) is False   # held (comskip enabled)
    assert r.is_ready(comskip_enabled=False) is True   # released (comskip off)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
