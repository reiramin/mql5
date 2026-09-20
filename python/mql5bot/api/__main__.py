"""``python -m mql5bot.api`` — run the AEGIS operator console.

The console is a FastAPI app (an ASGI application). Serving it needs an ASGI
server; this runner uses ``uvicorn`` if it is installed and prints a clear,
actionable error if it is not — no server dependency is bundled.

WHAT THIS IS: a read-and-control surface. WHAT IT IS NOT: proof of anything.
Nothing in this project is certified — nothing is VERIFIED and stage 5 of the
certification gate FAILED (see ``docs/OWNER_DELIVERY.md``). The UI can view
state, stop trading (the kill switch), and drive the guided conversation; it
can never mark a strategy LIVE. Built and unit-tested; never run live.
"""

from __future__ import annotations

import argparse
import sys

from ..factory.store import FactoryStore
from .main import create_app

BANNER = (
    "AEGIS operator console\n"
    "  WHAT IT IS : a read-and-control surface over the system — view state,\n"
    "               stop trading (kill switch), run the guided conversation.\n"
    "  WHAT IT IS NOT : proof of anything. Nothing here is certified —\n"
    "               nothing is VERIFIED and stage 5 of the gate FAILED. The\n"
    "               UI can never mark a strategy LIVE.\n"
    "  Built and unit-tested; never run live.\n"
    "  Persian RTL status page: add ?lang=fa to the board URL."
)


class ServerDependencyMissing(RuntimeError):
    """The chosen ASGI server is not installed. The message names it and how
    to install it — it is never a silent failure."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mql5bot.api",
        description="Run the AEGIS operator console (FastAPI/ASGI).")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind host (default: 127.0.0.1, loopback only)")
    p.add_argument("--port", type=int, default=8000,
                   help="bind port (default: 8000)")
    p.add_argument("--db", default="factory.db",
                   help="factory store path (default: factory.db)")
    return p


def _load_server():
    """Return the ASGI server module, or raise :class:`ServerDependencyMissing`
    with a clear message. Importing here (not at module load) keeps
    ``build_parser`` and the app importable with no server installed."""
    try:
        import uvicorn
    except ImportError as exc:
        raise ServerDependencyMissing(
            "the ASGI server 'uvicorn' is not installed; install it to run the "
            "console (pip install uvicorn), or serve mql5bot.api.main:create_app "
            "with your own ASGI server") from exc
    return uvicorn


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(BANNER)
    app = create_app(FactoryStore(args.db))
    server = _load_server()
    server.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
