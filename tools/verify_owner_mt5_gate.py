#!/usr/bin/env python3
"""verify_owner_mt5_gate — consume an owner MT5 evidence directory.

FINAL REALITY GATE §32/§34: the single command that mechanically
verifies owner-produced evidence — completeness, freshness, identity
binding, tester-model identity, real-tick coverage, gold
reconciliation, first divergence, mismatch classification, safety
runtime evidence — and assigns the truthful certification verdict.

Usage:
    python tools/verify_owner_mt5_gate.py <evidence-dir> \\
        [--frozen artifacts/owner_mt5_gate/frozen_inputs.json] \\
        [--out report.json]

Exit codes:
    0  verdict is a positive one (MT5_VALIDATED or a later layer)
    1  any NOT_VERIFIED_* verdict (missing/stale/wrong/partial evidence)
    2  usage/configuration error

This tool only CONSUMES owner evidence; it can never manufacture it.
A package that fails verification stays exactly as failed as it is.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from mql5bot import owner_gate as og


def _symbolspec_expectations(repo: Path) -> dict:
    """Frozen deterministic broker-spec expectations (Gold #1 manifest)."""
    man = repo / "artifacts" / "gold" / "manifest.json"
    if not man.is_file():
        return {}
    try:
        doc = json.loads(man.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    spec = doc.get("broker_spec")
    return spec if isinstance(spec, dict) else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("evidence_dir",
                    help="owner evidence directory (contract: "
                         "artifacts/owner_mt5_gate/README.md)")
    ap.add_argument("--frozen",
                    default="artifacts/owner_mt5_gate/frozen_inputs.json",
                    help="frozen-inputs record (default: repo package)")
    ap.add_argument("--repo", default=".",
                    help="repository root (default: cwd)")
    ap.add_argument("--out", default="",
                    help="write the machine-readable report here")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    frozen_path = Path(args.frozen)
    if not frozen_path.is_absolute():
        frozen_path = repo / frozen_path
    try:
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read frozen inputs: {exc}", file=sys.stderr)
        return 2

    # bind the frozen broker-spec expectations for SymbolSpec comparison
    frozen.setdefault("symbolspec_expectations",
                      _symbolspec_expectations(repo))

    report = og.run_gate(Path(args.evidence_dir), frozen)
    report["frozen_source_commit"] = frozen.get("source", {}).get(
        "commit", "")
    report["verifier"] = "mql5bot.owner_gate"
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"report written: {args.out}")
    else:
        print(text)

    verdict = report["verdict"]
    print(f"\n[verdict] {verdict}", file=sys.stderr)
    for reason in report.get("reasons", []):
        print(f"  - {reason}", file=sys.stderr)
    return 0 if verdict in og.POSITIVE_VERDICTS else 1


if __name__ == "__main__":
    raise SystemExit(main())
