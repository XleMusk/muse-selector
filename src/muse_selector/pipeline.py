"""Offline-first search pipeline for domestic second-hand market discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .compatibility import build_compatibility_matrix
from .contracts import RESULT_SCHEMA_VERSION, Evidence, Listing
from .filtering import FilterDecision, filter_listings
from .link_only import build_link_only_plan
from .ports import SourceConnector, SourceUnavailable, SourceConnectorFactory
from .source_factory import build_source_connector
from .query_parser import PolicyBlockedError, has_explicit_unbounded_budget, parse_query
from .ranking import SOURCE_ORDER_PROFILE
from .result_card import build_card
from .source_capabilities import source_capability_registry

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

def _source_capability(source_id: str, connector: Any = None) -> dict[str, Any] | None:
    capability = source_capability_registry().get(source_id)
    if capability is None:
        return None
    result = capability.to_dict()
    fixture_path = getattr(connector, "fixture_path", None)
    if isinstance(fixture_path, (str, Path)) and str(fixture_path):
        result.update({"access_mode": "local_fixture", "status": "ready"})
    elif source_id == "ebay.browse.hk.v1" and connector is not None:
        kill_switch = getattr(connector, "_kill_switch_active", None)
        kill_switch_active = kill_switch() if callable(kill_switch) else False
        if kill_switch_active is True:
            result["status"] = "disabled"
        elif getattr(connector, "live_enabled", False) is True:
            result["status"] = "ready"
        else:
            result["status"] = "credential_unavailable"
        credential_state = getattr(connector, "credential_state", "missing")
        result["credential_state"] = credential_state if isinstance(credential_state, str) else "unknown"
        environment = getattr(getattr(connector, "config", None), "environment", "unknown")
        result["environment"] = environment if isinstance(environment, str) else "unknown"
    return result


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
    connector: SourceConnector | None = None,
    connector_factory: SourceConnectorFactory | None = None,
    resume_state: Mapping[str, Any] | None = None,
    stage_callback: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run a fully offline search and return serializable result cards."""

    try:
        spec = parse_query(query)
    except PolicyBlockedError as exc:
        policy: dict[str, Any] = {
            "domain": getattr(exc, "domain", "policy"),
            "source_id": getattr(exc, "source_id", "policy.guard"),
            "reason_code": getattr(exc, "reason_code", "blocked_action"),
            "status": "blocked",
            "read_only": True,
            "link_only": False,
            "allowed_actions": ["read_policy"],
            "blocked_actions": ["login", "purchase", "transfer", "boosting", "payment"],
        }
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "policy_blocked",
            "message": str(exc),
            "search_spec": None,
            "recommended": [],
            "rejected": [],
            "dropped": [],
            # Keep the v1 envelope source stable; the domain-specific source
            # identity is carried in ``policy.source_id`` for new clients.
            "source": "policy.guard",
            "domain": policy["domain"],
            "policy": policy,
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
    if spec.product_type == "game_account":
        policy = {
            "domain": "game_accounts",
            "source_id": "game_accounts.policy.v1",
            "reason_code": "manual_read_only_discovery",
            "status": "link_only",
            "read_only": True,
            "link_only": True,
            "allowed_actions": ["read_public_information"],
            "blocked_actions": ["login", "purchase", "transfer", "boosting", "payment"],
        }
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "ok": False,
            "status": "source_unavailable",
            "message": "游戏账号仅支持只读人工入口；系统不抓取挂牌，不处理登录、购买、转移、代打或支付。",
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": policy["source_id"],
            "source_capability": _source_capability(policy["source_id"]),
            "link_only": build_link_only_plan(spec),
            "domain": policy["domain"],
            "policy": policy,
            "read_only": True,
        }
    resume_source_id = str(resume_state.get("source_id")) if isinstance(resume_state, Mapping) and resume_state.get("source_id") else None
    local_fixture = (
        connector is not None and getattr(connector, "source_id", None) == "fixture.local.v1"
    ) or resume_source_id == "fixture.local.v1"
    if spec.region == "CN" and not local_fixture:
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
    source_id = resume_source_id or "ebay.browse.hk.v1"
    resume_mapping = resume_state if isinstance(resume_state, Mapping) else None
    source_metadata: dict[str, Any] = {}
    resumed_source_capability: dict[str, Any] | None = None
    try:
        resumed_stage = str(resume_mapping.get("completed_stage")) if resume_mapping is not None else None
        resumed_fanout = resumed_stage == "fanout"
        resumed_normalize = resumed_stage == "normalize"
        resumed_filter = resumed_stage == "filter"
        resumed_rank = resumed_stage == "rank"
        if resumed_fanout or resumed_normalize or resumed_filter or resumed_rank:
            assert resume_mapping is not None
            if resumed_fanout:
                raw_rows = resume_mapping.get("rows")
                if not isinstance(raw_rows, list) or any(not isinstance(row, Mapping) for row in raw_rows):
                    raise ValueError("resume checkpoint fanout rows are invalid")
                rows = [dict(row) for row in raw_rows]
            raw_metadata = resume_mapping.get("source_metadata")
            source_metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
            raw_capability = resume_mapping.get("source_capability")
            if isinstance(raw_capability, Mapping):
                resumed_source_capability = dict(raw_capability)
        else:
            if connector is None:
                factory = connector_factory or build_source_connector
                connector = factory(fixture_path=fixture_path, environment=environment)
            assert connector is not None
            candidate_source_id = getattr(connector, "source_id", source_id)
            if isinstance(candidate_source_id, str) and candidate_source_id:
                source_id = candidate_source_id
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
            # connector never follows ``next`` or never synthesizes later pages.
            connector_spec["offset"] = offset
            rows = connector.search(connector_spec)
    except (SourceUnavailable, ValueError) as exc:
        source_metadata = dict(connector.source_metadata) if connector is not None else {}
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
            "source": source_id,
            "source_metadata": source_metadata,
            "source_capability": _source_capability(source_id, connector),
            "read_only": True,
        }
    if not (resume_mapping is not None and resume_mapping.get("completed_stage") in {"fanout", "normalize", "filter", "rank"}):
        assert connector is not None
        source_metadata = dict(connector.source_metadata)
        if stage_callback is not None and not (resumed_normalize or resumed_filter or resumed_rank):
            stage_callback(
                "fanout",
                {
                    "source_id": source_id,
                    "source_metadata": dict(source_metadata),
                    "source_capability": _source_capability(source_id, connector),
                    "rows": [dict(row) for row in rows],
                },
            )
    listings: list[Listing] = []
    evidence_by_id: dict[str, list[Evidence]] = {}
    source_rank_by_id: dict[str, int] = {}
    dropped: list[dict[str, str]] = []
    if resumed_normalize or resumed_filter or resumed_rank:
        assert resume_mapping is not None
        raw_listings = resume_mapping.get("listings")
        raw_evidence = resume_mapping.get("evidence_by_id")
        raw_ranks = resume_mapping.get("source_rank_by_id")
        raw_dropped = resume_mapping.get("dropped")
        if not isinstance(raw_listings, list) or any(not isinstance(item, Mapping) for item in raw_listings):
            raise ValueError("resume checkpoint normalize listings are invalid")
        if not isinstance(raw_evidence, Mapping) or not isinstance(raw_ranks, Mapping) or not isinstance(raw_dropped, list):
            raise ValueError("resume checkpoint normalize snapshot is invalid")
        listings = [Listing.from_dict(item) for item in raw_listings]
        evidence_by_id = {
            str(listing_id): [Evidence(**dict(item)) for item in items]
            for listing_id, items in raw_evidence.items()
            if isinstance(items, list) and all(isinstance(item, Mapping) for item in items)
        }
        source_rank_by_id = {str(key): int(value) for key, value in raw_ranks.items()}
        dropped = [dict(item) for item in raw_dropped if isinstance(item, Mapping)]
    for source_rank, row in enumerate(rows if not (resumed_normalize or resumed_filter or resumed_rank) else [], 1):
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
    if stage_callback is not None and not (resumed_normalize or resumed_filter):
        stage_callback(
            "normalize",
            {
                "completed_stage": "normalize",
                "source_id": source_id,
                "source_metadata": dict(source_metadata),
                "source_capability": resumed_source_capability or _source_capability(source_id, connector),
                "listings": [listing.to_dict() for listing in listings],
                "evidence_by_id": {
                    listing_id: [item.to_dict() for item in evidence]
                    for listing_id, evidence in evidence_by_id.items()
                },
                "source_rank_by_id": dict(source_rank_by_id),
                "dropped": list(dropped),
            },
        )
    if resumed_rank:
        assert resume_mapping is not None
        raw_cards = resume_mapping.get("recommended_cards")
        raw_rejected = resume_mapping.get("rejected")
        if not isinstance(raw_cards, list) or not all(isinstance(item, Mapping) for item in raw_cards):
            raise ValueError("resume checkpoint rank cards are invalid")
        if not isinstance(raw_rejected, list) or not all(isinstance(item, Mapping) for item in raw_rejected):
            raise ValueError("resume checkpoint rank rejected records are invalid")
        recommended_cards = [dict(item) for item in raw_cards]
        rejected = [dict(item) for item in raw_rejected]
        decisions = []
        accepted = []
    elif resumed_filter:
        assert resume_mapping is not None
        raw_decisions = resume_mapping.get("decisions")
        accepted_ids_raw = resume_mapping.get("accepted_ids")
        if not isinstance(raw_decisions, list) or not isinstance(accepted_ids_raw, list):
            raise ValueError("resume checkpoint filter snapshot is invalid")
        decisions = [
            FilterDecision(
                str(item.get("listing_id")),
                bool(item.get("accepted")),
                tuple(str(reason) for reason in item.get("reasons", ())),
            )
            for item in raw_decisions
            if isinstance(item, Mapping)
        ]
        accepted_ids_resume = {str(item) for item in accepted_ids_raw}
        accepted = [listing for listing in listings if listing.listing_id in accepted_ids_resume]
    else:
        accepted, decisions = filter_listings(spec, listings)
        if stage_callback is not None:
            stage_callback(
                "filter",
                {
                    "completed_stage": "filter",
                    "source_id": source_id,
                    "source_metadata": dict(source_metadata),
                    "source_capability": resumed_source_capability or _source_capability(source_id, connector),
                    "listings": [listing.to_dict() for listing in listings],
                    "evidence_by_id": {
                        listing_id: [item.to_dict() for item in evidence]
                        for listing_id, evidence in evidence_by_id.items()
                    },
                    "source_rank_by_id": dict(source_rank_by_id),
                    "dropped": list(dropped),
                    "accepted_ids": [item.listing_id for item in accepted],
                    "decisions": [
                        {
                            "listing_id": item.listing_id,
                            "accepted": item.accepted,
                            "reasons": list(item.reasons),
                        }
                        for item in decisions
                    ],
                },
            )
    # eBay's Buy API requirements prohibit partner-side re-sorting. Preserve
    # the source's best-match order and expose an explainable fit score instead.
    if not resumed_rank:
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
        if stage_callback is not None:
            stage_callback(
                "rank",
                {
                    "completed_stage": "rank",
                    "source_id": source_id,
                    "source_metadata": dict(source_metadata),
                    "source_capability": resumed_source_capability or _source_capability(source_id, connector),
                    "listings": [listing.to_dict() for listing in listings],
                    "evidence_by_id": {
                        listing_id: [item.to_dict() for item in evidence]
                        for listing_id, evidence in evidence_by_id.items()
                    },
                    "source_rank_by_id": dict(source_rank_by_id),
                    "dropped": list(dropped),
                    "recommended_cards": list(recommended_cards),
                    "rejected": list(rejected),
                },
            )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "ok": True,
        "status": "complete",
        "search_spec": spec.to_dict(),
        "recommended": recommended_cards,
        "compatibility_matrix": build_compatibility_matrix({"search_spec": spec.to_dict(), "recommended": recommended_cards}),
        "ranking_policy": "source_order_preserved",
        "rank_profile_id": SOURCE_ORDER_PROFILE.profile_id,
        "rejected": rejected,
        "dropped": dropped,
        "source": source_id,
        "source_metadata": source_metadata,
        "source_capability": resumed_source_capability or _source_capability(source_id, connector),
        "read_only": True,
    }

