"""Deterministic ranking profiles used after hard filtering."""

from __future__ import annotations

from .contracts import RankProfile


SOURCE_ORDER_PROFILE = RankProfile(
    profile_id="source_order_preserved.v1",
    weights={"source_order": 1.0},
    source_order_preserved=True,
)


__all__ = ["SOURCE_ORDER_PROFILE"]
