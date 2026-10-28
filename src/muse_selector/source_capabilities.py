"""Typed source capability registry used by the local API and CLI."""

from __future__ import annotations

from .contracts import SourceCapability

_CAPABILITIES = (
    SourceCapability(
        source_id="ebay.browse.hk.v1",
        display_name="eBay Browse API（香港站）",
        category="computers_hardware",
        access_mode="official_api",
        read_only=True,
        listing_search=True,
        status="credential_pending",
        allowed_regions=("HK",),
        allowed_fields=("title", "url", "price", "condition", "stock", "shipping", "seller", "localizedAspects"),
        authorization_evidence_url="https://developer.ebay.com/api-docs/buy/browse/overview.html",
        retention_days=30,
        cache_ttl_minutes=15,
    ),
    SourceCapability(
        source_id="xianyu.partner.v1",
        display_name="闲鱼官方合作方能力",
        category="computers_hardware",
        access_mode="authorized_partner",
        read_only=True,
        listing_search=False,
        status="link_only",
        allowed_regions=("CN",),
        allowed_fields=("title", "url", "price", "condition", "stock", "seller", "specs"),
        authorization_evidence_url="https://open.goofish.com/doc/development/dev/server.html",
    ),
    SourceCapability(
        source_id="zhuanzhuan.recommerce.mcp.v1",
        display_name="转转官方 MCP 回收估价",
        category="computers_hardware",
        access_mode="authorized_partner",
        read_only=True,
        listing_search=False,
        status="auxiliary_only",
        allowed_regions=("CN",),
        allowed_fields=("product", "model", "confidence", "price_range", "warnings", "handoff_url"),
        capabilities=("recycle_valuation", "open_recycle_entry"),
        authorization_evidence_url="https://open.zhuanzhuan.com/mcp",
    ),
    SourceCapability(
        source_id="game_accounts.policy.v1",
        display_name="游戏账号只读策略域",
        category="game_accounts",
        access_mode="user_link",
        read_only=True,
        listing_search=False,
        status="link_only",
        allowed_regions=("CN", "HK"),
        allowed_fields=("policy_status", "blocked_actions"),
        capabilities=("read_only_policy", "manual_link_only"),
    ),
    SourceCapability(
        source_id="game_accounts.5173.link.v1",
        display_name="5173 游戏账号人工入口",
        category="game_accounts",
        access_mode="user_link",
        read_only=True,
        listing_search=False,
        status="link_only",
        allowed_regions=("CN",),
        allowed_fields=("title", "url", "price", "game", "condition"),
        capabilities=("manual_link_only",),
        authorization_evidence_url="https://www.5173.com/",
    ),
    SourceCapability(
        source_id="game_accounts.taoshouyou.link.v1",
        display_name="淘手游游戏账号人工入口",
        category="game_accounts",
        access_mode="user_link",
        read_only=True,
        listing_search=False,
        status="link_only",
        allowed_regions=("CN",),
        allowed_fields=("title", "url", "price", "game", "condition"),
        capabilities=("manual_link_only",),
        authorization_evidence_url="https://www.taoshouyou.com/",
    ),
    SourceCapability(
        source_id="game_accounts.jaoyimc.link.v1",
        display_name="交易猫游戏账号人工入口",
        category="game_accounts",
        access_mode="user_link",
        read_only=True,
        listing_search=False,
        status="link_only",
        allowed_regions=("CN",),
        allowed_fields=("title", "url", "price", "game", "condition"),
        capabilities=("manual_link_only",),
        authorization_evidence_url="https://jaoyimc.com.cn/",
    ),
    SourceCapability(
        source_id="fixture.local.v1",
        display_name="本地固定回归数据",
        category="computers_hardware",
        access_mode="local_fixture",
        read_only=True,
        listing_search=True,
        status="ready",
        allowed_regions=("HK", "CN"),
        allowed_fields=("title", "url", "price", "condition", "stock", "shipping", "seller", "specs"),
    ),
)


def source_capability_registry() -> dict[str, SourceCapability]:
    """Return a fresh mapping of the declared source capabilities."""

    return {item.source_id: item for item in _CAPABILITIES}


__all__ = ["source_capability_registry"]
