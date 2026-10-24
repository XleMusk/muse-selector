"""Evidence-first result cards for the read-only MVP."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import re
from typing import Any, Iterable, Mapping

from .contracts import Evidence, Listing, SearchSpec
from .filtering import FilterDecision


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
    risk_flags: tuple[str, ...]
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
        result["risk_flags"] = list(self.risk_flags)
        return result


def _money(value: Decimal | None) -> str | None:
    return f"{value:.2f}" if value is not None else None


def _markdown_untrusted(value: Any) -> str:
    """Keep external listing text on one safe Markdown line."""

    text = str(value if value is not None else "unknown").replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_\[\]{}()<>])", r"\\\1", text)


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
        evidence=tuple(item.to_dict() for item in evidence),
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
        return "\n".join(lines) + "\n"

    spec = payload["search_spec"]
    lines = [
        "# Muse Selector 结果卡",
        "",
        f"查询：{_markdown_untrusted(spec['query'])}",
        f"地区/币种：{spec['region']} / {spec['currency']}",
        f"预算上限：{spec.get('budget_max') or '未指定'}",
        f"来源：{_markdown_untrusted(payload.get('source') or 'unknown')}",
        "只读状态：true",
        "",
        "## 推荐结果",
        "",
    ]
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
            f"- {cost_label}：{card['landed_cost'] or 'unknown'} {card['currency']}（{card.get('cost_basis') or 'unknown'}）",
            f"- 运费/税费：{card.get('shipping_cost') or 'unknown'} / {card.get('tax') or 'unknown'} {card['currency']}",
            f"- 关键字段证据覆盖率：{float(card.get('evidence_coverage', 0.0)):.1%}",
            f"- 来源观测时间：{_markdown_untrusted(card.get('source_observed_at') or 'unknown')}",
            f"- 状态：{_markdown_untrusted(card['stock_status'])}；成色：{_markdown_untrusted(card['condition'])}",
            f"- 规格：{_markdown_untrusted(card['specs'] or 'unknown')}",
            f"- 来源：[打开原平台]({_markdown_untrusted(card['url'])})",
            f"- 风险：{_markdown_untrusted(', '.join(card['risk_flags']) if card['risk_flags'] else '未标记')}",
            f"- 证据字段：{_markdown_untrusted(', '.join(item['field'] for item in card['evidence']) or 'unknown')}",
            "",
        ])
    if payload.get("rejected"):
        lines.extend(["## 被硬约束过滤的结果", ""])
        for item in payload["rejected"]:
            lines.append(f"- `{_markdown_untrusted(item['listing_id'])}`：{_markdown_untrusted(', '.join(item['reasons']))}")
    if payload.get("dropped"):
        lines.extend(["", "## 未进入推荐的来源记录", ""])
        for item in payload["dropped"]:
            lines.append(f"- `{_markdown_untrusted(item['listing_id'])}`：{_markdown_untrusted(item['reason'])}")
    return "\n".join(lines).rstrip() + "\n"

