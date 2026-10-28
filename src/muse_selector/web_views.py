"""Pure HTML and safe-link rendering helpers for the Muse Selector web view."""

from __future__ import annotations

import html
import json
from typing import Any, Mapping
from urllib.parse import urlparse

from .url_policy import is_allowed_market_url


def _text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _capability_label(payload: Mapping[str, Any]) -> str:
    capability = payload.get("source_capability")
    if not isinstance(capability, Mapping):
        return "unknown"
    return " / ".join(
        str(capability.get(key))
        for key in ("access_mode", "status", "environment")
        if capability.get(key)
    ) or "unknown"


def _evidence_excerpt(item: dict[str, Any]) -> str:
    """Return a bounded, escaped evidence value for the local result page."""

    value = item.get("quote") if item.get("quote") not in (None, "") else item.get("value")
    text = str(value if value not in (None, "") else "unknown").replace("\r", " ").replace("\n", " ")
    if len(text) > 240:
        text = text[:237] + "..."
    return _text(text)


def _safe_href(value: Any) -> str:
    candidate = str(value or "")
    return candidate if is_allowed_market_url(candidate) else "#"


def _safe_manual_href(value: Any) -> str:
    """Allow only the registered domestic platform entry domains."""

    candidate = str(value or "")
    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError:
        return "#"
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in {
            "goofish.com",
            "www.goofish.com",
            "zhuanzhuan.com",
            "www.zhuanzhuan.com",
        }
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate)
    ):
        return "#"
    return candidate


def _source_metadata_markup(payload: dict[str, Any]) -> str:
    """Render bounded source response metadata without trusting source text."""

    metadata = payload.get("source_metadata")
    if not isinstance(metadata, dict) or not metadata:
        return ""
    # Keep this as escaped JSON so new connector metadata becomes visible
    # without needing a template change, while preserving a safe text-only UI.
    serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2)
    if len(serialized) > 8000:
        serialized = serialized[:7997] + "..."
    source = payload.get("source") or "unknown"
    return (
        "<details class='source-metadata'><summary>来源元数据</summary>"
        f"<p>来源：<code>{_text(source)}</code></p>"
        f"<pre>{_text(serialized)}</pre></details>"
    )


