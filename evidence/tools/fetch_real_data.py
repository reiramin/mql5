"""tools/fetch_real_data.py — fetch the REAL historical market data used
by the Meta Layer empirical validation (empirical-gate mission).

Egress from this sandbox is allowlisted to github.com, so market-data
providers (Stooq/Yahoo/brokers) are unreachable.  The obtainable REAL
daily OHLC series is the CBOE VIX index daily file mirrored by the
DataHub `datasets/finance-vix` GitHub repository (CBOE-derived, updated
continuously).  Everything else in the suggested basket (EURUSD,
GBPUSD, USDJPY, XAUUSD, an index CFD, a crypto instrument) is marked
UNAVAILABLE IN SANDBOX — the owner runs tools/meta_real_validation.py
with broker-exported CSVs on a normal machine instead; no data is
fabricated here.

Usage:
    gh auth must be active, then:
    python tools/fetch_real_data.py [--out tests/data/real]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# dataset id -> (github repo, path in repo, canonical csv name, note)
SOURCES = {
    "vix_daily": ("datasets/finance-vix", "data/vix-daily.csv",
                  "vix_daily.csv",
                  "CBOE VIX daily OHLC, real, 1990-01-02 .. present"),
}
UNAVAILABLE = {
    "EURUSD": "market-data provider unreachable (sandbox egress "
              "allowlist: github.com only)",
    "GBPUSD": "market-data provider unreachable (sandbox egress)",
    "USDJPY": "market-data provider unreachable (sandbox egress)",
    "XAUUSD": "market-data provider unreachable (sandbox egress)",
    "INDEX_CFD": "market-data provider unreachable (sandbox egress)",
    "CRYPTO": "market-data provider unreachable (sandbox egress)",
}


def fetch(repo: str, path: str) -> bytes:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/{path}", "--jq", ".content"],
        capture_output=True, text=True, check=True)
    import base64
    return base64.b64decode(out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/data/real")
    args = ap.parse_args()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"sources": {}, "unavailable": UNAVAILABLE}
    for key, (repo, path, name, note) in SOURCES.items():
        blob = fetch(repo, path)
        (outdir / name).write_bytes(blob)
        digest = hashlib.sha256(blob).hexdigest()
        manifest["sources"][key] = {
            "file": name, "sha256": digest, "repo": repo, "path": path,
            "note": note}
        print(f"fetched {key}: {name} {len(blob)} bytes sha256={digest[:16]}")
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"manifest: {outdir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
