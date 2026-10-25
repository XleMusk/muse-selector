"""Offline-first end-to-end search pipeline for the Hong Kong MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .connectors.ebay import ConnectorUnavailable, EbayBrowseConnector
from .contracts import RESULT_SCHEMA_VERSION, Evidence, Listing
from .compatibility import build_compatibility_matrix
from .filtering import filter_listings
from .link_only import build_link_only_plan
from .query_parser import PolicyBlockedError, has_explicit_unbounded_budget, parse_query
from .result_card import build_card


# Compatibility aliases for callers that imported the former private helpers.
from .source_normalizer import extract_specs as _extract_specs  # noqa: F401
from .source_normalizer import normalize_source_row as _to_listing
from .url_policy import is_allowed_market_url

_ALLOWED_SOURCE_HOSTS = frozenset(
    {
        "ebay.com.hk",
        "www.ebay.com.hk",
        "ebay.com",
        "www.ebay.com",
    }
)


def _allowed_source_url(value: str) -> bool:
    """Backward-compatible name for the shared market URL policy."""

    return is_allowed_market_url(value, hosts=_ALLOWED_SOURCE_HOSTS)


def _query_matches_title(query: str, title: str) -> bool:
    """Apply a small deterministic relevance gate before ranking.

    The first fixture is intentionally heterogeneous. A budget match alone must
    not make a dock or enclosure look like a mini PC recommendation.
    """

    q = query.lower()
    t = title.lower()
    groups = (
        (("mini pc", "迷你主机", "迷你电脑"), ("mini pc", "mini computer", "迷你", "主机")),
        (("扩展坞", "dock", "enclosure", "usb4"), ("扩展坞", "dock", "enclosure", "usb4")),
        (("显卡", "gpu", "显存", "rtx", "gtx"), ("显卡", "gpu", "显存", "rtx", "gtx")),
        (("笔记本", "轻薄本", "laptop"), ("笔记本", "轻薄本", "laptop")),
    )
    for needles, matches in groups:
        if any(needle in q for needle in needles):
            return any(match in t for match in matches)
    return True


def _fit_explanation(spec: Any, listing: Listing) -> tuple[float, dict[str, Any]]:
    """Explain fit without changing the source's mandated result ordering."""

    preferred = dict(spec.preferred_specs or {})
    matched = 0
    for key, expected in preferred.items():
        actual = listing.specs.get(key)
        if actual is not None and str(actual).strip().lower() == str(expected).strip().lower():
            matched += 1
    preferred_ratio = matched / len(preferred) if preferred else 1.0
    availability = {"in_stock": 1.0, "preorder": 0.5}.get(listing.stock_status, 0.0)
    score = round((preferred_ratio * 0.4 + listing.evidence_coverage * 0.4 + availability * 0.2) * 100, 2)
    return score, {
        "preferred_specs": f"{matched}/{len(preferred)}" if preferred else "not specified",
        "evidence_coverage": listing.evidence_coverage,
        "availability": listing.stock_status,
        "policy": "source_order_preserved",
    }


