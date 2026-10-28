"""Evidence-first result cards for the read-only MVP."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import re
from typing import Any, Iterable, Mapping

from .contracts import Evidence, Listing


@dataclass(frozen=True)
class ResultCard:
    listing_id: str
    title: str
    source_id: str
    url: str
    price: str | None
    landed_cost: str | None
    currency: str
    source_observed_at: str
    stock_status: str
    condition: str
    specs: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]
    evidence_ids: tuple[str, ...]
    risk_flags: tuple[str, ...]
    delivery_max_days: int | None = None
    warranty: str | None = None
    product_id: str | None = None
    status: str = "recommended"
    shipping_cost: str | None = None
    tax: str | None = None
    cost_status: str = "unknown"
    cost_basis: str = "unknown"
    evidence_coverage: float = 0.0
    source_rank: int = 0
    fit_score: float = 0.0
    fit_breakdown: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = [dict(item) for item in self.evidence]
        result["evidence_ids"] = list(self.evidence_ids)
        result["risk_flags"] = list(self.risk_flags)
        return result


def _money(value: Decimal | None) -> str | None:
    return f"{value:.2f}" if value is not None else None


def _markdown_untrusted(value: Any) -> str:
    """Keep external listing text on one safe Markdown line."""

    text = str(value if value is not None else "unknown").replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_\[\]{}()<>])", r"\\\1", text)


def _evidence_excerpt(item: Mapping[str, Any]) -> str:
    """Render a bounded evidence value without trusting listing text."""

    value = item.get("quote") if item.get("quote") not in (None, "") else item.get("value")
    text = str(value if value not in (None, "") else "unknown")
    text = text.replace("\r", " ").replace("\n", " ")
    if len(text) > 240:
        text = text[:237] + "..."
    return _markdown_untrusted(text)


def _table_untrusted(value: Any) -> str:
    """Keep untrusted listing text safe inside a Markdown table cell."""

    return _markdown_untrusted(value).replace("|", r"\|")


def build_card(
    listing: Listing,
    evidence: Iterable[Evidence],
    *,
    status: str = "recommended",
    source_rank: int = 0,
    fit_score: float = 0.0,
    fit_breakdown: Mapping[str, Any] | None = None,
) -> ResultCard:
    return ResultCard(
        listing_id=listing.listing_id,
        title=listing.title,
        source_id=listing.source_id,
        url=listing.url,
        price=_money(listing.price),
        landed_cost=_money(listing.landed_cost),
        currency=listing.currency,
        source_observed_at=listing.source_observed_at,
        stock_status=listing.stock_status,
        condition=listing.condition,
        specs=dict(listing.specs),
        delivery_max_days=listing.specs.get("delivery_max_days"),
        warranty=listing.specs.get("warranty"),
        product_id=listing.product_id,
        evidence=tuple(item.to_dict() for item in evidence),
        evidence_ids=listing.evidence_ids,
        risk_flags=listing.risk_flags,
        status=status,
        shipping_cost=_money(listing.shipping_cost),
        tax=_money(listing.tax),
        cost_status=listing.cost_status,
        cost_basis=listing.cost_basis,
        evidence_coverage=listing.evidence_coverage,
        source_rank=source_rank,
        fit_score=fit_score,
        fit_breakdown=dict(fit_breakdown or {}),
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render a compact, inspectable result card report."""

    if not payload.get("ok"):
        lines = [
            "# Muse Selector 结果卡",
            "",
            f"状态：{payload.get('status') or 'unknown'}",
            f"说明：{_markdown_untrusted(payload.get('message') or '没有可展示的结果。')}",
            "",
            "只读状态：true",
        ]
        policy = payload.get("policy") if isinstance(payload.get("policy"), Mapping) else None
        if policy:
            lines.extend(
                [
                    f"策略域：{_markdown_untrusted(policy.get('domain') or 'unknown')} / "
                    f"{_markdown_untrusted(policy.get('source_id') or 'unknown')}",
                    f"策略状态：{_markdown_untrusted(policy.get('status') or 'unknown')}；"
                    f"link-only：{_markdown_untrusted(policy.get('link_only'))}",
                    f"允许动作：{_markdown_untrusted(', '.join(policy.get('allowed_actions') or ()) or 'unknown')}",
                    f"阻断动作：{_markdown_untrusted(', '.join(policy.get('blocked_actions') or ()) or 'unknown')}",
                ]
            )
        link_only = payload.get("link_only") or []
        if link_only:
            lines.extend(["", "## 可人工打开的平台入口", ""])
            for item in link_only:
                entry_url = item.get("entry_url") or ""
                lines.extend(
                    [
                        f"### {_markdown_untrusted(item.get('display_name') or item.get('source_id') or 'unknown')}（link_only）",
                        f"- 官方入口：[{_markdown_untrusted(entry_url)}]({_markdown_untrusted(entry_url)})",
                        f"- 手动查询：{_markdown_untrusted(item.get('manual_query') or 'unknown')}",
                        f"- 说明：{_markdown_untrusted(item.get('instruction') or '仅允许人工打开和查看')}",
                        "- 只读状态：true；系统不会抓取、排序或执行平台写操作",
                        "",
                    ]
                )
        return "\n".join(lines) + "\n"

    spec = payload["search_spec"]
    source_capability = payload.get("source_capability") if isinstance(payload.get("source_capability"), Mapping) else {}
    capability_label = " / ".join(
        str(source_capability.get(key))
        for key in ("access_mode", "status", "environment")
        if source_capability.get(key)
    ) or "unknown"
    source_metadata = payload.get("source_metadata") if isinstance(payload.get("source_metadata"), Mapping) else {}
    latency_ms = source_metadata.get("latency_ms")
    lines = [
        "# Muse Selector 结果卡",
        "",
        f"查询：{_markdown_untrusted(spec['query'])}",
        f"地区/币种：{spec['region']} / {spec['currency']}",
        f"预算上限：{spec.get('budget_max') or '未指定'}",
        f"来源：{_markdown_untrusted(payload.get('source') or 'unknown')}",
        f"来源能力：{_markdown_untrusted(capability_label)}",
        "只读状态：true",
        "",
        "## 推荐结果",
        "",
    ]
    if isinstance(latency_ms, (int, float)) and latency_ms >= 0:
        lines.insert(5, f"来源请求耗时：{_markdown_untrusted(f'{float(latency_ms):.3f} ms')}")
    cards = payload.get("recommended", [])
    if not cards:
        lines.append("没有满足全部硬约束的结果。")
    for index, card in enumerate(cards, 1):
        cost_label = "到手价" if card.get("cost_status") == "complete" else "已知费用小计"
        lines.extend([
            f"### {index}. {_markdown_untrusted(card['title'])}",
            f"- 来源顺序：{card.get('source_rank') or index}（保留 eBay 来源顺序，未在客户端重排）",
            f"- 匹配分：{float(card.get('fit_score', 0.0)):.1f}/100；拆解：{_markdown_untrusted(card.get('fit_breakdown') or 'unknown')}",
            f"- 来源标识：{_markdown_untrusted(card.get('source_id') or 'unknown')}",
            f"- 实体标识：{_markdown_untrusted(card.get('product_id') or 'unknown')}",
            f"- {cost_label}：{card['landed_cost'] or 'unknown'} {card['currency']}（{card.get('cost_basis') or 'unknown'}）",
            f"- 运费/税费：{card.get('shipping_cost') or 'unknown'} / {card.get('tax') or 'unknown'} {card['currency']}",
            f"- 关键字段证据覆盖率：{float(card.get('evidence_coverage', 0.0)):.1%}",
            f"- 来源观测时间：{_markdown_untrusted(card.get('source_observed_at') or 'unknown')}",
            f"- 最长预计配送：{_markdown_untrusted(card.get('delivery_max_days') if card.get('delivery_max_days') is not None else 'unknown')} 天",
            f"- 保修：{_markdown_untrusted(card.get('warranty') or 'unknown')}",
            f"- 状态：{_markdown_untrusted(card['stock_status'])}；成色：{_markdown_untrusted(card['condition'])}",
            f"- 规格：{_markdown_untrusted(card['specs'] or 'unknown')}",
            f"- 来源：[打开原平台]({_markdown_untrusted(card['url'])})",
            f"- 风险：{_markdown_untrusted(', '.join(card['risk_flags']) if card['risk_flags'] else '未标记')}",
            f"- 证据字段：{_markdown_untrusted(', '.join(item['field'] for item in card['evidence']) or 'unknown')}",
            f"- 证据标识：{_markdown_untrusted(', '.join(card.get('evidence_ids') or ()) or 'unknown')}",
            *[
                f"- 证据片段（{_markdown_untrusted(item.get('field') or 'unknown')}）：{_evidence_excerpt(item)}；"
                f"提取：{_markdown_untrusted(item.get('extraction_method') or 'unknown')}；"
                f"原始字段：{_markdown_untrusted(item.get('raw_field') or 'unknown')}；"
                f"标准化：{_markdown_untrusted(item.get('normalization_rule') or 'unknown')}"
                for item in card.get('evidence', [])
            ],
            "",
        ])
    matrix = payload.get("compatibility_matrix")
    if isinstance(matrix, Mapping) and matrix.get("items"):
        lines.extend(["## 硬件兼容性矩阵", "", "| 商品 | 字段 | 要求 | 实际 | 状态 | 证据 |", "| --- | --- | --- | --- | --- | --- |"])
        for item in matrix.get("items") or []:
            for requirement in item.get("requirements") or []:
                evidence = ", ".join(requirement.get("evidence_ids") or ()) or "unknown"
                lines.append(
                    "| " + " | ".join([
                        _table_untrusted(item.get("listing_id") or "unknown"),
                        _table_untrusted(requirement.get("field") or "unknown"),
                        _table_untrusted(requirement.get("required")),
                        _table_untrusted(requirement.get("actual") if requirement.get("actual") is not None else "unknown"),
                        _table_untrusted(requirement.get("status") or "unknown"),
                        _table_untrusted(evidence),
                    ]) + " |"
                )
        lines.append("")
    if payload.get("rejected"):
        lines.extend(["## 被硬约束过滤的结果", ""])
        for item in payload["rejected"]:
            lines.append(f"- `{_markdown_untrusted(item['listing_id'])}`：{_markdown_untrusted(', '.join(item['reasons']))}")
    if payload.get("dropped"):
        lines.extend(["", "## 未进入推荐的来源记录", ""])
        for item in payload["dropped"]:
            lines.append(f"- `{_markdown_untrusted(item['listing_id'])}`：{_markdown_untrusted(item['reason'])}")
    return "\n".join(lines).rstrip() + "\n"


