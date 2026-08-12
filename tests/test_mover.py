"""Mover tests — real filesystem moves in a temp dir (no network, no host paths)."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sortdvr.mover import move  # noqa: E402
from sortdvr.naming import Plan  # noqa: E402


def _plan(src: Path, dest_dir, rel: str, typ: str = "MOVIE") -> Plan:
    return Plan(type=typ, rel_path=rel, dest_dir=str(dest_dir),
                source_path=str(src), preserve_mtime=True)


def test_dry_run_moves_nothing(tmp_path):
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x" * 10)
    dest_dir = tmp_path / "out"
    r = move(_plan(src, dest_dir, "A/B.mkv"), go=False)
    assert r.status == "dry-run"
    assert src.exists()
    assert not (dest_dir / "A" / "B.mkv").exists()


def test_move_creates_dirs_and_preserves_mtime(tmp_path):
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x" * 100)
    old = time.time() - 100_000
    os.utime(src, (old, old))
    dest_dir = tmp_path / "out"
    r = move(_plan(src, dest_dir, "Show/Season 01/E.mkv"), go=True)
    assert r.status == "moved"
    dest = dest_dir / "Show" / "Season 01" / "E.mkv"
    assert dest.is_file() and not src.exists()
    assert abs(dest.stat().st_mtime - old) < 2  # mtime carried over


def test_never_overwrites_appends_counter(tmp_path):
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    (dest_dir / "A.mkv").write_bytes(b"original")
    src = tmp_path / "src.mkv"
    src.write_bytes(b"new")
    r = move(_plan(src, dest_dir, "A.mkv"), go=True)
    assert r.status == "moved"
    assert r.dest.endswith("A_2.mkv")
    assert (dest_dir / "A.mkv").read_bytes() == b"original"  # untouched


def test_missing_source(tmp_path):
    r = move(_plan(tmp_path / "nope.mkv", tmp_path / "out", "A.mkv"), go=True)
    assert r.status == "missing-source"


def test_no_dest_dir_skips(tmp_path):
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x")
    r = move(Plan("REVIEW", "A.mkv", "", str(src), True), go=True)
    assert r.status == "skipped-no-dest"


if __name__ == "__main__":
    import tempfile

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