def _compatibility_matrix_markup(payload: dict[str, Any]) -> str:
    matrix = payload.get("compatibility_matrix")
    if not isinstance(matrix, dict) or not matrix.get("items"):
        return ""
    rows: list[str] = []
    for item in matrix.get("items") or []:
        if not isinstance(item, dict):
            continue
        for requirement in item.get("requirements") or []:
            if not isinstance(requirement, dict):
                continue
            evidence_ids = ", ".join(requirement.get("evidence_ids") or ()) or "unknown"
            rows.append(
                "<tr>"
                f"<td><code>{_text(item.get('listing_id') or 'unknown')}</code></td>"
                f"<td>{_text(requirement.get('field') or 'unknown')}</td>"
                f"<td>{_text(requirement.get('required'))}</td>"
                f"<td>{_text(requirement.get('actual') if requirement.get('actual') is not None else 'unknown')}</td>"
                f"<td>{_text(requirement.get('status') or 'unknown')}</td>"
                f"<td><code>{_text(evidence_ids)}</code></td>"
                "</tr>"
            )
    if not rows:
        return ""
    return (
        "<section class='compatibility'><h2>硬件兼容性矩阵</h2>"
        "<table><thead><tr><th>商品</th><th>字段</th><th>要求</th><th>实际</th><th>状态</th><th>证据</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def render_html(payload: dict[str, Any], query: str) -> str:
    """Render a safe, source-visible result page from a pipeline payload."""
    if not payload.get("ok"):
        link_only = payload.get("link_only") or []
        entry_cards = []
        for entry in link_only:
            if not isinstance(entry, dict):
                continue
            href = _safe_manual_href(entry.get("entry_url"))
            entry_cards.append(
                "<article class='card'>"
                f"<h2>{_text(entry.get('display_name') or entry.get('source_id') or '官方入口')}</h2>"
                f"<p>状态：<code>{_text(entry.get('status') or 'link_only')}</code> · 只读：{_text(entry.get('read_only', True))}</p>"
                f"<p>手动查询：<code>{_text(entry.get('manual_query') or query)}</code></p>"
                f"<p>{_text(entry.get('instruction') or '请在官方平台内手动完成查询。')}</p>"
                f"<p><a rel='noreferrer' target='_blank' href='{_text(href)}'>打开官方入口</a></p>"
                "</article>"
            )
        manual_section = (
            "<section class='manual-entry'><h2>人工接管入口</h2>"
            f"<div class='cards'>{''.join(entry_cards)}</div></section>"
            if entry_cards
            else ""
        )
        body = (
            "<section class='notice danger'><strong>"
            f"{_text(payload.get('status'))}</strong><p>{_text(payload.get('message', '请求被阻止'))}</p></section>"
            f"{manual_section}"
        )
    else:
        spec = payload.get("search_spec") or {}
        cards: list[str] = []
        for card in payload.get("recommended") or []:
            cost_label = "到手价" if card.get("cost_status") == "complete" else "已知费用小计"
            try:
                coverage_label = f"{float(card.get('evidence_coverage')):.1%}"
            except (TypeError, ValueError):
                coverage_label = "unknown"
            evidence = "".join(
                f"<li><code>{_text(item.get('field'))}</code> · {_text(item.get('status'))} · "
                f"观测时间：{_text(item.get('observed_at') or 'unknown')} · "
                f"提取：{_text(item.get('extraction_method') or 'unknown')} · "
                f"原始字段：{_text(item.get('raw_field') or 'unknown')} · "
                f"标准化：{_text(item.get('normalization_rule') or 'unknown')} · "
                f"证据：{_evidence_excerpt(item)} · {_text(item.get('source_url'))}</li>"
                for item in card.get("evidence", [])
            ) or "<li>unknown</li>"
            risk = ", ".join(card.get("risk_flags") or []) or "未标记"
            href = _safe_href(card.get("url"))
            cards.append(
                "<article class='card'>"
                f"<h2>{_text(card.get('title'))}</h2>"
                f"<p>来源标识：<code>{_text(card.get('source_id') or 'unknown')}</code></p>"
                f"<p>实体标识：<code>{_text(card.get('product_id') or 'unknown')}</code></p>"
                f"<p>来源顺序：{_text(card.get('source_rank') or 'unknown')}（保留 eBay 来源顺序） · 匹配分：{_text(card.get('fit_score') or '0')} / 100</p>"
                f"<p>匹配拆解：<code>{_text(json.dumps(card.get('fit_breakdown') or {}, ensure_ascii=False, sort_keys=True))}</code></p>"
                f"<p class='price'>{_text(cost_label)}：{_text(card.get('landed_cost') or 'unknown')} {_text(card.get('currency'))}</p>"
                f"<p>运费/税费：{_text(card.get('shipping_cost') or 'unknown')} / {_text(card.get('tax') or 'unknown')} {_text(card.get('currency'))} · 基准：{_text(card.get('cost_basis') or 'unknown')}</p>"
                f"<p>关键字段证据覆盖率：{_text(coverage_label)}</p>"
                f"<p>来源观测时间：{_text(card.get('source_observed_at') or 'unknown')}</p>"
                f"<p>最长预计配送：{_text(card.get('delivery_max_days') if card.get('delivery_max_days') is not None else 'unknown')} 天</p>"
                f"<p>保修：{_text(card.get('warranty') or 'unknown')}</p>"
                f"<p>库存：{_text(card.get('stock_status'))} · 成色：{_text(card.get('condition'))}</p>"
                f"<p>规格：<code>{_text(json.dumps(card.get('specs') or {}, ensure_ascii=False, sort_keys=True))}</code></p>"
                f"<p>风险：{_text(risk)}</p>"
                f"<p><a rel='noreferrer' target='_blank' href='{_text(href)}'>打开原平台</a></p>"
                f"<details><summary>证据（{len(card.get('evidence', []))}）</summary><ul>{evidence}</ul></details>"
                "</article>"
            )
        rejected = "".join(
            f"<li><code>{_text(item.get('listing_id'))}</code>：{_text(', '.join(item.get('reasons') or []))}</li>"
            for item in payload.get("rejected", [])
        ) or "<li>无</li>"
        dropped = "".join(
            f"<li><code>{_text(item.get('listing_id'))}</code>：{_text(item.get('reason'))}</li>"
            for item in payload.get("dropped", [])
        ) or "<li>无</li>"
        body = (
            f"<section class='summary'><p>地区/币种：{_text(spec.get('region'))} / {_text(spec.get('currency'))}</p>"
            f"<p>预算上限：{_text(spec.get('budget_max') or '未指定')}</p>"
            f"<p>来源能力：{_text(_capability_label(payload))}</p></section>"
            f"{_source_metadata_markup(payload)}"
            "<h2>推荐结果</h2>"
            f"<div class='cards'>{''.join(cards) or '<p>没有满足全部硬约束的结果。</p>'}</div>"
            f"{_compatibility_matrix_markup(payload)}"
            f"<details><summary>被过滤结果（{len(payload.get('rejected', []))}）</summary><ul>{rejected}</ul></details>"
            f"<details><summary>未进入推荐的来源记录（{len(payload.get('dropped', []))}）</summary><ul>{dropped}</ul></details>"
        )
    return f"""<!doctype html><html lang='zh-Hans'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Muse Selector · 中国二手市场只读筛选</title>
<style>body{{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;max-width:1100px;margin:0 auto;padding:24px;background:#f6f7f9;color:#1f2937}}h1{{margin-bottom:4px}}.muted{{color:#64748b;font-size:.9rem}}form{{display:flex;gap:8px;margin:20px 0}}input{{flex:1;padding:11px;border:1px solid #cbd5e1;border-radius:8px;font-size:1rem}}button{{padding:11px 18px;border:0;border-radius:8px;background:#2563eb;color:white;cursor:pointer}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}}.card,.summary,.notice,details{{background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin:12px 0}}.card h2{{font-size:1.05rem;margin:0 0 8px}}.price{{font-weight:700;font-size:1.2rem;color:#0f766e}}code{{word-break:break-word}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0}}a{{color:#1d4ed8}}.danger{{border-color:#fca5a5;background:#fff1f2}}ul{{padding-left:20px}}</style></head><body>
<h1>Muse Selector</h1><p class='muted'>中国大陆二手电子产品与游戏账号 · 只读结果页</p>
<form method='get' action='/'><input name='q' value='{_text(query)}' aria-label='查询'><button type='submit'>筛选</button></form>
<p class='muted'>来源数据、证据时间和风险状态均可展开查看；本页面没有登录、购买或写操作能力。</p>
{body}</body></html>"""