def render_comparison(payload: Mapping[str, Any]) -> str:
    """Render source-order recommendations as a compact comparison artifact."""

    if not payload.get("ok"):
        return render_markdown(payload)
    spec = payload.get("search_spec") or {}
    source_capability = payload.get("source_capability") if isinstance(payload.get("source_capability"), Mapping) else {}
    capability_label = " / ".join(
        str(source_capability.get(key))
        for key in ("access_mode", "status", "environment")
        if source_capability.get(key)
    ) or "unknown"
    source_metadata = payload.get("source_metadata") if isinstance(payload.get("source_metadata"), Mapping) else {}
    latency_ms = source_metadata.get("latency_ms")
    latency_label = f"{float(latency_ms):.3f} ms" if isinstance(latency_ms, (int, float)) and latency_ms >= 0 else "unknown"
    lines = [
        "# Muse Selector 比较表",
        "",
        f"查询：{_table_untrusted(spec.get('query') or 'unknown')}",
        f"地区/币种：{_table_untrusted(spec.get('region') or 'unknown')} / {_table_untrusted(spec.get('currency') or 'unknown')}",
        f"来源：{_table_untrusted(payload.get('source') or 'unknown')}（保留来源顺序，不在客户端重排）",
        f"来源能力：{_table_untrusted(capability_label)}",
        f"来源请求耗时：{_table_untrusted(latency_label)}",
        "只读状态：true",
        "",
        "| 来源顺序 | 商品 | 实体标识 | 成本 | 证据覆盖 | 观测时间 | 状态/成色 | 配送 | 保修 | 风险 | 来源能力 | 来源 |",
        "| ---: | --- | --- | --- | ---: | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for index, card in enumerate(payload.get("recommended") or [], 1):
        cost = card.get("landed_cost") or "unknown"
        currency = card.get("currency") or ""
        cost_status = card.get("cost_status") or "unknown"
        coverage = card.get("evidence_coverage")
        try:
            coverage_text = f"{float(coverage):.1%}"
        except (TypeError, ValueError):
            coverage_text = "unknown"
        delivery = card.get("delivery_max_days")
        delivery_text = f"{delivery} 天" if delivery is not None else "unknown"
        risk = ", ".join(card.get("risk_flags") or []) or "未标记"
        lines.append(
            "| "
            + " | ".join([
                _table_untrusted(card.get("source_rank") or index),
                _table_untrusted(card.get("title") or "unknown"),
                _table_untrusted(card.get("product_id") or "unknown"),
                _table_untrusted(f"{cost} {currency} ({cost_status})".strip()),
                _table_untrusted(coverage_text),
                _table_untrusted(card.get("source_observed_at") or "unknown"),
                _table_untrusted(f"{card.get('stock_status') or 'unknown'} / {card.get('condition') or 'unknown'}"),
                _table_untrusted(delivery_text),
                _table_untrusted(card.get("warranty") or "unknown"),
                _table_untrusted(risk),
                _table_untrusted(capability_label),
                _table_untrusted(f"{card.get('source_id') or 'unknown'} · {card.get('url') or 'unknown'}"),
            ])
            + " |"
        )
    if not payload.get("recommended"):
        lines.extend(["", "没有满足全部硬约束的结果。"])
    return "\n".join(lines).rstrip() + "\n"

