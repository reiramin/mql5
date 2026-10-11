# Subprocess half of tests/windows_newlines.py: active only when
# MQL5BOT_EMULATE_WINDOWS_NEWLINES=1 (set by tests/conftest.py).
import os

if os.environ.get("MQL5BOT_EMULATE_WINDOWS_NEWLINES") == "1":
    import _pyio
    import builtins
    import io

    os.linesep = "\r\n"
    builtins.open = _pyio.open
    io.open = _pyio.open
