"""Deterministic, read-only execution graph for one selector task.

The graph wraps the existing pipeline instead of duplicating filtering logic.
Its checkpoint contains the completed result payload, so a replay can return a
previous result without invoking a connector again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .application import search as run_search
from .contracts import RESULT_SCHEMA_VERSION

STATE_GRAPH_SCHEMA_VERSION = "muse.selector.execution.v1"
STAGE_CHECKPOINT_SCHEMA_VERSION = "muse.selector.stage-checkpoint.v1"
STAGES = ("parse", "fanout", "normalize", "filter", "rank", "verify", "present")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def execution_id_for_request(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
    environment: str | None = None,
) -> str:
    request = {
        "query": query,
        "fixture_path": str(fixture_path) if fixture_path is not None else None,
        "limit": limit,
        "offset": offset,
        "environment": environment,
    }
    digest = hashlib.sha256(_canonical(request).encode("utf-8")).hexdigest()[:32]
    return f"exec_{digest}"


def save_checkpoint(path: str | Path, checkpoint: Mapping[str, Any]) -> None:
    """Atomically persist one read-only execution checkpoint as JSON."""

    if not isinstance(checkpoint, Mapping):
        raise ValueError("checkpoint must be an object")
    target = Path(path)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(dict(checkpoint), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(target)


def load_checkpoint(path: str | Path) -> dict[str, Any]:
    """Load one persisted checkpoint without contacting a source."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"checkpoint must be readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be an object")
    return value


def _failed_stage(payload: Mapping[str, Any]) -> str | None:
    status = payload.get("status")
    if status in {"policy_blocked", "invalid_query", "needs_clarification"}:
        return "parse"
    if status == "source_unavailable":
        return "fanout"
    return None


