"""Audit event types and hook interfaces for lib_safety.

Moves, trash deletes, and refused writes can emit structured
:class:`AuditEvent` objects to any object implementing the
:class:`AuditHook` protocol. The default hook is a no-op;
:class:`JsonlAuditHook` provides a small append-only JSONL sink for
callers who want a durable log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class AuditEvent:
    """A structured, JSON-serializable record of one safety-relevant operation."""

    operation: str
    source: str
    destination: str | None = None
    companions: tuple[str, ...] = ()
    ok: bool = True
    reason: str | None = None
    timestamp: str = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, object]:
        """Return the event as a JSON-serializable dictionary."""
        return {
            "operation": self.operation,
            "source": self.source,
            "destination": self.destination,
            "companions": list(self.companions),
            "ok": self.ok,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@runtime_checkable
class AuditHook(Protocol):
    """Interface for audit sinks: a single ``record`` method."""

    def record(self, event: AuditEvent) -> None: ...


class NullAuditHook:
    """Default no-op audit hook."""

    def record(self, event: AuditEvent) -> None:
        return None


NULL_HOOK = NullAuditHook()


class JsonlAuditHook:
    """Append-only JSONL audit sink at a caller-supplied log path.

    Each :meth:`record` call appends one JSON line. Parent directories are
    created on first use; existing log contents are never read or rewritten.
    """

    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)

    def record(self, event: AuditEvent) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.as_dict(), sort_keys=True) + "\n")
