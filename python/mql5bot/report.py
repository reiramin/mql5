"""mql5bot.report — self-contained HTML performance reports."""

from __future__ import annotations

import json
import math

from .backtest import BacktestResult

_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mql5bot report — {title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#0d1117; color:#e6edf3;
         margin:0; padding:24px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:#8b949e; margin-bottom:20px; font-size:13px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:24px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px 14px; }}
  .card .label {{ color:#8b949e; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }}
  .card .value {{ font-size:20px; font-weight:600; margin-top:4px; font-variant-numeric:tabular-nums; }}
  .pos {{ color:#3fb950; }} .neg {{ color:#f85149; }}
  .panel {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; margin-bottom:20px; }}
  h2 {{ font-size:15px; margin:0 0 12px; color:#e6edf3; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  th, td {{ text-align:right; padding:6px 8px; border-bottom:1px solid #21262d; font-variant-numeric:tabular-nums; }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ color:#8b949e; font-weight:500; }}
  code {{ background:#21262d; padding:2px 6px; border-radius:4px; font-size:12px; }}
</style>
</head>
<body>
<h1>mql5bot — {title}</h1>
<div class="sub">{subtitle}</div>
<div class="cards">{cards}</div>
<div class="panel"><h2>Equity curve</h2><div id="equity"></div></div>
<div class="panel"><h2>Drawdown</h2><div id="dd"></div></div>
<div class="panel"><h2>Trades</h2>{trades_table}</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
const C = {{color:'#7ee787', color2:'#f85149', grid:'#21262d', text:'#8b949e'}};
const eq = {equity};
const labels = eq.time.map(t => t.slice(0,16));
function ddCurve(values) {{
  let peak = -Infinity; return values.map(v => {{ peak = Math.max(peak, v); return (v/peak - 1)*100; }});
}}
new Chart(document.getElementById('equity'), {{type:'line',
  data:{{labels, datasets:[{{label:'Equity', data:eq.value, borderColor:C.color,
    backgroundColor:'rgba(126,231,135,.08)', fill:true, pointRadius:0, borderWidth:1.5, tension:.15}}]}},
  options:{{plugins:{{legend:{{display:false}}}}, scales:{{x:{{ticks:{{color:C.text, maxTicksLimit:10}}, grid:{{color:C.grid}}}},
    y:{{ticks:{{color:C.text}}, grid:{{color:C.grid}}}}}}, animation:false}}}});
new Chart(document.getElementById('dd'), {{type:'line',
  data:{{labels, datasets:[{{label:'Drawdown %', data:ddCurve(eq.value), borderColor:C.color2,
    backgroundColor:'rgba(248,81,73,.08)', fill:true, pointRadius:0, borderWidth:1.5, tension:.15}}]}},
  options:{{plugins:{{legend:{{display:false}}}}, scales:{{x:{{ticks:{{color:C.text, maxTicksLimit:10}}, grid:{{color:C.grid}}}},
    y:{{ticks:{{color:C.text}}, grid:{{color:C.grid}}}}}}, animation:false}}}});
</script>
</body>
</html>
"""

_TRADES_TABLE = """<table><thead><tr>
<th>#</th><th>entry time</th><th>exit time</th><th>side</th><th>entry</th><th>exit</th>
<th>lots</th><th>bars</th><th>pnl</th><th>pnl %</th><th>exit reason</th>
</tr></thead><tbody>{rows}</tbody></table>"""


def build_report_html(result: BacktestResult, *, title: str | None = None) -> str:
    """Render a full standalone HTML report for one backtest result."""
    metrics = result.metrics
    title = title or f"{result.strategy}"
    subtitle = (
        f"params: {json.dumps(result.params)} &nbsp;|&nbsp; "
        f"{metrics.get('start')} &rarr; {metrics.get('end')} &nbsp;|&nbsp; "
        f"{metrics.get('bars', 0):,} bars &nbsp;|&nbsp; config: {json.dumps(result.config)}"
    )

    cards = _cards(metrics)
    trades_rows = ""
    t = result.trades
    if len(t):
        for i, (_, row) in enumerate(t.iterrows(), 1):
            pnl = float(row["pnl"])
            cls = "pos" if pnl >= 0 else "neg"
            trades_rows += (
                f"<tr><td>{i}</td><td>{row['entry_time']}</td><td>{row['exit_time']}</td>"
                f"<td>{row['side']}</td><td>{row['entry_price']:.5f}</td>"
                f"<td>{row['exit_price']:.5f}</td><td>{row['lots']:.2f}</td>"
                f"<td>{int(row['bars_held'])}</td>"
                f"<td class='{cls}'>{pnl:+.2f}</td>"
                f"<td class='{cls}'>{float(row['pnl_pct']):+.3f}%</td>"
                f"<td>{row['exit_reason']}</td></tr>"
            )
    trades_table = (
        _TRADES_TABLE.format(rows=trades_rows) if trades_rows else "<p style='color:#8b949e'>No trades.</p>"
    )

    eq = result.equity
    step = max(1, math.ceil(len(eq) / 1500))
    equity_json = json.dumps(
        {"time": [str(x) for x in eq.index[::step]], "value": [float(v) for v in eq.values[::step]]}
    )
    return _REPORT_TEMPLATE.format(
        title=title,
        subtitle=subtitle,
        cards=cards,
        trades_table=trades_table,
        equity=equity_json,
    )


def build_batch_report_html(title: str, results: list[tuple[str, BacktestResult]]) -> str:
    """Render a comparison report for multiple backtest results."""
    rows = ""
    for label, res in results:
        m = res.metrics
        ret = m.get("total_return_pct")
        cls_ret = "pos" if (ret or 0) >= 0 else "neg"
        rows += (
            f"<tr><td><code>{label}</code></td>"
            f"<td class='{cls_ret}'>{_fmt(ret)}%</td>"
            f"<td>{_fmt(m.get('cagr_pct'))}%</td>"
            f"<td>{_fmt(m.get('sharpe'))}</td>"
            f"<td class='neg'>{_fmt(m.get('max_drawdown_pct'))}%</td>"
            f"<td>{_fmt(m.get('win_rate_pct'))}%</td>"
            f"<td>{_fmt(m.get('profit_factor'))}</td>"
            f"<td>{m.get('trades')}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>strategy</th><th>total return</th><th>CAGR</th>"
        "<th>Sharpe</th><th>max DD</th><th>win rate</th><th>profit factor</th>"
        "<th>trades</th></tr></thead><tbody>" + rows + "</tbody></table>"
    )
    html = _REPORT_TEMPLATE
    # drop the chart panels and chart script (no per-run curves in batch mode)
    html = html.replace(
        '<div class="panel"><h2>Equity curve</h2><div id="equity"></div></div>', ""
    )
    html = html.replace(
        '<div class="panel"><h2>Drawdown</h2><div id="dd"></div></div>', ""
    )
    html = html.replace('<div class="panel"><h2>Trades</h2>{trades_table}</div>', table)
    html = html.split("<script src=")[0] + "</body>\n</html>\n"
    subtitle = "comparison of backtest results — all runs share the same data window and cost model"
    return html.format(
        title=title,
        subtitle=subtitle,
        cards="",
        trades_table="",
        equity=json.dumps({"time": [], "value": []}),
    )


def save_report_html(result: BacktestResult, path: str, *, title: str | None = None) -> str:
    import os

    html = build_report_html(result, title=title)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


def _cards(metrics: dict) -> str:
    def card(label: str, value: str, cls: str = "") -> str:
        return f"<div class='card'><div class='label'>{label}</div><div class='value {cls}'>{value}</div></div>"

    def ret_cls(v) -> str:
        if v is None:
            return ""
        return "pos" if v >= 0 else "neg"

    m = metrics
    return "".join(
        [
            card("Total return", f"{_fmt(m.get('total_return_pct'))}%", ret_cls(m.get("total_return_pct"))),
            card("CAGR", f"{_fmt(m.get('cagr_pct'))}%", ret_cls(m.get("cagr_pct"))),
            card("Sharpe", _fmt(m.get("sharpe")), ""),
            card("Sortino", _fmt(m.get("sortino")), ""),
            card("Max drawdown", f"{_fmt(m.get('max_drawdown_pct'))}%", "neg"),
            card("Win rate", f"{_fmt(m.get('win_rate_pct'))}%", ""),
            card("Profit factor", _fmt(m.get("profit_factor")), ""),
            card("Trades", str(m.get("trades", 0)), ""),
            card("Net profit", f"{_fmt(m.get('net_profit'))}", ret_cls(m.get("net_profit"))),
        ]
    )


def _fmt(v, ndigits: int = 2):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{ndigits}f}"
    except (TypeError, ValueError):
        return str(v)
