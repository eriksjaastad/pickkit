"""Audit event types and hook interfaces for lib_safety.

This module is the single source of truth for audit behaviour: what events
exist, how they are recorded, and where they go. Moves, trash deletes, and
refused writes can emit structured :class:`AuditEvent` objects to any
object implementing the :class:`AuditHook` protocol. The default hook is a
no-op; :class:`JsonlAuditHook` provides a small append-only JSONL sink for
callers who want a durable log. The precursor FileTracker was a heavier
system — pickkit uses only this lightweight hook API.

Principles
----------
Structured events
    Every safety-relevant operation (move, trash, refuse_write) is
    captured as one :class:`AuditEvent` with operation, source,
    destination, companions, ok, reason, and timestamp fields.
Default is a no-op
    Nothing is logged unless the caller supplies a hook; ``NULL_HOOK`` is
    a shared :class:`NullAuditHook` instance used by default everywhere.
Append-only JSONL
    :class:`JsonlAuditHook` appends one JSON line per event to a
    caller-supplied log path; existing log contents are never read or
    rewritten.
UTC timestamps
    Event timestamps come from :func:`utc_now`, an ISO-8601 UTC ``Z``
    time.

Public API
----------
``utc_now()``
    Return an ISO-8601 UTC timestamp with a ``Z`` suffix.
``AuditEvent``
    Frozen, JSON-serializable dataclass describing one safety operation.
``AuditHook``
    Protocol for audit sinks: a single ``record`` method.
``NullAuditHook``
    Default no-op audit hook.
``NULL_HOOK``
    Shared :class:`NullAuditHook` instance used by default everywhere.
``JsonlAuditHook``
    Append-only JSONL audit sink at a caller-supplied log path.
``FanoutHook(*hooks)``
    Audit hook that records each event on every wrapped hook, in order.
``optional_jsonl_hook(path)``
    Return ``JsonlAuditHook(path)``, or ``None`` when *path* is empty or
    ``None`` (the CLIs' ``--audit PATH`` flag).

Examples
--------
Record an event on a JSONL hook::

    from lib_safety import AuditEvent, JsonlAuditHook

    hook = JsonlAuditHook("sandbox/.audit.jsonl")
    hook.record(AuditEvent(operation="move", source="a.png", destination="b.png"))

Out of scope
------------
DB-backed trackers, rewriting past log lines, and auto-discovering log
paths are **not** this module's job. The log path is always
caller-supplied, and the sink only ever appends.
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


class FanoutHook:
    """Record one event to every wrapped hook (e.g. audit JSONL + caller hook)."""

    def __init__(self, *hooks: AuditHook) -> None:
        self._hooks = hooks

    def record(self, event: AuditEvent) -> None:
        for hook in self._hooks:
            hook.record(event)


def optional_jsonl_hook(path: str | None) -> AuditHook | None:
    """Return a :class:`JsonlAuditHook` on *path*, or ``None`` without a path."""
    return JsonlAuditHook(path) if path else None
