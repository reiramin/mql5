# Subprocess half of tests/windows_newlines.py: active only when
# MQL5BOT_EMULATE_WINDOWS_NEWLINES=1 (set by tests/conftest.py).
import os

if os.environ.get("MQL5BOT_EMULATE_WINDOWS_NEWLINES") == "1":
    import _pyio
    import builtins
    import io
    import pathlib

    os.linesep = "\r\n"
    builtins.open = _pyio.open
    io.open = _pyio.open
    # Python 3.10: pathlib opens through _NormalAccessor.open (bound to
    # io.open at class creation), see tests/windows_newlines.patches()
    _acc = getattr(pathlib, "_NormalAccessor", None)
    if _acc is not None and hasattr(_acc, "open"):
        _acc.open = staticmethod(_pyio.open)
