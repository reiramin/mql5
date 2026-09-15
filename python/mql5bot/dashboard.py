"""mql5bot.dashboard — zero-dependency live web dashboard.

Serves an interactive single-page app that backtests the configured strategy
against a live bar feed (simulated, or bridged from MetaTrader 5) and shows
an up-to-date equity curve, drawdown, trade log and metrics. Uses only the
Python standard library so it runs anywhere.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .data import load_mt5
from .strategies import STRATEGIES, default_params

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mql5bot live dashboard</title>
<style>
:root { color-scheme: dark; }
body { font-family:'Segoe UI',system-ui,sans-serif; background:#0d1117; color:#e6edf3; margin:0; padding:20px; }
h1 { font-size:20px; margin:0 0 2px; } .sub { color:#8b949e; font-size:12px; margin-bottom:16px; }
.row { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:14px; }
label { font-size:12px; color:#8b949e; display:block; margin-bottom:3px; }
select, input { background:#161b22; border:1px solid #30363d; color:#e6edf3; border-radius:6px; padding:6px 8px; font-size:13px; }
button { background:#238636; border:0; color:#fff; border-radius:6px; padding:7px 14px; font-size:13px; cursor:pointer; }
button:hover { background:#2ea043; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-bottom:16px; }
.card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px 12px; }
.card .label { color:#8b949e; font-size:10.5px; text-transform:uppercase; letter-spacing:.04em; }
.card .value { font-size:18px; font-weight:600; margin-top:3px; font-variant-numeric:tabular-nums; }
.pos{color:#3fb950;} .neg{color:#f85149;}
.panel { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:14px; margin-bottom:16px; }
.panel h2 { font-size:14px; margin:0 0 10px; }
canvas { max-height:260px; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th,td { text-align:right; padding:5px 7px; border-bottom:1px solid #21262d; font-variant-numeric:tabular-nums; }
th:first-child,td:first-child { text-align:left; } th { color:#8b949e; font-weight:500; }
#status { font-size:12px; color:#8b949e; margin-left:10px; }
</style>
</head>
<body>
<h1>mql5bot live dashboard</h1>
<div class="sub" id="subtitle">loading…</div>
<div class="row">
  <div><label>strategy</label><select id="strategy"></select></div>
  <div><label>risk % / trade</label><input id="risk" type="number" value="1" min="0.1" step="0.1" style="width:80px"></div>
  <div><label>trailing ATR</label><input id="trail" type="number" value="2.5" step="0.5" style="width:80px"></div>
  <div><label>spread pts</label><input id="spread" type="number" value="1" step="0.1" style="width:80px"></div>
  <div><label>daily loss %</label><input id="daily" type="number" value="0" step="0.5" style="width:80px"></div>
  <div><label>&nbsp;</label><button id="run">Run backtest</button></div>
  <div style="align-self:end"><span id="status"></span></div>
</div>
<div class="cards" id="cards"></div>
<div class="panel"><h2>Equity</h2><canvas id="eq"></canvas></div>
<div class="panel"><h2>Drawdown %</h2><canvas id="dd"></canvas></div>
<div class="panel"><h2>Trades</h2><div id="trades"><p style="color:#8b949e">no trades yet</p></div></div>
<script>
const $ = id => document.getElementById(id);
let charts = {};
function makeChart(id, color){ charts[id]?.destroy();
  charts[id] = new Chart($(id), {type:'line',
    data:{labels:[],datasets:[{label:'',data:[],borderColor:color,backgroundColor:color+'18',fill:true,pointRadius:0,borderWidth:1.5,tension:.15}]},
    options:{plugins:{legend:{display:false}},animation:false,
      scales:{x:{ticks:{color:'#8b949e',maxTicksLimit:8},grid:{color:'#21262d'}},
              y:{ticks:{color:'#8b949e'},grid:{color:'#21262d'}}}}}); }
async function load(){
  const list = await (await fetch('/api/strategies')).json();
  $('strategy').innerHTML = list.map(s=>`<option value="${s.name}">${s.name} — ${s.family}</option>`).join('');
  const info = await (await fetch('/api/status')).json();
  $('subtitle').textContent = info.text;
  run();
}
async function run(){
  const q = new URLSearchParams({strategy:$('strategy').value, risk:$('risk').value,
    trail:$('trail').value, spread:$('spread').value, daily:$('daily').value});
  $('status').textContent = 'running…';
  const t0 = performance.now();
  try {
    const res = await (await fetch('/api/backtest?'+q)).json();
    $('status').textContent = `done in ${((performance.now()-t0)/1000).toFixed(2)}s · ${res.metrics.bars} bars`;
    render(res);
  } catch(e){ $('status').textContent = 'error: '+e; }
}
function card(label, value, cls=''){ return `<div class="card"><div class="label">${label}</div><div class="value ${cls}">${value}</div></div>`; }
const f = (v,d=2)=> v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d});
const pc = v => v==null?'—':(v>=0?'':'−')+Number(Math.abs(v)).toLocaleString(undefined,{maximumFractionDigits:2})+ '%';
function render(res){
  const m = res.metrics;
  const cls = v=>v==null?'':(v>=0?'pos':'neg');
  $('cards').innerHTML =
    card('total return', pc(m.total_return_pct), cls(m.total_return_pct)) +
    card('CAGR', pc(m.cagr_pct), cls(m.cagr_pct)) +
    card('Sharpe', f(m.sharpe)) +
    card('max drawdown', pc(m.max_drawdown_pct), 'neg') +
    card('win rate', pc(m.win_rate_pct)) +
    card('profit factor', f(m.profit_factor)) +
    card('trades', m.trades) +
    card('net profit', f(m.net_profit), cls(m.net_profit));
  const t = res.equity.time.map(x=>x.slice(0,16));
  makeChart('eq','#7ee787'); charts.eq.data.labels=t; charts.eq.data.datasets[0].data=res.equity.value; charts.eq.update();
  let peak=-Infinity;
  const dd = res.equity.value.map(v=>{peak=Math.max(peak,v);return (v/peak-1)*100;});
  makeChart('dd','#f85149'); charts.dd.data.labels=t; charts.dd.data.datasets[0].data=dd; charts.dd.update();
  const rows = res.trades.slice().reverse().map((tr,i)=>
    `<tr><td>${tr.exit_time}</td><td>${tr.side}</td><td>${tr.entry_price.toFixed(5)}</td>
     <td>${tr.exit_price.toFixed(5)}</td><td>${tr.lots.toFixed(2)}</td><td>${tr.bars_held}</td>
     <td class="${tr.pnl>=0?'pos':'neg'}">${tr.pnl>=0?'+':''}${tr.pnl.toFixed(2)}</td><td>${tr.exit_reason}</td></tr>`);
  $('trades').innerHTML = rows.length
    ? `<table><thead><tr><th>exit time</th><th>side</th><th>entry</th><th>exit</th><th>lots</th><th>bars</th><th>pnl</th><th>exit</th></tr></thead><tbody>${rows.join('')}</tbody></table>`
    : '<p style="color:#8b949e">no trades</p>';
}
$('run').onclick = run;
load();
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "mql5bot/1.0"

    def log_message(self, fmt, *args):  # keep console quiet
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        ctx: Dashboard = self.server.dashboard  # type: ignore[attr-defined]
        try:
            if parsed.path == "/":
                self._send(_PAGE.encode(), "text/html; charset=utf-8")
            elif parsed.path == "/api/strategies":
                self._send(
                    json.dumps(
                        [
                            {
                                "name": name,
                                "family": fn.__doc__.strip().splitlines()[0]
                                if fn.__doc__
                                else "",
                                "defaults": default_params(name),
                            }
                            for name, (fn, _) in STRATEGIES.items()
                        ]
                    ).encode(),
                    "application/json",
                )
            elif parsed.path == "/api/status":
                self._send(
                    json.dumps(ctx.status()).encode(), "application/json"
                )
            elif parsed.path == "/api/backtest":
                q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                payload = ctx.backtest(q)
                self._send(json.dumps(payload).encode(), "application/json")
            else:
                self._send(b'{"error":"not found"}', "application/json", 404)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._send(
                json.dumps({"error": str(exc)}).encode(), "application/json", 500
            )
        except Exception as exc:  # noqa: BLE001 - HTTP boundary: any failure
            # must answer 500 JSON, never leave the client hanging; the
            # error text is surfaced, so nothing is silently swallowed.
            self._send(
                json.dumps({"error": str(exc)}).encode(), "application/json", 500
            )


class Dashboard:
    """Holds dashboard state: the data feed (growing by one bar per second,
    simulated or live from MT5) and backtest-on-demand."""

    def __init__(
        self,
        df,
        *,
        live_symbol: str | None = None,
        live_timeframe: str = "H1",
    ):
        self.lock = threading.Lock()
        self.df = df
        self._next_index = len(df)  # resample timestamps for demo bars
        self.live_symbol = live_symbol
        self.live_timeframe = live_timeframe

    def status(self) -> dict:
        with self.lock:
            n = len(self.df)
        source = f"live MT5 {self.live_symbol} {self.live_timeframe}" if self.live_symbol else "simulated feed"
        return {
            "text": f"{source} · {n} bars · {self.df.index[0]} → {self.df.index[-1]}"
            f" · strategies: {len(STRATEGIES)}",
            "bars": n,
        }

    def next_bar(self) -> None:
        """Append one synthetic continuation bar (only used in demo mode)."""
        with self.lock:
            last = self.df.iloc[-1]
            rng = np.random.default_rng()
            vol = max(last["close"] * 0.0012, 1e-6)
            open_ = last["close"]
            close = open_ * (1 + rng.normal(0, vol * 0.8))
            high = max(open_, close) * (1 + abs(rng.normal(0, vol * 0.4)))
            low = min(open_, close) * (1 - abs(rng.normal(0, vol * 0.4)))
            ts = self.df.index[-1] + (self.df.index[-1] - self.df.index[-2])
            row = pd.DataFrame(
                {
                    "open": [open_],
                    "high": [high],
                    "low": [low],
                    "close": [close],
                    "volume": [1000.0],
                },
                index=pd.DatetimeIndex([ts]),
            )
            self.df = pd.concat([self.df, row])

    def refresh_mt5(self) -> bool:
        if not self.live_symbol:
            return False
        df = load_mt5(self.live_symbol, self.live_timeframe, bars=5000)
        with self.lock:
            self.df = df
        return True

    def backtest(self, q: dict) -> dict:
        strategy = q.get("strategy", "ema_crossover")
        if strategy not in STRATEGIES:
            strategy = "ema_crossover"
        with self.lock:
            df = self.df
        kwargs = {
            "risk_percent": float(q.get("risk", 1.0)),
            "trail_atr": float(q.get("trail", 2.5)),
            "spread_points": float(q.get("spread", 1.0)),
            "slippage_points": 0.0,
            "commission_per_lot": 7.0,
            "max_daily_loss_pct": float(q.get("daily", 0.0)),
        }
        result = run_backtest(df, strategy, None, **kwargs)
        return result.to_dict()


def run_dashboard(
    df,
    strategy: str = "ema_crossover",
    backtest_kwargs: dict | None = None,
    *,
    port: int = 8000,
    live_symbol: str | None = None,
    live_timeframe: str = "H1",
) -> None:
    """Start the dashboard server. Blocks forever (Ctrl+C to stop)."""
    dashboard = Dashboard(df, live_symbol=live_symbol, live_timeframe=live_timeframe)
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    server.dashboard = dashboard  # type: ignore[attr-defined]
    print(f"mql5bot dashboard listening on http://0.0.0.0:{port}")

    if not live_symbol:
        def feed_loop():
            while True:
                time.sleep(1.0)
                dashboard.next_bar()

        threading.Thread(target=feed_loop, daemon=True).start()
    else:
        def feed_loop():
            while True:
                try:
                    dashboard.refresh_mt5()
                except Exception as exc:  # noqa: BLE001 - live-refresh
                    # daemon boundary: a broker/telemetry error must not
                    # kill the feed thread; it is logged and retried.
                    print(f"MT5 refresh failed: {exc}")
                time.sleep(5.0)

        threading.Thread(target=feed_loop, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
