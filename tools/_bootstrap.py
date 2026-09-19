"""Repo-local import bootstrap for tools/ scripts (STAGE 5 R4).

Every ``tools/`` script that imports :mod:`mql5bot` MUST resolve it from THIS
repo's ``python/`` tree, never an INSTALLED copy in site-packages.  gate_run16
(on HEAD c7aec19) proved the hole: on the Windows host the gate imported an
installed ``mql5bot`` instead of the repo's, so R2's ``run_backtest`` changes
were absent (the outcome carried the PRE-R2 "report not found" text, no
``searched:`` list, no ``exit_code``) while R3's tools-file constant applied.
A certification gate that grades the repo using a DIFFERENT copy of the code is
not certifying the repo.

The repo-resolution logic lives HERE, once, so it cannot drift across the many
tools that need it.  Importing this module pins ``<repo_root>/python`` at
``sys.path[0]`` before any ``mql5bot`` import.  A tools script uses the
two-line preamble (self-locating so it also works when a test loads the file
via ``importlib`` without ``tools/`` already on the path):

    sys.path.insert(0, str(Path(__file__).resolve().parent))  # find _bootstrap
    import _bootstrap  # noqa: F401  pins repo python/ ahead of any installed mql5bot
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"


def ensure_repo_first() -> Path:
    """Pin the repo's ``python/`` dir at ``sys.path[0]``; return the repo root.

    Any existing occurrence is removed first so the repo copy is unambiguously
    ahead of an installed one, even if a prior insertion left it lower down.
    """
    target = str(PYTHON_DIR)
    sys.path[:] = [p for p in sys.path if p != target]
    sys.path.insert(0, target)
    return REPO_ROOT


def is_inside_repo(pkg_file: str | Path, repo_root: str | Path = REPO_ROOT) -> bool:
    """True when ``pkg_file`` resolves to a path inside ``repo_root``."""
    pkg = Path(pkg_file).resolve()
    root = Path(repo_root).resolve()
    try:
        pkg.relative_to(root)
        return True
    except ValueError:
        return False


def build_provenance(pkg_file: str | Path, version: str) -> dict:
    """Provenance record for a resolved mql5bot (pure — testable in isolation).

    ``ok``/``inside_repo`` is True only when the resolved package file lives
    inside this repo, so a gate that resolved an installed copy fails closed and
    the record names BOTH the repo root and where mql5bot actually came from.
    """
    inside = is_inside_repo(pkg_file)
    return {
        "ok": inside,
        "inside_repo": inside,
        "repo_root": str(REPO_ROOT),
        "python_dir": str(PYTHON_DIR),
        "mql5bot_file": str(Path(pkg_file).resolve()),
        "mql5bot_version": version,
    }


def mql5bot_provenance() -> dict:
    """Resolve mql5bot (after pinning) and return its provenance record.

    Recorded in the stage-0 evidence so every run states which code produced the
    verdict — the point of the check: the evidence must name the code it graded.
    """
    ensure_repo_first()
    import mql5bot
    return build_provenance(mql5bot.__file__,
                            getattr(mql5bot, "__version__", "unknown"))


# Pin on import so a bare `import _bootstrap` before `import mql5bot` suffices.
ensure_repo_first()
