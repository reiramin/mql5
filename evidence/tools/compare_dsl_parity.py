#!/usr/bin/env python3
"""Exact comparator for the MQL5 DSL parity run (mission §12/§13).

Input: a directory of MQL5 runner outputs (``<fixture>.json`` written by
``mql5/Scripts/Mql5Bot/DslParityRunner.mq5`` in batch mode) and the
committed golden set (``artifacts/dsl_parity/``).

For EVERY fixture pinned in ``manifest.json`` the MQL5 output must match
``expected_trace.json`` EXACTLY — positions, events, n_bars,
position_hash, spec_hash, strategy_id, strategy_version and every
exit_geometry key; logical values carry no tolerance.  The output must
also carry the manifest-pinned provenance (``bundle_hash`` and the
``ohlc_sha256`` of the exact fixture bytes the runner hashed), so a
re-imported or converted frame can never masquerade as the fixture.

The negative fixture ``tampered_bundle/`` (committed OUTSIDE the
manifest) must produce a REFUSAL, not a trace.

Exit code 0 only when ALL manifest fixtures are EXACT (14/14 for the
committed set) AND the tampered fixture was refused.  On the first
divergence of a positions vector the report names the fixture, the bar
index, the expected and the actual value.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "artifacts" / "dsl_parity"

# the trace fields compared field-for-field (positions handled apart
# for the bar-indexed first-divergence report)
_EXACT_FIELDS = ("n_bars", "position_hash", "spec_hash", "strategy_id",
                 "strategy_version", "events")


def compare_fixture(name: str, expected: dict, actual: dict,
                    pins: dict) -> list[str]:
    """Return divergence strings (empty == EXACT) for one fixture."""
    if actual.get("refused"):
        return [(f"{name}: REFUSED by the runner: "
                 f"{actual.get('error', '?')!r} (a manifest fixture must "
                 "produce a trace)")]

    diffs: list[str] = []

    # provenance binding: the runner must have consumed the EXACT
    # committed bytes and the EXACT committed bundle
    pin_bundle = pins.get("bundle_hash")
    if actual.get("bundle_hash") != pin_bundle:
        diffs.append(f"{name}: bundle_hash {actual.get('bundle_hash')!r}"
                     f" != manifest pin {pin_bundle!r}")
    pin_ohlc = (pins.get("files") or {}).get("ohlc.csv")
    if actual.get("ohlc_sha256") != pin_ohlc:
        diffs.append(f"{name}: ohlc_sha256 {actual.get('ohlc_sha256')!r}"
                     f" != manifest pin {pin_ohlc!r} (the runner did not"
                     " hash the committed fixture bytes)")

    exp_pos = expected["positions"]
    act_pos = actual.get("positions")
    if not isinstance(act_pos, list):
        diffs.append(f"{name}: output has no positions vector")
        return diffs
    if len(act_pos) != len(exp_pos):
        diffs.append(f"{name}: positions length {len(act_pos)} != "
                     f"expected {len(exp_pos)}")
    else:
        for bar, (e, a) in enumerate(zip(exp_pos, act_pos)):
            if e != a:
                diffs.append(f"{name}: first divergence at bar {bar}: "
                             f"expected {e}, actual {a}")
                break

    for field in _EXACT_FIELDS:
        if actual.get(field) != expected.get(field):
            diffs.append(f"{name}: {field} mismatch: expected "
                         f"{expected.get(field)!r}, actual "
                         f"{actual.get(field)!r}")

    eg_exp = expected.get("exit_geometry") or {}
    eg_act = actual.get("exit_geometry") or {}
    for key in sorted(set(eg_exp) | set(eg_act)):
        e, a = eg_exp.get(key, "<absent>"), eg_act.get(key, "<absent>")
        if e != a:
            diffs.append(f"{name}: exit_geometry.{key}: expected {e!r},"
                         f" actual {a!r}")
    return diffs


def compare_dir(out_dir: Path, fixtures_dir: Path) -> tuple[bool, list[str]]:
    """Compare every manifest fixture + the tampered negative.

    Returns (ok, report_lines)."""
    lines: list[str] = []
    ok = True
    manifest = json.loads((fixtures_dir / "manifest.json").read_text())
    names = sorted(manifest["fixtures"])
    exact = 0
    for name in names:
        out_path = out_dir / f"{name}.json"
        if not out_path.exists():
            ok = False
            lines.append(f"FAIL  {name}: missing runner output "
                         f"{out_path}")
            continue
        expected = json.loads(
            (fixtures_dir / name / "expected_trace.json").read_text())
        actual = json.loads(out_path.read_text())
        diffs = compare_fixture(name, expected, actual,
                                manifest["fixtures"][name])
        if diffs:
            ok = False
            for d in diffs:
                lines.append(f"FAIL  {d}")
        else:
            exact += 1
            lines.append(f"EXACT {name}")

    # negative fixture: a tampered bundle_hash MUST have been refused
    tampered = fixtures_dir / "tampered_bundle" / "bundle.json"
    if tampered.exists():
        t_out = out_dir / "tampered_bundle.json"
        if not t_out.exists():
            ok = False
            lines.append("FAIL  tampered_bundle: no runner output — the "
                         "tamper check did not run")
        else:
            t = json.loads(t_out.read_text())
            if t.get("refused") is not True:
                ok = False
                lines.append("FAIL  tampered_bundle: runner produced a "
                             "trace for a tampered bundle (bundle_hash "
                             "verification is broken)")
            elif "bundle_hash mismatch" not in str(t.get("error", "")):
                ok = False
                lines.append("FAIL  tampered_bundle: refused for the "
                             f"wrong reason: {t.get('error')!r}")
            else:
                lines.append("EXACT tampered_bundle (refused: "
                             "bundle_hash mismatch)")

    lines.append(f"{exact}/{len(names)} fixtures EXACT"
                 + ("" if ok else " — PARITY NOT PROVEN"))
    return ok, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", type=Path,
                    help="directory of MQL5 runner outputs "
                         "(<fixture>.json)")
    ap.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES,
                    help="golden fixture root (default: "
                         "artifacts/dsl_parity)")
    args = ap.parse_args(argv)
    ok, lines = compare_dir(args.out_dir, args.fixtures)
    for line in lines:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
