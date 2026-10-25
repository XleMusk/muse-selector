"""Minimal local read-only web view for Muse Selector results."""

from __future__ import annotations

import argparse
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .connectors.ebay import EbayBrowseConnector
from .pipeline import _allowed_source_url, run_search
from .persistence import SelectorStore


def _text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _evidence_excerpt(item: dict[str, Any]) -> str:
    """Return a bounded, escaped evidence value for the local result page."""

    value = item.get("quote") if item.get("quote") not in (None, "") else item.get("value")
    text = str(value if value not in (None, "") else "unknown").replace("\r", " ").replace("\n", " ")
    if len(text) > 240:
        text = text[:237] + "..."
    return _text(text)


def _safe_href(value: Any) -> str:
    candidate = str(value or "")
    return candidate if _allowed_source_url(candidate) else "#"


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


def _validate_bind_host(host: str) -> str:
    """Keep the local result page on loopback to prevent cross-tenant reads."""

    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("local result page host must be 127.0.0.1 or ::1")
    return host


def capability_snapshot() -> dict[str, Any]:
    """Return local source readiness without issuing any network request."""

    client_id = str(os.environ.get("EBAY_CLIENT_ID") or "").strip()
    client_secret = str(os.environ.get("EBAY_CLIENT_SECRET") or "").strip()
    credential_state = "configured" if client_id and client_secret else "partial" if client_id or client_secret else "missing"
    ebay: dict[str, Any] = {
        "source_id": "ebay.browse.hk.v1",
        "read_only": True,
        "listing_search": True,
        "credential_state": credential_state,
        "environment": "unknown",
        "status": "unavailable",
    }
    try:
        connector = EbayBrowseConnector()
        ebay.update(
            {
                "environment": connector.config.environment,
                "status": "disabled" if connector._kill_switch_active() else "ready" if connector.live_enabled else "credential_unavailable",
            }
        )
    except (TypeError, ValueError, OSError):
        ebay["status"] = "configuration_error"
    return {
        "ok": True,
        "read_only": True,
        "sources": {
            "ebay.browse.hk.v1": ebay,
            "xianyu.partner.v1": {
                "source_id": "xianyu.partner.v1",
                "read_only": True,
                "listing_search": False,
                "region": "CN",
                "currency": "CNY",
                "status": "link_only",
            },
            "zhuanzhuan.recommerce.mcp.v1": {
                "source_id": "zhuanzhuan.recommerce.mcp.v1",
                "read_only": True,
                "listing_search": False,
                "region": "CN",
                "currency": "CNY",
                "status": "auxiliary_only",
                "capabilities": ["recycle_valuation", "open_recycle_entry"],
            },
        },
    }


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
            f"<p>预算上限：{_text(spec.get('budget_max') or '未指定')}</p></section>"
            "<h2>推荐结果</h2>"
            f"<div class='cards'>{''.join(cards) or '<p>没有满足全部硬约束的结果。</p>'}</div>"
            f"<details><summary>被过滤结果（{len(payload.get('rejected', []))}）</summary><ul>{rejected}</ul></details>"
            f"<details><summary>未进入推荐的来源记录（{len(payload.get('dropped', []))}）</summary><ul>{dropped}</ul></details>"
        )
    return f"""<!doctype html><html lang='zh-Hans'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Muse Selector · 香港硬件只读筛选</title>
<style>body{{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;max-width:1100px;margin:0 auto;padding:24px;background:#f6f7f9;color:#1f2937}}h1{{margin-bottom:4px}}.muted{{color:#64748b;font-size:.9rem}}form{{display:flex;gap:8px;margin:20px 0}}input{{flex:1;padding:11px;border:1px solid #cbd5e1;border-radius:8px;font-size:1rem}}button{{padding:11px 18px;border:0;border-radius:8px;background:#2563eb;color:white;cursor:pointer}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}}.card,.summary,.notice,details{{background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin:12px 0}}.card h2{{font-size:1.05rem;margin:0 0 8px}}.price{{font-weight:700;font-size:1.2rem;color:#0f766e}}code{{word-break:break-word}}a{{color:#1d4ed8}}.danger{{border-color:#fca5a5;background:#fff1f2}}ul{{padding-left:20px}}</style></head><body>
<h1>Muse Selector</h1><p class='muted'>香港电脑/硬件 · eBay HK · 只读结果页</p>
<form method='get' action='/'><input name='q' value='{_text(query)}' aria-label='查询'><button type='submit'>筛选</button></form>
<p class='muted'>来源数据、证据时间和风险状态均可展开查看；本页面没有登录、购买或写操作能力。</p>
{body}</body></html>"""


