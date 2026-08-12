"""Parsed view over a Dispatcharr recording payload.

Shape verified against live data (192.168.0.148, 2026-08-12): state lives in
``custom_properties`` (no status column); scheduled/future recordings have no
``status``/``file_path`` yet; ``comskip.status`` is set only after the recording
completes (``status=="completed"`` is set *before* Comskip runs).
"""

from __future__ import annotations

from dataclasses import dataclass

_TERMINAL_COMSKIP = {"completed", "skipped", "error"}
# Final states with a kept file: ran to the end, or the user stopped it early
# but chose to keep the partial recording.
_FINAL_STATUSES = {"completed", "stopped"}


@dataclass
class Recording:
    id: int
    channel_id: int | None
    raw: dict

    @property
    def cp(self) -> dict:
        return self.raw.get("custom_properties") or {}

    @property
    def program(self) -> dict:
        return self.cp.get("program") or {}

    @property
    def status(self) -> str:
        return self.cp.get("status") or ""

    @property
    def comskip_status(self) -> str:
        cs = self.cp.get("comskip")
        return cs.get("status", "") if isinstance(cs, dict) else ""

    @property
    def file_path(self) -> str:
        return self.cp.get("file_path") or ""

    @property
    def file_name(self) -> str:
        return self.cp.get("file_name") or ""

    @property
    def title(self) -> str:
        return self.program.get("title") or ""

    @property
    def sub_title(self) -> str:
        return self.program.get("sub_title") or ""

    @property
    def description(self) -> str:
        return self.program.get("description") or ""

    def _int_field(self, key: str) -> int | None:
        val = self.cp.get(key)
        if val is None:
            val = self.program.get(key)
        return val if isinstance(val, int) else None

    @property
    def season(self) -> int | None:
        return self._int_field("season")

    @property
    def episode(self) -> int | None:
        return self._int_field("episode")

    @property
    def start_time(self) -> str:
        return self.raw.get("start_time") or ""

    @property
    def bytes_written(self) -> int | None:
        v = self.cp.get("bytes_written")
        return v if isinstance(v, int) else None

    def has_file(self) -> bool:
        """True once the recording exists on disk with a lifecycle status."""
        return bool(self.file_path) and bool(self.status)

    def is_empty(self) -> bool:
        """A 0-byte recording (e.g. stopped before anything was written)."""
        return self.bytes_written == 0

    def is_ready(self, comskip_enabled: bool) -> bool:
        """Safe-to-process gate: a final state (completed OR user-stopped-and-kept)
        with real bytes AND (Comskip done, if enabled)."""
        if self.status not in _FINAL_STATUSES:
            return False
        if self.is_empty():  # nothing to route
            return False
        if comskip_enabled:
            return self.comskip_status in _TERMINAL_COMSKIP
        return True

    @classmethod
    def from_api(cls, d: dict) -> "Recording":
        return cls(id=d.get("id"), channel_id=d.get("channel"), raw=d)
