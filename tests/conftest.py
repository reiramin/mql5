"""Suite-wide setup. Windows newline emulation (tests/windows_newlines.py)
is installed only when MQL5BOT_EMULATE_WINDOWS_NEWLINES=1."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import windows_newlines

if windows_newlines.enabled():
    windows_newlines.install()
    os.environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (windows_newlines.SITE_DIR,
                    os.environ.get("PYTHONPATH", "")) if p)