def _stage_projection(name: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Select the result fields owned by one observable execution stage."""

    projections: dict[str, tuple[str, ...]] = {
        "parse": ("status", "search_spec", "ask", "policy"),
        "fanout": ("status", "source", "source_metadata", "source_capability"),
        "normalize": ("status", "source", "dropped"),
        "filter": ("status", "rejected"),
        "rank": ("status", "recommended"),
        "verify": ("status", "compatibility_matrix", "recommended"),
        "present": tuple(payload.keys()),
    }
    return {field: payload.get(field) for field in projections[name] if field in payload}


def _stage_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    failed = _failed_stage(payload)
    records: list[dict[str, Any]] = []
    failed_seen = False
    completed_at = _timestamp()
    for name in STAGES:
        if failed_seen:
            status = "skipped"
        elif name == failed:
            status = "failed"
            failed_seen = True
        else:
            status = "complete"
        stage_data_fingerprint = hashlib.sha256(
            _canonical(_stage_projection(name, payload)).encode("utf-8")
        ).hexdigest()
        records.append({
            "name": name,
            "status": status,
            "read_only": True,
            "completed_at": None if status == "skipped" else completed_at,
            "data_fingerprint": stage_data_fingerprint,
        })
    return records


def _stage_fingerprint(stages: Sequence[Mapping[str, Any]]) -> str:
    stable_records = [
        {
            "name": item.get("name"),
            "status": item.get("status"),
            "read_only": item.get("read_only"),
            "data_fingerprint": item.get("data_fingerprint"),
        }
        for item in stages
    ]
    return hashlib.sha256(_canonical(stable_records).encode("utf-8")).hexdigest()


def _validate_checkpoint_stages(
    stages: Any,
    stored_fingerprint: Any,
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(stages, list) or len(stages) != len(STAGES):
        raise ValueError("checkpoint stages are incomplete")
    expected = _stage_records(payload)
    for index, item in enumerate(stages):
        if not isinstance(item, Mapping):
            raise ValueError("checkpoint stages are invalid")
        expected_item = expected[index]
        for key in ("name", "status", "read_only", "data_fingerprint"):
            if item.get(key) != expected_item[key]:
                raise ValueError("checkpoint stages do not match payload")
        completed_at = item.get("completed_at")
        if expected_item["status"] == "skipped":
            if completed_at is not None:
                raise ValueError("skipped checkpoint stages cannot have a completion timestamp")
        elif not isinstance(completed_at, str) or not completed_at:
            raise ValueError("completed checkpoint stages require a timestamp")
    if stored_fingerprint != _stage_fingerprint([dict(item) for item in stages]):
        raise ValueError("checkpoint stage fingerprint does not match stages")
    return [dict(item) for item in stages]


def run_search_graph(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
    environment: str | None = None,
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run or replay one deterministic, read-only task graph.

    A checkpoint must belong to the same request and contain a prior payload.
    Replaying it does not call ``run_search`` or any connector.
    """

    execution_id = execution_id_for_request(
        query,
        fixture_path,
        limit=limit,
        offset=offset,
        environment=environment,
    )
    resumed = checkpoint is not None
    stage_snapshots: dict[str, dict[str, Any]] = {}

    def capture_stage(name: str, snapshot: Mapping[str, Any]) -> None:
        stage_snapshots[name] = dict(snapshot)

    if checkpoint is not None:
        if not isinstance(checkpoint, Mapping):
            raise ValueError("checkpoint must be an object")
        if checkpoint.get("execution_id") != execution_id:
            raise ValueError("checkpoint belongs to a different execution request")
        if checkpoint.get("completed_stage") in {"fanout", "normalize", "filter", "rank", "verify"}:
            snapshots = checkpoint.get("stage_snapshots")
            completed_stage = str(checkpoint.get("completed_stage"))
            snapshot = snapshots.get(completed_stage) if isinstance(snapshots, Mapping) else None
            if not isinstance(snapshot, Mapping):
                raise ValueError(f"{completed_stage} resume checkpoint is missing stage snapshot")
            resume_state = {"completed_stage": completed_stage, **dict(snapshot)}
            payload = run_search(
                query,
                fixture_path,
                limit=limit,
                offset=offset,
                environment=environment,
                resume_state=resume_state,
                stage_callback=capture_stage,
            )
        elif checkpoint.get("completed_stage") == "present":
            snapshots = checkpoint.get("stage_snapshots")
            present = snapshots.get("present") if isinstance(snapshots, Mapping) else None
            present_payload = present.get("payload") if isinstance(present, Mapping) else None
            if isinstance(present_payload, Mapping):
                payload = dict(present_payload)
            else:
                payload_value = checkpoint.get("payload")
                if not isinstance(payload_value, Mapping):
                    raise ValueError("checkpoint payload is required")
                payload = dict(payload_value)
        else:
            payload_value = checkpoint.get("payload")
            if not isinstance(payload_value, Mapping):
                raise ValueError("checkpoint payload is required")
            payload = dict(payload_value)
    else:
        payload = run_search(
            query,
            fixture_path,
            limit=limit,
            offset=offset,
            environment=environment,
            stage_callback=capture_stage,
        )

    if not stage_snapshots and isinstance(checkpoint, Mapping):
        stored_snapshots = checkpoint.get("stage_snapshots")
        if isinstance(stored_snapshots, Mapping):
            stage_snapshots = {
                str(name): dict(snapshot)
                for name, snapshot in stored_snapshots.items()
                if isinstance(snapshot, Mapping)
            }
    stage_snapshots.setdefault(
        "present",
        {
            "completed_stage": "present",
            "payload": dict(payload),
        },
    )

    payload_fingerprint = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if checkpoint is not None:
        stored_payload_fingerprint = checkpoint.get("payload_fingerprint")
        if stored_payload_fingerprint is not None and stored_payload_fingerprint != payload_fingerprint:
            raise ValueError("checkpoint payload fingerprint does not match payload")
        if "stages" in checkpoint or "stage_fingerprint" in checkpoint:
            stages = _validate_checkpoint_stages(
                checkpoint.get("stages"),
                checkpoint.get("stage_fingerprint"),
                payload,
            )
        else:
            # Checkpoints written before stage metadata was introduced remain
            # replayable; the next returned checkpoint upgrades them.
            stages = _stage_records(payload)
    else:
        stages = _stage_records(payload)
    stage_fingerprint = _stage_fingerprint(stages)
    result = dict(payload)
    result["execution"] = {
        "schema_version": STATE_GRAPH_SCHEMA_VERSION,
        "execution_id": execution_id,
        "resumed_from_checkpoint": resumed,
        "current_stage": "present" if payload.get("ok") else (_failed_stage(payload) or "present"),
        "stages": stages,
        "checkpoint": {
            "schema_version": STAGE_CHECKPOINT_SCHEMA_VERSION,
            "execution_id": execution_id,
            "completed_stage": "present" if payload.get("ok") else (_failed_stage(payload) or "present"),
            "payload_fingerprint": payload_fingerprint,
            "stage_snapshots": stage_snapshots,
            "stages": stages,
            "stage_fingerprint": stage_fingerprint,
            "payload": payload,
        },
        "read_only": True,
    }
    result.setdefault("schema_version", RESULT_SCHEMA_VERSION)
    return result


def run_state_graph(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    environment: str | None = None,
    limit: int = 10,
    offset: int = 0,
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the compact W6 execution envelope used by callers."""

    result = run_search_graph(
        query,
        fixture_path,
        limit=limit,
        offset=offset,
        environment=environment,
        checkpoint=checkpoint,
    )
    execution = result["execution"]
    payload = {key: value for key, value in result.items() if key != "execution"}
    return {
        "schema_version": STATE_GRAPH_SCHEMA_VERSION,
        "run_id": execution["execution_id"],
        "status": payload.get("status", "unknown"),
        "stages": execution["stages"],
        "payload": payload,
        "checkpoint": execution["checkpoint"],
        "resumed_from_checkpoint": execution["resumed_from_checkpoint"],
        "read_only": True,
    }


__all__ = [
    "STATE_GRAPH_SCHEMA_VERSION",
    "STAGE_CHECKPOINT_SCHEMA_VERSION",
    "STAGES",
    "execution_id_for_request",
    "load_checkpoint",
    "run_state_graph",
    "run_search_graph",
    "save_checkpoint",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Muse Selector execution graph")
    parser.add_argument("--query", required=True, help="explicit hardware query")
    parser.add_argument("--fixture", default=None, help="offline source fixture")
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--checkpoint", default=None, help="JSON checkpoint file to replay")
    parser.add_argument("--checkpoint-out", default=None, help="write the completed JSON checkpoint to this path")
    args = parser.parse_args()
    checkpoint = None
    if args.checkpoint:
        try:
            checkpoint = load_checkpoint(args.checkpoint)
        except ValueError as exc:
            parser.error(str(exc))
    result = run_state_graph(
        args.query,
        Path(args.fixture) if args.fixture else None,
        environment=args.environment,
        limit=args.limit,
        offset=args.offset,
        checkpoint=checkpoint,
    )
    if args.checkpoint_out:
        try:
            save_checkpoint(args.checkpoint_out, result["checkpoint"])
        except (OSError, TypeError, ValueError) as exc:
            parser.error(f"checkpoint output could not be written: {exc}")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("payload", {}).get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
