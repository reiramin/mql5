#!/usr/bin/env python3
"""tools/preview_gold2_regen.py — PREVIEW of a gold-2 regeneration.

``artifacts/gold_2`` is FROZEN and is never touched. This tool runs the
real gold-2 builder (``tools/build_gold2_standard.py``) with the CURRENT
engine — which now applies ``engine.FLIP_RULE_ENTER_NEXT_BAR`` ("close
opposite (signal_exit); enter next bar", the manifest flip_rule the owner
ruled binding on 2026-10-03) — into ``evidence/preview/`` (gitignored),
then diffs the preview ``python_trace`` against the frozen one:

* how many trades are UNCHANGED (same side, same entry minute);
* how many MOVED +1 bar (same side, entry one M1 minute later — the flip
  deferral's direct signature);
* which frozen trades VANISH and which preview trades APPEAR (knock-on
  effects: once one entry moves, exits/equity/sizing move downstream).

The preview refuses to speak unless the builder's fixture is byte-equal
to the frozen fixture: a diff against a different tape would be noise.

Output: ``evidence/preview/gold_2_regen/`` (full builder output:
python_trace.json, expected_execution.json, manifest, fixture) and
``evidence/preview/regen_diff_summary.json``; the summary is printed.

This is INPUT for the owner's later regeneration decision — nothing here
is evidence, a regeneration, or a pass of anything.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FROZEN_DIR = REPO / "artifacts" / "gold_2"
PREVIEW_ROOT = REPO / "evidence" / "preview"
PREVIEW_DIR = PREVIEW_ROOT / "gold_2_regen"
SUMMARY = PREVIEW_ROOT / "regen_diff_summary.json"
BUILDER = REPO / "tools" / "build_gold2_standard.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trades(path: Path) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["trades"]


def _plus_one_minute(stamp: str) -> str:
    return (datetime.fromisoformat(stamp) + timedelta(minutes=1)).isoformat()


def _key(t: dict) -> tuple[str, str]:
    # a trade's identity for the diff: entry minute + side
    return (str(t["signal_time"]), str(t["side"]))


def diff_traces(frozen: list[dict], preview: list[dict]) -> dict:
    """Match frozen trades to preview trades: exact entry minute first,
    then entry minute + 1 (the flip-deferral move). Each preview trade is
    consumed at most once; leftovers are vanished/appeared."""
    pool: dict[tuple[str, str], list[int]] = {}
    for i, t in enumerate(preview):
        pool.setdefault(_key(t), []).append(i)

    def take(key: tuple[str, str]) -> int | None:
        lst = pool.get(key)
        return lst.pop(0) if lst else None

    unchanged, moved, vanished = [], [], []
    lots_changed = exit_changed = 0
    for t in frozen:
        key = _key(t)
        hit = take(key)
        row = None
        if hit is not None:
            row = {"entry": key[0], "side": key[1]}
            unchanged.append(row)
        else:
            hit = take((_plus_one_minute(key[0]), key[1]))
            if hit is not None:
                row = {"frozen_entry": key[0],
                       "preview_entry": _plus_one_minute(key[0]),
                       "side": key[1]}
                moved.append(row)
        if row is not None:
            p = preview[hit]
            if p.get("lots") != t.get("lots"):
                lots_changed += 1
                row["lots"] = {"frozen": t.get("lots"),
                               "preview": p.get("lots")}
            if p.get("exit_reason") != t.get("exit_reason"):
                exit_changed += 1
                row["exit_reason"] = {"frozen": t.get("exit_reason"),
                                      "preview": p.get("exit_reason")}
            continue
        vanished.append({"entry": key[0], "side": key[1],
                         "exit_reason": t.get("exit_reason"),
                         "lots": t.get("lots")})
    appeared = [{"entry": preview[i]["signal_time"],
                 "side": preview[i]["side"],
                 "exit_reason": preview[i].get("exit_reason"),
                 "lots": preview[i].get("lots")}
                for idxs in pool.values() for i in idxs]
    appeared.sort(key=lambda r: str(r["entry"]))
    return {"frozen_trades": len(frozen), "preview_trades": len(preview),
            "unchanged": len(unchanged), "moved_plus_one_bar": len(moved),
            "matched_with_lots_changed": lots_changed,
            "matched_with_exit_reason_changed": exit_changed,
            "vanished": vanished, "appeared": appeared,
            "moved": moved}


def main() -> int:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        [sys.executable, str(BUILDER), "--out", str(PREVIEW_DIR)],
        capture_output=True, text=True, check=False)
    if cp.returncode != 0:
        print("builder failed:", cp.stderr.strip() or cp.stdout.strip())
        return 1

    frozen_fix = FROZEN_DIR / "gold2_fixture.csv"
    preview_fix = PREVIEW_DIR / "gold2_fixture.csv"
    if _sha(frozen_fix) != _sha(preview_fix):
        print("REFUSED: the builder's fixture is not byte-equal to the "
              "frozen fixture — the diff below would compare different "
              "tapes.\n  frozen  sha256", _sha(frozen_fix),
              "\n  preview sha256", _sha(preview_fix))
        return 2

    frozen = _trades(FROZEN_DIR / "python_trace.json")
    preview = _trades(PREVIEW_DIR / "python_trace.json")
    diff = diff_traces(frozen, preview)
    diff["fixture_sha256"] = _sha(frozen_fix)
    diff["frozen_trace"] = str(FROZEN_DIR / "python_trace.json")
    diff["preview_dir"] = str(PREVIEW_DIR)
    diff["note"] = ("PREVIEW ONLY: input for the owner's regeneration "
                    "decision. artifacts/gold_2 is frozen and untouched. "
                    "Built, unit-tested, never run live.")
    SUMMARY.write_text(json.dumps(diff, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")

    print(f"fixture byte-equal to frozen: yes ({diff['fixture_sha256'][:12]}…)")
    print(f"frozen trades:  {diff['frozen_trades']}")
    print(f"preview trades: {diff['preview_trades']}")
    print(f"unchanged (same entry minute + side): {diff['unchanged']}")
    print(f"moved +1 bar (flip deferral):         {diff['moved_plus_one_bar']}")
    print(f"matched trades with changed lots:        "
          f"{diff['matched_with_lots_changed']}")
    print(f"matched trades with changed exit_reason: "
          f"{diff['matched_with_exit_reason_changed']}")
    print(f"vanished: {len(diff['vanished'])}")
    for row in diff["vanished"]:
        print(f"  - {row['entry']} {row['side']} "
              f"(lots {row['lots']}, exit {row['exit_reason']})")
    print(f"appeared: {len(diff['appeared'])}")
    for row in diff["appeared"]:
        print(f"  + {row['entry']} {row['side']} "
              f"(lots {row['lots']}, exit {row['exit_reason']})")
    print(f"summary: {SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
