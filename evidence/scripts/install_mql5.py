#!/usr/bin/env python3
"""Install the mql5bot Expert Advisor into a MetaTrader 5 data folder.

Finds the terminal data folder automatically (Windows, macOS, or Wine
prefixes on Linux), then copies:

    mql5/Include/Mql5Bot/*      -> <data>/MQL5/Include/Mql5Bot/
    mql5/Experts/Mql5Bot/*.mq5  -> <data>/MQL5/Experts/Mql5Bot/
    mql5/Scripts/Mql5Bot/*.mq5  -> <data>/MQL5/Scripts/Mql5Bot/
    mql5/Presets/Mql5Bot/*.set  -> <data>/MQL5/Presets/Mql5Bot/

After installing, compile the files in MetaEditor (F7) and attach the EA
to a chart. Usage:

    python scripts/install_mql5.py                 # auto-detect data folder
    python scripts/install_mql5.py --folder "C:/path/to/Terminal/ABCDEF"
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def candidate_data_folders() -> list[Path]:
    """Candidate MT5 data folders per platform."""
    candidates: list[Path] = []
    home = Path.home()

    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates.append(appdata / "MetaQuotes" / "Terminal")
    elif sys.platform == "darwin":
        candidates.append(
            home / "Library" / "Application Support" / "MetaQuotes" / "Terminal"
        )
    else:
        # Linux — commonly MT5 runs under Wine with a Windows-like layout
        for wine_prefix in (home / ".wine" / "drive_c", home / ".local" / "share" / "wineprefixes"):
            appdata = wine_prefix / "users" / os.environ.get("USER", "user") / "AppData" / "Roaming"
            candidates.append(appdata / "MetaQuotes" / "Terminal")
            # flatprefix variants
            candidates.append(wine_prefix / "users" / "*" / "AppData" / "Roaming" / "MetaQuotes" / "Terminal")

    return [c for c in candidates if c.exists()]


def detect_data_folder() -> Path | None:
    """Return the most recently modified Terminal/<hash> data folder."""
    best: Path | None = None
    best_mtime = 0.0
    for base in candidate_data_folders():
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "MQL5").exists():
                try:
                    mtime = (child / "MQL5").stat().st_mtime
                except OSError:
                    mtime = 0.0
                if mtime >= best_mtime:
                    best, best_mtime = child, mtime
    return best


def install(data_folder: Path, *, force: bool = False) -> int:
    mappings = {
        REPO_ROOT / "mql5" / "Include" / "Mql5Bot": data_folder / "MQL5" / "Include" / "Mql5Bot",
        REPO_ROOT / "mql5" / "Experts" / "Mql5Bot": data_folder / "MQL5" / "Experts" / "Mql5Bot",
        REPO_ROOT / "mql5" / "Scripts" / "Mql5Bot": data_folder / "MQL5" / "Scripts" / "Mql5Bot",
        REPO_ROOT / "mql5" / "Presets" / "Mql5Bot": data_folder / "MQL5" / "Presets" / "Mql5Bot",
    }
    count = 0
    for src, dst in mappings.items():
        if not src.exists():
            print(f"skip {src.name} (not present)")
            continue
        if dst.exists() and not force:
            print(f"skip {src.name} (already installed — use --force to overwrite)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        count += 1
        print(f"installed {src.relative_to(REPO_ROOT)} -> {dst}")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", default=None,
                        help="MT5 data folder (auto-detected when omitted)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files")
    args = parser.parse_args(argv)

    folder = Path(args.folder) if args.folder else detect_data_folder()
    if folder is None:
        print(
            "error: could not find a MetaTrader 5 data folder.\n"
            "Open MT5 -> File -> Open Data Folder, then pass --folder <path>.",
            file=sys.stderr,
        )
        return 1
    print(f"MT5 data folder: {folder}")
    if not (folder / "MQL5").exists():
        print(f"error: {folder} does not look like an MT5 data folder (no MQL5 dir)",
              file=sys.stderr)
        return 1
    n = install(folder, force=args.force)
    print(f"\ndone — {n} components installed. Compile in MetaEditor, then attach "
          f"the EA to a chart. Presets are available in the EA's Inputs tab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
