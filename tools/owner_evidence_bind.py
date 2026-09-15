#!/usr/bin/env python3
"""owner_evidence_bind — compute evidence bindings for the owner.

The owner NEVER hand-types a hash.  This tool computes the
cryptographic bindings the verifier requires:

  bind <file> [--root <evidence-dir>]
      Print the {"path", "sha256"} binding object for one evidence
      file (real-tick journal, safety artifact, ...).  `path` is
      relative to the evidence root and must stay inside it.

  manifest <evidence-dir> [--frozen <frozen_inputs.json>]
      Build the complete archive_manifest.json: SHA-256 of EVERY file
      in the evidence directory plus the frozen source/fixture
      identities.  Run this LAST, after every other artifact exists.

Both commands only READ and PRINT — they never generate evidence and
never touch MT5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cmd_bind(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    path = Path(args.file).resolve()
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    try:
        rel = path.relative_to(root)
    except ValueError:
        print("error: file is outside the evidence root — evidence must "
              "live inside the package", file=sys.stderr)
        return 2
    print(json.dumps({"path": str(rel).replace("\\", "/"),
                      "sha256": sha256_file(path)}, indent=2))
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    root = Path(args.evidence_dir).resolve()
    if not root.is_dir():
        print(f"error: evidence dir not found: {root}", file=sys.stderr)
        return 2
    artifacts = {}
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.name != "archive_manifest.json":
            artifacts[str(f.relative_to(root)).replace("\\", "/")] = \
                sha256_file(f)
    identity: dict = {}
    if args.frozen:
        try:
            frozen = json.loads(Path(args.frozen).read_text(
                encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"error: cannot read frozen inputs: {exc}",
                  file=sys.stderr)
            return 2
        identity = {
            "source_commit": frozen.get("source", {}).get("commit", ""),
            "gold1_fixture_sha256":
                frozen.get("gold_1", {}).get("fixture_sha256", ""),
            "gold2_fixture_sha256":
                frozen.get("gold_2", {}).get("fixture_sha256", ""),
        }
    print(json.dumps({"artifacts": artifacts, "identity": identity},
                     indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bind", help="print one file binding")
    b.add_argument("file")
    b.add_argument("--root", default=".",
                   help="evidence root (default: cwd)")
    m = sub.add_parser("manifest", help="build archive_manifest.json")
    m.add_argument("evidence_dir")
    m.add_argument("--frozen",
                   default="artifacts/owner_mt5_gate/frozen_inputs.json")
    args = ap.parse_args(argv)
    if args.cmd == "bind":
        return cmd_bind(args)
    return cmd_manifest(args)


if __name__ == "__main__":
    raise SystemExit(main())
