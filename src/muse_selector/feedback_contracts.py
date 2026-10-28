"""Local, replayable feedback records for result-card evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


FEEDBACK_LABELS = frozenset({"relevant", "irrelevant", "needs_review"})
FEEDBACK_SCHEMA_VERSION = "muse.selector.feedback.v1"


@dataclass(frozen=True)
class FeedbackRecord:
    """One local judgment about a listing in a persisted result run."""

    feedback_id: str
    run_id: str
    listing_id: str
    label: str
    recorded_at: str
    details: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FEEDBACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.feedback_id or not self.run_id or not self.listing_id:
            raise ValueError("feedback_id, run_id and listing_id are required")
        if self.label not in FEEDBACK_LABELS:
            raise ValueError(f"label must be one of {sorted(FEEDBACK_LABELS)}")
        if not self.recorded_at:
            raise ValueError("recorded_at is required")
        object.__setattr__(self, "details", dict(self.details or {}))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FeedbackRecord":
        if not isinstance(value, Mapping):
            raise ValueError("feedback record must be an object")
        details = value.get("details")
        normalized_details = details if isinstance(details, Mapping) else {}
        return cls(
            feedback_id=str(value.get("feedback_id") or ""),
            run_id=str(value.get("run_id") or ""),
            listing_id=str(value.get("listing_id") or ""),
            label=str(value.get("label") or ""),
            recorded_at=str(value.get("recorded_at") or ""),
            details=normalized_details,
            schema_version=str(value.get("schema_version") or FEEDBACK_SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_feedback_fixture(path: str) -> tuple[FeedbackRecord, ...]:
    """Load a JSON feedback fixture without executing any external action."""

    import json
    from pathlib import Path

    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    events = raw.get("events") if isinstance(raw, Mapping) else raw
    if not isinstance(events, list):
        raise ValueError("feedback fixture must contain an events list")
    return tuple(FeedbackRecord.from_mapping(item) for item in events)


def replay_feedback(
    records: tuple[FeedbackRecord, ...] | list[FeedbackRecord],
    recommendations_by_run: Mapping[str, list[str] | tuple[str, ...] | set[str]],
) -> dict[str, Any]:
    """Compare saved judgments with deterministic recommendation membership."""

    disagreements: list[dict[str, Any]] = []
    matched_count = 0
    for record in records:
        accepted = record.listing_id in set(recommendations_by_run.get(record.run_id, ()))
        expected = record.label == "relevant"
        if record.label == "needs_review" or accepted == expected:
            matched_count += 1
            continue
        disagreements.append({
            "feedback_id": record.feedback_id,
            "run_id": record.run_id,
            "listing_id": record.listing_id,
            "label": record.label,
            "recommended": accepted,
        })
    return {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "event_count": len(records),
        "matched_count": matched_count,
        "disagreement_count": len(disagreements),
        "disagreements": disagreements,
        "ok": not disagreements,
    }


__all__ = ["FEEDBACK_LABELS", "FEEDBACK_SCHEMA_VERSION", "FeedbackRecord", "load_feedback_fixture", "replay_feedback"]
