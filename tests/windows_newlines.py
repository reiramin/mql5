"""Emulate Windows text-mode newline translation on any OS.

On Windows, a file opened in text mode without ``newline=""`` writes every
"\\n" as "\\r\\n" (and ``pandas.DataFrame.to_csv`` defaults its line
terminator to ``os.linesep``). Bytes that are hashed or compared then
differ from the POSIX bytes. CPython fixes the Windows separator at
compile time, but the pure-Python ``_pyio`` implementation reads
``os.linesep`` at open time. ``install()`` therefore sets
``os.linesep = "\\r\\n"`` and routes ``open``/``io.open`` (which
``pathlib`` uses) through ``_pyio.open``, so the POSIX CI reproduces the
Windows behaviour (reports/windows_pytest/failures.txt, gate-reports).

Enabled for a whole pytest run with ``MQL5BOT_EMULATE_WINDOWS_NEWLINES=1``
(tests/conftest.py); subprocesses inherit it through the
``_windows_newlines_site`` sitecustomize. Test-only: never imported by
python/ or tools/.
"""

from __future__ import annotations

import builtins
import io
import os

ENV = "MQL5BOT_EMULATE_WINDOWS_NEWLINES"
SITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "_windows_newlines_site")


def install() -> None:
    import _pyio

    os.linesep = "\r\n"
    builtins.open = _pyio.open
    io.open = _pyio.open


def enabled() -> bool:
    return os.environ.get(ENV) == "1"
