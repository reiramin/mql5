#!/usr/bin/env python3
"""demo_safety_harness - run one demo safety test with no clicking
(restart / netting / hedging; docs/SAFETY_DEMO_PLAN.md).

    python tools/demo_safety_harness.py run --test restart \\
        --terminal "C:\\Program Files\\MetaTrader 5\\terminal64.exe" \\
        --data-folder "%APPDATA%\\MetaQuotes\\Terminal\\<id>" \\
        [--accounts %USERPROFILE%\\.mql5bot\\demo_accounts.json] \\
        [--out evidence\\demo_safety]

The demo credentials are read from the LOCAL accounts file (default
%USERPROFILE%\\.mql5bot\\demo_accounts.json, or MQL5BOT_DEMO_ACCOUNTS); a
file inside the repository is refused. Close the terminal before a run.
Exit 0 when the run completed its steps (NOT a pass: the stage-8 builder
grades the EA log), 1 on a refused/failed step, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401  pins this repo's python/
from mql5bot import demo_harness as dh


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--test", required=True, choices=dh.TESTS)
    p.add_argument("--terminal", required=True)
    p.add_argument("--data-folder", required=True)
    p.add_argument("--accounts", default="")
    p.add_argument("--out", default="")
    p.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    out = Path(args.out) if args.out else repo / "evidence" / "demo_safety"
    try:
        rec = dh.Harness(test=args.test, terminal=args.terminal,
                         data_folder=args.data_folder,
                         accounts=args.accounts or dh.default_accounts_path(),
                         repo=repo, out_dir=out,
                         timeout_s=args.timeout).run()
    except dh.HarnessError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"ok": rec["error"] is None, **rec}, indent=2))
    return 0 if rec["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