def run_search(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
    environment: str | None = None,
) -> dict[str, Any]:
    """Run a fully offline search and return serializable result cards."""

    try:
        spec = parse_query(query)
    except PolicyBlockedError as exc:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "policy_blocked",
            "message": str(exc),
            "search_spec": None,
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    except ValueError as exc:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "invalid_query",
            "message": str(exc),
            "search_spec": None,
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "invalid_query",
            "message": "limit must be a positive integer",
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "invalid_query",
            "message": "offset must be a non-negative integer",
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    limit = min(limit, 200)
    if spec.budget_max is None and not has_explicit_unbounded_budget(query):
        budget_name = "max_total_cny" if spec.currency == "CNY" else "max_total_hkd"
        currency_hint = "CNY" if spec.currency == "CNY" else "HKD"
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "needs_clarification",
            "message": f"请补充配送地区和 {currency_hint} 预算上限；如无预算限制，请明确写“价格不限”。",
            "ask": ["location", budget_name],
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    if spec.region == "CN":
        # Domestic second-hand sources are registered by capability, but the
        # public official APIs currently expose no general arbitrary-listing
        # search connector.  Fail closed instead of routing a mainland query
        # into the HK eBay connector or using an unofficial scraper.
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "source_unavailable",
            "message": "中国大陆二手挂牌搜索连接器尚未获得官方授权；闲鱼当前为 link_only，转转当前仅提供官方估价/回收入口。",
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "domestic.secondhand.pending",
            "source_metadata": None,
            "link_only": build_link_only_plan(spec),
            "read_only": True,
        }
    try:
        connector_kwargs: dict[str, Any] = {"fixture_path": fixture_path}
        if environment is not None:
            connector_kwargs["environment"] = environment
        connector = EbayBrowseConnector(**connector_kwargs)
        connector_spec = spec.to_dict()
        # Keep the source request bounded while preserving recall after hard
        # filtering.  A small output limit must not shrink the single source
        # page below the connector's normal page size, otherwise early
        # rejected listings can hide later matches.  We still never follow
        # ``next`` or fetch more than one bounded page.
        default_source_limit = getattr(getattr(connector, "config", None), "default_limit", 20)
        if (
            isinstance(default_source_limit, bool)
            or not isinstance(default_source_limit, int)
            or default_source_limit < 1
        ):
            default_source_limit = 20
        connector_spec["limit"] = min(200, max(limit, default_source_limit))
        # Browse pagination is an explicit single-page control.  The
        # connector never follows ``next`` and never synthesizes later pages.
        connector_spec["offset"] = offset
        rows = connector.search(connector_spec)
    except (ConnectorUnavailable, ValueError) as exc:
        source_metadata = connector.source_metadata if "connector" in locals() else None
        if isinstance(source_metadata, dict) and "environment" not in source_metadata and "connector" in locals():
            source_metadata = {
                **source_metadata,
                "environment": getattr(getattr(connector, "config", None), "environment", "unknown"),
            }
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "source_unavailable",
            "message": str(exc),
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "ebay.browse.hk.v1",
            "source_metadata": source_metadata,
            "read_only": True,
        }
    source_metadata = connector.source_metadata
    listings: list[Listing] = []
    evidence_by_id: dict[str, list[Evidence]] = {}
    source_rank_by_id: dict[str, int] = {}
    dropped: list[dict[str, str]] = []
    for source_rank, row in enumerate(rows, 1):
        try:
            listing, evidence, reason = _to_listing(row, product_type=spec.product_type)
        except (TypeError, ValueError, OverflowError):
            # A live source can return a syntactically valid JSON object with
            # a value that violates our strict Listing contract (for example
            # NaN/Infinity prices or malformed monetary fields).  Isolate the
            # bad record so one source row cannot crash the whole read-only
            # search or bypass hard-constraint filtering.
            listing, evidence, reason = None, [], "malformed_source_record"
        if reason or listing is None:
            dropped.append({"listing_id": str(row.get("listing_id", "unknown")), "reason": reason or "invalid_source_record"})
            continue
        if not _query_matches_title(spec.query, listing.title):
            listing = Listing(
                listing_id=listing.listing_id,
                source_id=listing.source_id,
                title=listing.title,
                url=listing.url,
                region=listing.region,
                currency=listing.currency,
                price=listing.price,
                shipping_cost=listing.shipping_cost,
                tax=listing.tax,
                stock_status=listing.stock_status,
                condition=listing.condition,
                specs=listing.specs,
                category_attributes=listing.category_attributes,
                product_id=listing.product_id,
                evidence_ids=listing.evidence_ids,
                source_observed_at=listing.source_observed_at,
                risk_flags=tuple((*listing.risk_flags, "query_mismatch")),
                evidence_coverage=listing.evidence_coverage,
            )
        listings.append(listing)
        evidence_by_id[listing.listing_id] = evidence
        item_rank = row.get("source_rank")
        source_rank_by_id[listing.listing_id] = (
            item_rank
            if isinstance(item_rank, int) and not isinstance(item_rank, bool) and item_rank > 0
            else source_rank
        )
    accepted, decisions = filter_listings(spec, listings)
    # eBay's Buy API requirements prohibit partner-side re-sorting. Preserve
    # the source's best-match order and expose an explainable fit score instead.
    accepted = accepted[:limit]
    accepted_ids = {item.listing_id for item in accepted}
    decision_by_id = {item.listing_id: item for item in decisions}
    recommended_cards = []
    for index, item in enumerate(accepted, 1):
        fit_score, fit_breakdown = _fit_explanation(spec, item)
        recommended_cards.append(
            build_card(
                item,
                evidence_by_id[item.listing_id],
                source_rank=source_rank_by_id[item.listing_id],
                fit_score=fit_score,
                fit_breakdown=fit_breakdown,
            ).to_dict()
        )
    rejected = [
        {"listing_id": item.listing_id, "reasons": list(decision_by_id[item.listing_id].reasons)}
        for item in listings
        if item.listing_id not in accepted_ids
    ]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "ok": True,
        "status": "complete",
        "search_spec": spec.to_dict(),
        "recommended": recommended_cards,
        "compatibility_matrix": build_compatibility_matrix({"search_spec": spec.to_dict(), "recommended": recommended_cards}),
        "ranking_policy": "source_order_preserved",
        "rejected": rejected,
        "dropped": dropped,
        "source": "ebay.browse.hk.v1",
        "source_metadata": source_metadata,
        "read_only": True,
    }

