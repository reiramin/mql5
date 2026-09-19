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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # pins this repo's python/ ahead of any installed mql5bot
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

    sub.add_parser("provenance",
                   help="stage 0: resolve mql5bot and assert it is THIS repo's "
                        "copy (fail-closed) + record its file path and version, "
                        "so the evidence names the code that produced the verdict")

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

    p = sub.add_parser("validate-preset",
                       help="stage 4: the STAGED .set must carry exactly the "
                            "intended key=value pairs (validated BEFORE the "
                            "terminal is launched; fail-closed)")
    p.add_argument("preset", help="path to the staged .set in MQL5\\Presets")
    p.add_argument("--expect", action="append", default=[],
                   metavar="KEY=VALUE",
                   help="one intended key=value pair (repeat per input)")

    p = sub.add_parser("tester-inputs",
                       help="stage 5: derive the tester timeframe + period "
                            "from the manifest + fixture; fail-closed naming "
                            "any input the gate cannot derive (never guessed)")
    p.add_argument("--manifest", required=True, help="path to the gold manifest.json")
    p.add_argument("--fixture", required=True, help="path to the gold fixture CSV")

    p = sub.add_parser("stage5-leg",
                       help="stage 5: read the ACTUAL model + real-tick "
                            "coverage a tester leg achieved from its report "
                            "sidecar + journal (never the requested model)")
    p.add_argument("--report-json", required=True,
                   help="path to the leg's parsed report.json sidecar")
    p.add_argument("--journal", default="",
                   help="path to the leg's tester-journal excerpt, if any")
    p.add_argument("--requested-model", required=True, type=int,
                   help="the model the gate requested (0..4)")
    p.add_argument("--symbol", default="", help="the custom symbol under test")
    p.add_argument("--leg", default="", help="a label for this leg")

    p = sub.add_parser("stage5-leg-outcome",
                       help="stage 5: classify a tester leg that produced no "
                            "report — BLOCKED_OWNER_ENVIRONMENT (proven clean "
                            "run, only the report missing), FAIL_INSUFFICIENT_"
                            "FIXTURE_HISTORY (0 bars), or FAIL — from the "
                            "leg's OWN window capture only (R6: never a "
                            "day-wide log dump)")
    p.add_argument("--window", required=True,
                   help="path to THIS leg's window capture: the lines "
                        "appended to the tester logs while this leg ran")
    p.add_argument("--report-present", default="false",
                   help="true|false: did the leg produce a usable report")
    p.add_argument("--symbol", required=True,
                   help="the custom symbol under test; symbol-bearing log "
                        "lines count only when they name it")
    p.add_argument("--leg", default="", help="a label for this leg")

    p = sub.add_parser("stage4-outcome",
                       help="stage 4: decide the three-way import outcome "
                            "(never-launched / ran-no-json / refused)")
    p.add_argument("--symbol", required=True)
    p.add_argument("--launched", required=True,
                   help="true|false: did the terminal process start")
    p.add_argument("--result", default="",
                   help="path the gate told the importer to write (may be "
                        "absent if the importer never wrote it)")
    p.add_argument("--manifest-hash", default="",
                   help="the manifest dataset_hash to match on success")
    p.add_argument("--log-excerpt", default="",
                   help="path to a saved terminal-log excerpt, if any")

    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()

    try:
        if args.cmd == "provenance":
            # Resolve mql5bot the SAME way every tool does (via _bootstrap) and
            # assert it is this repo's copy; the JSON (recorded as evidence)
            # names both the repo root and where mql5bot actually came from.
            prov = _bootstrap.mql5bot_provenance()
            print(json.dumps(prov, indent=2, sort_keys=True))
            return 0 if prov["ok"] else 1

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

        if args.cmd == "validate-preset":
            text = gs.decode_bom_aware(_read_bytes(args.preset))
            expected: dict[str, str] = {}
            for pair in args.expect:
                key, _, val = pair.partition("=")
                expected[key] = val
            verdict = gs.validate_preset(text, expected)
            return _emit({**verdict, "preset": args.preset})

        if args.cmd == "tester-inputs":
            return _emit(gs.derive_tester_inputs(args.manifest, args.fixture))

        if args.cmd == "stage5-leg":
            verdict = gs.tester_leg_evidence(
                args.report_json, args.journal or None,
                args.requested_model, symbol=args.symbol or None,
                leg=args.leg or None)
            print(json.dumps({**verdict}, indent=2, sort_keys=True))
            return 0 if verdict["ok"] else 1

        if args.cmd == "stage5-leg-outcome":
            # R6: the ONLY text a leg may be judged by is its own window
            # capture — never a day-wide journal dump or a multi-leg tail.
            window = ""
            if args.window and Path(args.window).is_file():
                window = gs.decode_bom_aware(_read_bytes(args.window))
            report_present = str(args.report_present).strip().lower() in (
                "true", "1", "yes")
            verdict = gs.classify_tester_leg_outcome(
                report_present=report_present,
                window_text=window,
                symbol=args.symbol or None, leg=args.leg or None)
            print(json.dumps({"ok": verdict["ok"], **verdict},
                             indent=2, sort_keys=True))
            return 0 if verdict["ok"] else 1

        if args.cmd == "stage4-outcome":
            launched = str(args.launched).strip().lower() in ("true", "1", "yes")
            doc = None
            json_present = False
            if args.result and Path(args.result).is_file():
                try:
                    doc = json.loads(Path(args.result).read_text(encoding="utf-8"))
                    json_present = True
                except ValueError:
                    # a file that will not parse is NOT a usable JSON output
                    json_present = False
            log_present = bool(args.log_excerpt) and Path(args.log_excerpt).is_file()
            # fold the excerpt's first lines into the decision message so a
            # stage-4 failure is diagnosable from the gate console alone
            log_head = None
            if log_present:
                try:
                    raw = _read_bytes(args.log_excerpt)
                    log_head = "\n".join(
                        gs.decode_bom_aware(raw).splitlines()[:10]) or None
                except OSError:
                    log_head = None
            verdict = gs.classify_stage4_outcome(
                launched=launched, json_present=json_present, doc=doc,
                manifest_hash=(args.manifest_hash or None), symbol=args.symbol,
                log_excerpt_present=log_present,
                log_excerpt_head=log_head)
            print(json.dumps({"ok": verdict["ok"], **verdict},
                             indent=2, sort_keys=True))
            return 0 if verdict["ok"] else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
