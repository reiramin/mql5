"""mql5bot command line interface.

Examples
--------
Generate synthetic data::

    mql5bot data --symbol EURUSD --timeframe H1 --days 730 --out data/EURUSD_H1.csv

Backtest one strategy with realistic costs::

    mql5bot backtest --data data/EURUSD_H1.csv --strategy ema_crossover \
        --spread 1.0 --slippage 0.5 --commission 7 --risk 1 \\
        --trail 2.5 --be 0 --daily-loss 5 --report results/report.html

Compare every strategy on the same data::

    mql5bot compare --data data/EURUSD_H1.csv

Grid-search parameters (parallel)::

    mql5bot optimize --data data/EURUSD_H1.csv --strategy ema_crossover \\
        --grid '{"fast":[8,10,12,16],"slow":[25,30,40]}' --jobs 4

Walk-forward validation::

    mql5bot walkforward --data data/EURUSD_H1.csv --strategy rsi_reversal \\
        --grid '{"period":[10,14,21]}' --windows 4

Start the live dashboard::

    mql5bot dashboard --port 8000
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mql5bot",
        description="mql5bot — algorithmic trading system for MetaTrader 5 (quant toolkit)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---------------- data ----------------
    p_data = sub.add_parser("data", help="generate or fetch OHLC data")
    p_data.add_argument("--symbol", default="EURUSD")
    p_data.add_argument("--timeframe", default="H1")
    p_data.add_argument("--days", type=int, default=730)
    p_data.add_argument("--start", default="2023-01-01")
    p_data.add_argument("--seed", type=int, default=42)
    p_data.add_argument("--annual-vol", type=float, default=0.12)
    p_data.add_argument("--drift", type=float, default=0.0)
    p_data.add_argument("--out", required=True, help="output CSV path")

    # ---------------- backtest ----------------
    def add_cost_args(p):
        p.add_argument("--capital", type=float, default=10_000.0)
        p.add_argument("--risk", type=float, default=1.0, help="risk %% of equity per trade")
        p.add_argument("--spread", type=float, default=1.0, help="spread in points")
        p.add_argument("--slippage", type=float, default=0.5, help="slippage in points per side")
        p.add_argument("--commission", type=float, default=7.0, help="round-trip commission per lot")
        p.add_argument("--point", type=float, default=1e-5)
        p.add_argument("--contract", type=float, default=100_000.0)
        p.add_argument("--no-short", action="store_true")
        p.add_argument("--trail", type=float, default=0.0, help="trailing stop in ATR")
        p.add_argument("--be", type=float, default=0.0, help="breakeven trigger in ATR")
        p.add_argument("--be-offset", type=float, default=0.0, help="breakeven offset in points")
        p.add_argument("--partial", type=float, default=0.0, help="partial close trigger in ATR")
        p.add_argument("--partial-frac", type=float, default=0.5)
        p.add_argument("--max-bars", type=int, default=0)
        p.add_argument("--daily-loss", type=float, default=0.0, help="daily loss limit %% (0=off)")
        p.add_argument("--max-dd", type=float, default=0.0, help="max drawdown kill switch %% (0=off)")

    p_bt = sub.add_parser("backtest", help="run a single backtest")
    p_bt.add_argument("--data", required=True)
    p_bt.add_argument("--strategy", required=True)
    p_bt.add_argument("--params", default=None, help="JSON dict of strategy params")
    p_bt.add_argument("--report", default=None, help="write HTML report to this path")
    p_bt.add_argument("--json-out", default=None, help="write JSON summary to this path")
    p_bt.add_argument("--train-frac", type=float, default=1.0, help="fraction of data to use")
    add_cost_args(p_bt)

    # ---------------- compare ----------------
    p_cmp = sub.add_parser("compare", help="compare all strategies on one dataset")
    p_cmp.add_argument("--data", required=True)
    p_cmp.add_argument("--report", default=None, help="write HTML comparison report")
    add_cost_args(p_cmp)

    # ---------------- optimize ----------------
    p_opt = sub.add_parser("optimize", help="grid-search strategy parameters")
    p_opt.add_argument("--data", required=True)
    p_opt.add_argument("--strategy", required=True)
    p_opt.add_argument("--grid", required=True, help="JSON dict: param -> list of values")
    p_opt.add_argument("--metric", default="sharpe")
    p_opt.add_argument("--minimize", action="store_true")
    p_opt.add_argument("--jobs", type=int, default=1)
    p_opt.add_argument("--top", type=int, default=10)
    p_opt.add_argument("--json-out", default=None)
    add_cost_args(p_opt)

    # ---------------- walk-forward ----------------
    p_wf = sub.add_parser("walkforward", help="walk-forward optimisation")
    p_wf.add_argument("--data", required=True)
    p_wf.add_argument("--strategy", required=True)
    p_wf.add_argument("--grid", default="{}", help="JSON param grid")
    p_wf.add_argument("--windows", type=int, default=3)
    p_wf.add_argument("--train-frac", type=float, default=0.6)
    p_wf.add_argument("--metric", default="sharpe")
    p_wf.add_argument("--json-out", default=None)
    add_cost_args(p_wf)

    # ---------------- dashboard ----------------
    p_dash = sub.add_parser("dashboard", help="start the live dashboard")
    p_dash.add_argument("--data", default=None, help="CSV to load; generated if omitted")
    p_dash.add_argument("--strategy", default="ema_crossover")
    p_dash.add_argument("--port", type=int, default=8000)
    add_cost_args(p_dash)

    args = parser.parse_args(argv)

    from . import backtest as bt_mod
    from . import data as data_mod
    from . import optimizer as opt_mod
    from . import report as report_mod
    from . import strategies as strat_mod

    try:
        if args.command == "data":
            df = data_mod.generate_ohlc(
                symbol=args.symbol,
                timeframe=args.timeframe,
                days=args.days,
                start=args.start,
                seed=args.seed,
                annual_vol=args.annual_vol,
                drift=args.drift,
            )
            data_mod.save_csv(df, args.out)
            print(f"wrote {len(df)} bars to {args.out}")

        elif args.command in ("backtest", "compare", "optimize", "walkforward", "dashboard"):
            df = data_mod.load_csv(args.data) if args.data else data_mod.generate_ohlc(days=730)
            train_frac = getattr(args, "train_frac", 1.0)
            if train_frac < 1.0 and args.command != "walkforward":
                n = int(len(df) * train_frac)
                df = df.iloc[:n]

            kwargs = {
                "initial_capital": args.capital,
                "risk_percent": args.risk,
                "allow_short": not args.no_short,
                "spread_points": args.spread,
                "slippage_points": args.slippage,
                "commission_per_lot": args.commission,
                "point": args.point,
                "contract_size": args.contract,
                "trail_atr": args.trail,
                "breakeven_atr": args.be,
                "breakeven_offset_points": args.be_offset,
                "partial_atr": args.partial,
                "partial_fraction": args.partial_frac,
                "max_bars": args.max_bars,
                "max_daily_loss_pct": args.daily_loss,
                "max_drawdown_pct": args.max_dd,
            }

            if args.command == "backtest":
                params = json.loads(args.params) if args.params else None
                res = bt_mod.run_backtest(df, args.strategy, params, **kwargs)
                _print_metrics(res.metrics)
                if args.report:
                    report_mod.save_report_html(res, args.report, title=f"{args.strategy} on {args.data}")
                    print(f"report -> {args.report}")
                if args.json_out:
                    _write_json(args.json_out, res.to_dict())
                    print(f"json -> {args.json_out}")

            elif args.command == "compare":
                results = []
                for name in strat_mod.STRATEGIES:
                    res = bt_mod.run_backtest(df, name, None, **kwargs)
                    results.append((name, res))
                    m = res.metrics
                    print(
                        f"{name:<20} ret {_fmt(m['total_return_pct']):>9}%  "
                        f"sharpe {_fmt(m['sharpe']):>6}  maxDD {_fmt(m['max_drawdown_pct']):>8}%  "
                        f"trades {m['trades']:>4}"
                    )
                if args.report:
                    html = report_mod.build_batch_report_html(
                        f"strategy comparison — {args.data}", results
                    )
                    import os

                    parent = os.path.dirname(os.path.abspath(args.report))
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(args.report, "w", encoding="utf-8") as fh:
                        fh.write(html)
                    print(f"report -> {args.report}")

            elif args.command == "optimize":
                grid = json.loads(args.grid)
                runs = opt_mod.grid_search(
                    df, args.strategy, grid, metric=args.metric,
                    minimize=args.minimize, n_jobs=args.jobs, **kwargs,
                )
                print(f"{'params':<42} {'metric':>10}")
                for r in runs[: args.top]:
                    print(f"{json.dumps(r.params):<42} {r.result.metrics.get(args.metric):>10}")
                if args.json_out:
                    _write_json(
                        args.json_out,
                        {
                            "strategy": args.strategy,
                            "metric": args.metric,
                            "runs": [r.summary() for r in runs[: args.top]],
                        },
                    )
                    print(f"json -> {args.json_out}")

            elif args.command == "walkforward":
                wf = opt_mod.walk_forward(
                    df, args.strategy, json.loads(args.grid),
                    train_fraction=args.train_frac, n_windows=args.windows,
                    metric=args.metric, **kwargs,
                )
                print("window  train_metric  best_params")
                for w in wf["windows"]:
                    print(
                        f"{w['window']:<8} {w['train_metric']:<13} "
                        f"{json.dumps(w['best_params'])}"
                    )
                oos = wf["oos_metrics"]
                print(
                    f"\nOOS aggregate: ret {_fmt(oos.get('total_return_pct'))}%  "
                    f"sharpe {_fmt(oos.get('sharpe'))}  maxDD {_fmt(oos.get('max_drawdown_pct'))}%"
                )
                if args.json_out:
                    _write_json(
                        args.json_out,
                        {
                            "strategy": args.strategy,
                            "windows": wf["windows"],
                            "oos_metrics": wf["oos_metrics"],
                        },
                    )
                    print(f"json -> {args.json_out}")

            elif args.command == "dashboard":
                from .dashboard import run_dashboard

                df.attrs["symbol"] = getattr(args, "data", None) or "EURUSD"
                print(f"dashboard: http://localhost:{args.port}")
                run_dashboard(df, args.strategy, kwargs, port=args.port)

    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_metrics(m: dict) -> None:
    rows = [
        ("total return", m["total_return_pct"], "%"),
        ("CAGR", m["cagr_pct"], "%"),
        ("Sharpe", m["sharpe"], ""),
        ("Sortino", m["sortino"], ""),
        ("max drawdown", m["max_drawdown_pct"], "%"),
        ("win rate", m["win_rate_pct"], "%"),
        ("profit factor", m["profit_factor"], ""),
        ("trades", m["trades"], ""),
        ("net profit", m["net_profit"], ""),
        ("expectancy", m["expectancy"], ""),
    ]
    width = max(len(label) for label, _, _ in rows)
    for label, value, unit in rows:
        print(f"{label:<{width}} {_fmt(value)} {unit}".rstrip())


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    return f"{float(v):,.2f}"


def _write_json(path: str, obj) -> None:
    import os

    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, default=str)


if __name__ == "__main__":
    sys.exit(main())
