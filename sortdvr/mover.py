"""Move a planned recording to its destination.

MOVE, not copy. Preserve mtime (SpoilerFree's fallback date anchor for sport).
Same-volume rename when possible (atomic, keeps mtime); cross-volume falls back
to copy2 + verify + utime + unlink. Never overwrite an existing destination:
TV/Movie get a `_N` suffix; sport keep-both is already differentiated by the
broadcaster tag in the name, so a genuine collision there means a true duplicate.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sortdvr.naming import Plan


@dataclass
class MoveResult:
    status: str  # dry-run | moved | skipped-no-dest | missing-source | error
    src: str
    dest: str
    detail: str = ""


def _unique(dest: Path) -> Path:
    """Return dest, or dest with a `_N` suffix if it already exists."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    n = 2
    while (cand := dest.with_name(f"{stem}_{n}{suffix}")).exists():
        n += 1
    return cand


def _move_preserving_mtime(src: Path, dest: Path) -> None:
    st = src.stat()
    try:
        os.rename(src, dest)  # same volume: atomic, mtime preserved
        return
    except OSError:
        pass  # cross-volume; fall through to copy
    shutil.copy2(src, dest)  # copy2 preserves mtime
    if dest.stat().st_size != st.st_size:
        dest.unlink(missing_ok=True)
        raise OSError(f"copy size mismatch: {src} -> {dest}")
    os.utime(dest, (st.st_atime, st.st_mtime))
    src.unlink()


def move(plan: Plan, *, go: bool) -> MoveResult:
    """Execute (or, when go=False, describe) the move for one plan."""
    src = Path(plan.source_path)

    if not go:
        return MoveResult("dry-run", str(src), plan.dest_path)

    if not plan.dest_dir:
        return MoveResult("skipped-no-dest", str(src), plan.rel_path,
                          f"no destination dir configured for {plan.type}")
    if not src.is_file():
        return MoveResult("missing-source", str(src), plan.dest_path,
                          "source file not found (run on the host that holds it)")

    dest = _unique(Path(plan.dest_dir) / plan.rel_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _move_preserving_mtime(src, dest)
    except OSError as e:
        return MoveResult("error", str(src), str(dest), str(e))
    return MoveResult("moved", str(src), str(dest))
