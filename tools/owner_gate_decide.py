#!/usr/bin/env python3
"""owner_gate_decide - the decision CLI tools/owner_gate.ps1 shells to.

The gate is ONE command for the Windows owner; the DECISIONS live in
committed, Mac-tested Python (mql5bot.gate_selfcheck), not in the .ps1 and
not in a prompt. This wrapper exposes one subcommand per decision, prints a
machine-readable JSON verdict on stdout, and returns:

    0  the check PASSED
    1  the check FAILED (fail-closed; the .ps1 stops the gate)
    2  usage / unreadable-input error

It never writes frozen_inputs.json or the certification manifest, never
edits gold artifacts, never fabricates MT5/tester/broker evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from mql5bot import gate_selfcheck as gs


def _emit(payload: dict) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


def _read_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="repository root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("self-protection",
                   help="stage A: HEAD/clean/autocrlf/frozen/dsl binding")

    p = sub.add_parser("parse-compile", help="stage 1: parse strict log")
    p.add_argument("log", help="path to the strict compile log")

    p = sub.add_parser("parse-dsl", help="stage 2: parse compare report")
    p.add_argument("report", help="path to compare_report.txt")

    p = sub.add_parser("broker-scope", help="stage 3: parity scope rule")
    p.add_argument("report", help="path to parity_report.json")

    p = sub.add_parser("dataset-hash", help="stage 4: sha256 of a fixture")
    p.add_argument("csv", help="path to the fixture CSV")

    p = sub.add_parser("classify", help="mismatch class of a field")
    p.add_argument("field")

    p = sub.add_parser("clone-preflight",
                       help="refuse by name if a fresh-clone target exists")
    p.add_argument("dir", help="the intended clone/working-copy directory")

    p = sub.add_parser("import-diagnostic",
                       help="stage 4: importer result must be non-vacuous")
    p.add_argument("result", help="path to the importer <symbol>.json")

    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()

    try:
        if args.cmd == "self-protection":
            return _emit(gs.run_self_protection(repo))

        if args.cmd == "parse-compile":
            text = gs.decode_bom_aware(_read_bytes(args.log))
            targets = gs.expected_compile_targets(repo)
            return _emit(gs.parse_compile_log(text, targets))

        if args.cmd == "parse-dsl":
            text = gs.decode_bom_aware(_read_bytes(args.report))
            return _emit(gs.parse_dsl_compare_report(text))

        if args.cmd == "broker-scope":
            report = json.loads(Path(args.report).read_text(encoding="utf-8"))
            return _emit(gs.broker_parity_scope(report))

        if args.cmd == "dataset-hash":
            digest = gs.dataset_hash_of_csv(args.csv)
            print(json.dumps({"ok": True, "sha256": digest,
                              "path": args.csv}, indent=2, sort_keys=True))
            return 0

        if args.cmd == "classify":
            print(json.dumps({"ok": True, "field": args.field,
                              "classification": gs.classify_field(args.field)},
                             indent=2, sort_keys=True))
            return 0

        if args.cmd == "clone-preflight":
            return _emit(gs.clone_target_status(args.dir))

        if args.cmd == "import-diagnostic":
            doc = json.loads(Path(args.result).read_text(encoding="utf-8"))
            verdict = gs.import_diagnostic_populated(doc)
            # "ok" tracks whether the diagnostic is usable (populated), NOT the
            # stage pass/fail -- the .ps1 decides pass/fail from refused/hash
            # and uses this only to surface a human reason and fail closed on a
            # regression to a vacuous refusal.
            print(json.dumps({"ok": verdict["populated"], **verdict},
                             indent=2, sort_keys=True))
            return 0 if verdict["populated"] else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
