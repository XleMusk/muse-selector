"""Typed contracts for local observation tasks and their audit trail."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


WATCH_JOB_STATUSES = {"queued", "running", "complete", "failed", "skipped"}


@dataclass(frozen=True)
class WatchSpec:
    """Persisted user intent for a read-only observation task."""

    watch_id: str
    query: str
    fixture_path: str | None = None
    environment: str = "production"
    interval_seconds: int = 900
    enabled: bool = True
    revision: int = 0
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    last_run_id: str | None = None
    last_refreshed_at: str | None = None
    last_change_summary: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.watch_id or not self.query.strip():
            raise ValueError("watch_id and query are required")
        if self.environment not in {"production", "sandbox"}:
            raise ValueError("environment must be production or sandbox")
        if isinstance(self.interval_seconds, bool) or self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("revision must be non-negative")
        object.__setattr__(self, "thresholds", dict(self.thresholds or {}))
        if self.last_change_summary is not None:
            object.__setattr__(self, "last_change_summary", dict(self.last_change_summary))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WatchSpec":
        if not isinstance(value, Mapping):
            raise ValueError("watch spec must be an object")
        thresholds = value.get("thresholds")
        normalized_thresholds: Mapping[str, Any] = thresholds if isinstance(thresholds, Mapping) else {}
        summary = value.get("last_change_summary")
        normalized_summary: Mapping[str, Any] | None = summary if isinstance(summary, Mapping) else None
        return cls(
            watch_id=str(value.get("watch_id") or ""),
            query=str(value.get("query") or ""),
            fixture_path=str(value["fixture_path"]) if value.get("fixture_path") is not None else None,
            environment=str(value.get("environment") or "production"),
            interval_seconds=int(value.get("interval_seconds", 900)),
            enabled=bool(value.get("enabled", True)),
            revision=int(value.get("revision", 0)),
            thresholds=normalized_thresholds,
            last_run_id=str(value["last_run_id"]) if value.get("last_run_id") else None,
            last_refreshed_at=str(value["last_refreshed_at"]) if value.get("last_refreshed_at") else None,
            last_change_summary=normalized_summary,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RefreshJob:
    """One idempotent attempt to refresh a watch checkpoint."""

    job_id: str
    watch_id: str
    status: str
    attempt: int = 1
    run_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id or not self.watch_id:
            raise ValueError("job_id and watch_id are required")
        if self.status not in WATCH_JOB_STATUSES:
            raise ValueError(f"status must be one of {sorted(WATCH_JOB_STATUSES)}")
        if isinstance(self.attempt, bool) or self.attempt <= 0:
            raise ValueError("attempt must be positive")
        if self.status == "complete" and not self.run_id:
            raise ValueError("complete refresh jobs require run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WatchEvent:
    """Deduplicated, local-only event emitted by a watch refresh."""

    event_id: int | None
    watch_id: str
    run_id: str
    event_key: str
    event_type: str
    observed_at: str
    details: Mapping[str, Any] = field(default_factory=dict)
    consumed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.watch_id or not self.run_id or not self.event_key or not self.event_type:
            raise ValueError("watch event identity fields are required")
        object.__setattr__(self, "details", dict(self.details or {}))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WatchEvent":
        if not isinstance(value, Mapping):
            raise ValueError("watch event must be an object")
        raw_event_id = value.get("event_id")
        details = value.get("details")
        normalized_details: Mapping[str, Any] = details if isinstance(details, Mapping) else {}
        return cls(
            event_id=int(raw_event_id) if raw_event_id is not None else None,
            watch_id=str(value.get("watch_id") or ""),
            run_id=str(value.get("run_id") or ""),
            event_key=str(value.get("event_key") or ""),
            event_type=str(value.get("event_type") or ""),
            observed_at=str(value.get("observed_at") or "unknown"),
            details=normalized_details,
            consumed_at=str(value["consumed_at"]) if value.get("consumed_at") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditRecord:
    """Minimal non-sensitive record of an application action."""

    audit_id: str
    action: str
    status: str
    observed_at: str
    read_only: bool = True
    request_id: str | None = None
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.audit_id or not self.action or not self.status:
            raise ValueError("audit_id, action and status are required")
        if not self.read_only:
            raise ValueError("audit records must be read-only")
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["AuditRecord", "RefreshJob", "WatchEvent", "WatchSpec"]
