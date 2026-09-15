#!/usr/bin/env python3
"""run_mt5_backtest — headless MetaTrader 5 Strategy Tester CLI (Phase 2).

Drives the mql5bot EA through the Strategy Tester from the shell, with no
GUI clicking.  Deterministic, documented, reproducible artifacts.

  generate-set    write a .set preset (EA defaults + overrides)
  generate-ini    write a tester.ini ([Tester] + [TesterInputs])
  matrix          write a batch jobs.json (strategy x symbol x timeframe)
  parse           parse an MT5 tester HTML report to JSON
  run             launch terminal64.exe headless and parse the report
                  (Windows only; raw report preserved before parsing)
  batch           run many jobs sequentially and emit one JSON array

Config determinism: symbol, timeframe, dates, model, deposit, currency and
leverage are set explicitly per run and echoed into every artifact.  MT5
applies broker symbol conditions (spread, ticks) — cost scenarios are
handled by the Python execution model, not hidden here.

Owner protocol (CANONICAL: docs/MT5_ROUNDTRIP.md, the TEN-step owner
sequence — single source of truth): this tool executes canonical steps
5–7 (the M1-OHLC baseline leg, the Every-Tick leg and the
Every-Tick-real-ticks leg, including the raw-report archive + parse
sub-steps).  This sandbox has no terminal64.exe.  A green backtest claim
requires the actual `run`/`batch` output from a Windows machine, pasted
back into the session together with the run artifacts.

Exit codes: 0 ok; 1 runtime/parse failure; 2 usage/config error; 3
platform guard (run/batch on a non-Windows host).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mql5bot.mt5tester import (
    EA_INPUT_DEFAULTS,
    MT5_MODEL_LABELS,
    MT5_TIMEFRAMES,
    RunSettings,
    TesterConfig,
    inputs_to_lines,
    parse_report_html,
    render_set,
    run_backtest,
    run_batch,
    validate_inputs,
)

EA = "Experts\\Mql5Bot\\Mql5Bot.ex5"


# ---------------------------------------------------------------------------
# value coercion for --input k=v
# ---------------------------------------------------------------------------

def coerce_value(raw: str):
    """'true'/'false' -> bool; ints -> int; floats -> float; else verbatim."""
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def parse_kv_pairs(items: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--input expects key=value, got {item!r}")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"--input has an empty key: {item!r}")
        out[key] = coerce_value(value)
    return out


def add_config_args(parser: argparse.ArgumentParser, *, with_ea: bool = True) -> None:
    if with_ea:
        parser.add_argument("--ea", default=EA, help=".ex5 path under MQL5")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--timeframe", default="H1",
                        choices=MT5_TIMEFRAMES)
    parser.add_argument("--model", type=int, default=1, choices=sorted(MT5_MODEL_LABELS))
    parser.add_argument("--from", dest="date_from", default="2020.01.01",
                        metavar="YYYY.MM.DD")
    parser.add_argument("--to", dest="date_to", default="2024.01.01",
                        metavar="YYYY.MM.DD")
    parser.add_argument("--deposit", type=float, default=10000.0)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--leverage", type=int, default=100)
    parser.add_argument("--report", dest="report_name", default="",
                        help="report stem (default: deterministic auto id)")
    parser.add_argument("--input", dest="inputs", action="append", default=[],
                        metavar="KEY=VALUE", help="EA input override (repeatable)")


def config_from_args(args: argparse.Namespace,
                     known: set[str] | None = None) -> TesterConfig:
    inputs = parse_kv_pairs(args.inputs)
    validate_inputs(inputs, known=known)
    cfg = TesterConfig(ea=args.ea, symbol=args.symbol, timeframe=args.timeframe,
                       model=args.model, date_from=args.date_from,
                       date_to=args.date_to, deposit=args.deposit,
                       currency=args.currency, leverage=args.leverage,
                       report_name=args.report_name, inputs=inputs)
    cfg.validate()
    return cfg


# ---------------------------------------------------------------------------
# subcommand bodies
# ---------------------------------------------------------------------------

def cmd_generate_set(args: argparse.Namespace) -> int:
    overrides = parse_kv_pairs(args.inputs)
    base = dict(EA_INPUT_DEFAULTS) if args.defaults else {}
    base.update(overrides)
    validate_inputs(base, known=set(EA_INPUT_DEFAULTS))
    text = render_set(inputs_to_lines(base), header="mql5bot deterministic preset")
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"set written: {args.output}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_generate_ini(args: argparse.Namespace) -> int:
    cfg = config_from_args(args, known=set(EA_INPUT_DEFAULTS))
    text = cfg.render_ini()
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"ini written: {args.output}  (report: {cfg.safe_report_name})")
    else:
        sys.stdout.write(text)
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    symbols = [s for s in args.symbols.split(",") if s.strip()]
    timeframes = [t for t in args.timeframes.split(",") if t.strip()]
    strategies = [int(x) for x in args.strategies.split(",")]
    if not symbols or not timeframes:
        raise ValueError("--symbols and --timeframes need at least one item each")
    if any(s not in MT5_TIMEFRAMES for s in timeframes):
        raise ValueError(f"timeframes must be from {MT5_TIMEFRAMES}")
    jobs = []
    for strategy in strategies:
        for symbol in symbols:
            for timeframe in timeframes:
                jobs.append({"symbol": symbol, "timeframe": timeframe,
                             "inputs": {"InpStrategy": strategy}})
    doc = {"defaults": {"ea": EA, "model": 1, "date_from": args.date_from,
                        "date_to": args.date_to, "deposit": args.deposit,
                        "currency": args.currency, "leverage": args.leverage},
           "jobs": jobs}
    out = Path(args.output)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"jobs written: {out} ({len(jobs)} jobs)")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    text = Path(args.report).read_text(encoding="utf-8", errors="replace")
    data = parse_report_html(text)
    payload = data.to_dict()
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"parsed report written: {args.output}")
    else:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


def _load_jobs(path: str) -> tuple[dict, list[dict]]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), list):
        raise TypeError("jobs file must be {defaults?: {...}, jobs: [...]}")
    return dict(doc.get("defaults", {})), doc["jobs"]


def _job_config(defaults: dict, job: dict) -> TesterConfig:
    merged = dict(defaults)
    merged.update(job)
    inputs = dict(merged.pop("inputs", {}) or {})
    cfg = TesterConfig(inputs=inputs, **merged)
    cfg.validate()
    return cfg


def cmd_run(args: argparse.Namespace) -> int:
    cfg = config_from_args(args)
    settings = RunSettings(terminal_dir=args.terminal_dir,
                           data_folder=args.data_folder,
                           out_dir=args.out_dir, timeout_s=args.timeout)
    outcome = run_backtest(cfg, settings)
    json.dump(outcome.to_dict(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if outcome.ok else 1


def cmd_batch(args: argparse.Namespace) -> int:
    defaults, jobs = _load_jobs(args.jobs)
    configs = [_job_config(defaults, job) for job in jobs]
    settings = RunSettings(terminal_dir=args.terminal_dir,
                           data_folder=args.data_folder,
                           out_dir=args.out_dir, timeout_s=args.timeout)
    outcomes = run_batch(configs, settings)
    json.dump([o.to_dict() for o in outcomes], sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    failed = [o for o in outcomes if not o.ok]
    if failed:
        print(f"FAILED: {len(failed)}/{len(outcomes)} runs — see JSON above",
              file=sys.stderr)
    return 0 if not failed else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_mt5_backtest",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate-set", help="write a .set preset")
    p.add_argument("--defaults", action="store_true",
                   help="start from the EA's full default input set")
    p.add_argument("--input", dest="inputs", action="append", default=[],
                   metavar="KEY=VALUE", help="override (repeatable)")
    p.add_argument("--output", default="", help="file path (default: stdout)")
    p.set_defaults(func=cmd_generate_set)

    p = sub.add_parser("generate-ini", help="write a tester.ini")
    add_config_args(p)
    p.add_argument("--output", default="", help="file path (default: stdout)")
    p.set_defaults(func=cmd_generate_ini)

    p = sub.add_parser("matrix", help="write batch jobs.json")
    p.add_argument("--symbols", default="EURUSD,GBPUSD,XAUUSD")
    p.add_argument("--timeframes", default="H1,H4")
    p.add_argument("--strategies", default="0,1",
                   help="comma-separated InpStrategy enum ints (0..4)")
    p.add_argument("--from", dest="date_from", default="2020.01.01")
    p.add_argument("--to", dest="date_to", default="2024.01.01")
    p.add_argument("--deposit", type=float, default=10000.0)
    p.add_argument("--currency", default="USD")
    p.add_argument("--leverage", type=int, default=100)
    p.add_argument("--output", required=True, help="jobs.json path")
    p.set_defaults(func=cmd_matrix)

    p = sub.add_parser("parse", help="parse an MT5 HTML report")
    p.add_argument("--report", required=True, help="path to the .htm report")
    p.add_argument("--output", default="", help="json path (default: stdout)")
    p.set_defaults(func=cmd_parse)

    for name, help_text in (("run", "headless single run (Windows)"),
                            ("batch", "headless batch (Windows)")):
        p = sub.add_parser(name, help=help_text)
        if name == "run":
            add_config_args(p)
        else:
            p.add_argument("--jobs", required=True, help="jobs.json path")
        p.add_argument("--terminal-dir", required=True,
                       help="folder containing terminal64.exe")
        p.add_argument("--data-folder", required=True,
                       help="MT5 data folder (contains MQL5)")
        p.add_argument("--out-dir", default="results", help="artifacts root")
        p.add_argument("--timeout", type=float, default=3600.0, help="seconds")
        p.set_defaults(func=cmd_run if name == "run" else cmd_batch)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except SystemExit:
        raise
    except RuntimeError as exc:  # platform guard (run/batch off Windows)
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # anything else is a bug: let it traceback rather than guess


if __name__ == "__main__":
    sys.exit(main())
