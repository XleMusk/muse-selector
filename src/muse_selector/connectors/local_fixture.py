"""Explicit local-only connector for mainland CNY regression data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..ports import SourceUnavailable


class LocalFixtureConnector:
    """Serve canonical fixture rows without contacting a marketplace."""

    source_id = "fixture.local.v1"

    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)
        self._source_metadata: dict[str, Any] = {
            "fixture_path": str(self.fixture_path),
            "source": self.source_id,
            "read_only": True,
        }

    @property
    def source_metadata(self) -> Mapping[str, Any]:
        return dict(self._source_metadata)

    def search(self, search_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
        if not self.fixture_path.exists():
            raise SourceUnavailable(f"fixture not found: {self.fixture_path}")
        try:
            raw = json.loads(self.fixture_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceUnavailable(f"invalid local fixture: {exc}") from exc
        rows: Any = raw.get("listings") if isinstance(raw, Mapping) else raw
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise SourceUnavailable("invalid local fixture: expected a listings array")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item.get("source_id") != self.source_id:
                raise SourceUnavailable("invalid local fixture: source_id must be fixture.local.v1")
            normalized.append(item)
        limit = search_spec.get("limit", len(normalized)) if isinstance(search_spec, Mapping) else len(normalized)
        offset = search_spec.get("offset", 0) if isinstance(search_spec, Mapping) else 0
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("fixture limit must be a positive integer")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("fixture offset must be a non-negative integer")
        self._source_metadata.update({"total": len(normalized), "limit": limit, "offset": offset})
        return normalized[offset: offset + limit]


__all__ = ["LocalFixtureConnector"]