def make_handler(
    fixture_path: str | Path | None = None,
    store: SelectorStore | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one fixture or source configuration."""
    fixture = str(fixture_path) if fixture_path is not None else None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._send(200, "application/json; charset=utf-8", b'{"ok":true,"read_only":true}')
                return
            if parsed.path == "/api/capabilities":
                content = json.dumps(capability_snapshot(), ensure_ascii=False, sort_keys=True).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", content)
                return
            if parsed.path == "/api/watches":
                if store is None:
                    self._send_json(
                        503,
                        {
                            "ok": False,
                            "status": "watch_unavailable",
                            "message": "start the web view with --db to expose persisted watches",
                            "read_only": True,
                        },
                    )
                    return
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "status": "watches_ready",
                        "read_only": True,
                        "watches": store.list_watches(),
                    },
                )
                return
            if parsed.path == "/api/watch":
                watch_id = parse_qs(parsed.query).get("watch_id", [""])[0].strip()
                if not watch_id:
                    self._send_json(
                        400,
                        {
                            "ok": False,
                            "status": "invalid_query",
                            "message": "watch_id is required",
                            "read_only": True,
                        },
                    )
                    return
                if store is None:
                    self._send_json(
                        503,
                        {
                            "ok": False,
                            "status": "watch_unavailable",
                            "message": "start the web view with --db to expose persisted watch snapshots",
                            "read_only": True,
                        },
                    )
                    return
                watch = store.get_watch(watch_id)
                if watch is None:
                    self._send_json(
                        404,
                        {
                            "ok": False,
                            "status": "watch_not_found",
                            "message": f"unknown watch_id: {watch_id}",
                            "read_only": True,
                        },
                    )
                    return
                result: dict[str, Any] = {
                    "ok": True,
                    "status": "watch_ready",
                    "read_only": True,
                    "watch": watch,
                }
                run_id = watch.get("last_run_id")
                if run_id:
                    result["payload"] = store.replay_run(str(run_id))
                self._send_json(200, result)
                return
            if parsed.path == "/api/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                raw_limit = parse_qs(parsed.query).get("limit", ["10"])[0]
                try:
                    limit = int(raw_limit)
                except (TypeError, ValueError):
                    limit = 0
                payload = run_search(query, fixture, limit=limit)
                content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", content)
                return
            if parsed.path != "/":
                self._send(404, "text/plain; charset=utf-8", b"not found")
                return
            query = parse_qs(parsed.query).get("q", ["香港预算 HKD 7000 以内的迷你主机"])[0]
            content = render_html(run_search(query, fixture), query).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", content)

        def _send(self, status: int, content_type: str, content: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", content)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve(
    fixture_path: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: str | Path | None = None,
) -> None:
    host = _validate_bind_host(host)
    store = SelectorStore(db_path) if db_path is not None else None
    server = ThreadingHTTPServer((host, port), make_handler(fixture_path, store))
    print(f"Muse Selector read-only web view: http://{host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Local read-only Muse Selector web view")
    parser.add_argument("--fixture", default=None, help="offline fixture; omit to use live read-only API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    parser.add_argument("--db", default=None, help="local SQLite database for read-only /api/watch snapshots")
    args = parser.parse_args()
    previous_environment = os.environ.get("EBAY_ENVIRONMENT")
    try:
        if args.environment is not None:
            os.environ["EBAY_ENVIRONMENT"] = args.environment
        serve(Path(args.fixture) if args.fixture else None, args.host, args.port, Path(args.db) if args.db else None)
    finally:
        if previous_environment is None:
            os.environ.pop("EBAY_ENVIRONMENT", None)
        else:
            os.environ["EBAY_ENVIRONMENT"] = previous_environment
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

