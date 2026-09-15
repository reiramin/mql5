#!/usr/bin/env python3
"""certify_strategy.py — run the Phase-F real-tick certification protocol.

Tooling for the certification legs of the canonical TEN-step owner
sequence in docs/MT5_ROUNDTRIP.md (the single source of truth for the
owner protocol): it drives the tester legs and the Python↔MT5
comparison (canonical steps 5–8) and produces the certification-state
assignment (canonical step 10).  It can only ASSIGN a state from
evidence that the earlier steps actually produced; it never upgrades a
state on its own, and without a Windows terminal host it reports every
tester leg as not run and the verdict NOT VERIFIED with the reason.

Usage:
    python tools/certify_strategy.py --config config.json [--out report.md]

``config.json`` mirrors :class:`mql5bot.certify.CertifyConfig` (see
docs/CERTIFICATION.md).  The MT5 tester legs require a Windows terminal
host (mt5tester); without one this tool reports every tester leg as not
run and the verdict is NOT VERIFIED with the reason — a VERIFIED stamp
is never fabricated.  The optional python M1-OHLC cross-check leg runs
when ``--data parquet-or-csv`` points at OHLC data.

Exit code: 0 when the verdict is VERIFIED, 1 otherwise (including every
NOT VERIFIED case and configuration errors).
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from mql5bot.certify import (
    VERIFIED,
    CertifyConfig,
    render_report,
    run_certification,
)


def _load_config(path: str) -> CertifyConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    names = {f.name for f in fields(CertifyConfig)}
    kwargs = {k: v for k, v in raw.items() if k in names}
    unknown = sorted(set(raw) - names)
    if unknown:
        raise ValueError(f"unknown config keys: {unknown}")
    return CertifyConfig(**kwargs)


def _python_runner(cfg: CertifyConfig):
    """Wire the real headless-tester runner when on a terminal host."""
    from mql5bot.mt5tester import RunSettings

    if platform.system() != "Windows":
        note = ("MT5 terminal runner requires Windows (this host: "
                f"{platform.system()})")
        return None, note
    settings = RunSettings(
        terminal_dir=cfg.ea_inputs.get("terminal_dir"),
        data_folder=cfg.ea_inputs.get("data_folder"),
        out_dir=cfg.ea_inputs.get("out_dir", "results"))
    from mql5bot.mt5tester import run_backtest

    return (lambda tc: run_backtest(tc, settings)), \
        "headless MT5 tester via mt5tester.run_backtest"


def _reconciliation_ok(path: str) -> bool:
    """Fail-closed check of a reconciliation artifact (canonical step 8).

    The artifact must exist, parse as JSON, and carry a non-empty field
    comparison — otherwise the evidence is incomplete and a VERIFIED
    verdict stays withheld.  A PENDING_OWNER field is legitimate owner
    work-in-progress, but an EMPTY reconciliation is not evidence.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    fields = doc.get("fields")
    trades = doc.get("trades")
    return bool(fields) or bool(trades)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="JSON CertifyConfig")
    ap.add_argument("--out", default="", help="write the markdown report here")
    ap.add_argument("--data", default="", help="OHLC csv/parquet for the "
                                               "python cross-check leg")
    ap.add_argument("--reconciliation", default="",
                    help="path to the recorded Python<->MT5 reconciliation "
                         "artifact (canonical step 8). Without a valid "
                         "artifact a VERIFIED verdict is withheld — an "
                         "empirical ladder pass alone is not a "
                         "certification.")
    args = ap.parse_args(argv)

    cfg = _load_config(args.config)
    data = None
    if args.data:
        import pandas as pd

        data = (pd.read_parquet(args.data)
                if args.data.endswith(".parquet")
                else pd.read_csv(args.data, index_col=0, parse_dates=True))
    runner, note = _python_runner(cfg)
    reconciliation_ok = (_reconciliation_ok(args.reconciliation)
                         if args.reconciliation else None)
    report = run_certification(cfg, run_tester=runner, python_data=data,
                               runner_note=note,
                               reconciliation_ok=reconciliation_ok)
    text = render_report(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    status = report["verdict"]["status"]
    print(f"\n[exit] verdict: {status}", file=sys.stderr)
    return 0 if status == VERIFIED else 1


if __name__ == "__main__":
    raise SystemExit(main())
