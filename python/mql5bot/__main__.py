"""``python -m mql5bot`` — identical to the installed ``mql5bot`` console
script (both dispatch to :func:`mql5bot.cli.main`)."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
