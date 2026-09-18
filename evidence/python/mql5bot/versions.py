"""mql5bot.versions — semantic versions of the research identity.

These constants participate in the OOS certification identity
(:class:`mql5bot.pipeline.OosRegistry`): a certification recorded under
one identity is NOT reusable under another.  Bump a version whenever the
corresponding SEMANTICS change — never to obtain a fresh certification
look on the same data (that is refused outright; see the one-look
policy).
"""

from __future__ import annotations

# Canonical research engine semantics (mql5bot.engine / backtest wrapper
# / fast engine equivalence contract).
ENGINE_VERSION = "1.0.0"

# Cost model semantics (mql5bot.costs: fills, spread/slippage/
# commission accounting conventions).
COST_MODEL_VERSION = "1.0.0"

# Signal/feature semantics (mql5bot.strategies + mql5bot.indicators:
# what a signal value means on a closed bar).
FEATURE_VERSION = "1.0.0"

# Certification protocol / registry identity schema (this file's
# identity contract; schema 2 = content-digest identity, see
# docs/CERTIFICATION.md and docs/CV_STATE_CONTRACT.md).
CERTIFICATION_PROTOCOL_VERSION = "2.0.0"


def git_commit() -> str:
    """Short commit hash of the running research code (best effort).

    Reads the git worktree; falls back to the ``MQL5BOT_COMMIT``
    environment variable (pinned-execution environments), then
    ``"unknown"``.  Recorded in every run manifest so a result is
    traceable to the exact code that produced it.
    """
    import logging
    import os
    import subprocess
    from pathlib import Path

    env = os.environ.get("MQL5BOT_COMMIT")
    if env:
        return env
    try:
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / ".git").exists():
                out = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=parent, capture_output=True, text=True,
                    timeout=10, check=False)
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.strip()
                break
    except Exception as exc:  # noqa: BLE001 — best-effort provenance
        logging.getLogger(__name__).debug(
            "git_commit detection failed: %s", exc)
    return "unknown"


def reproducibility_block() -> dict:
    """The complete semantic identity of a research run (Phase 13):
    code version (git commit), engine / cost-model / feature /
    certification-protocol versions.  Recorded in every ``RunManifest``
    next to the data digest, strategy version, seed and configuration
    that the manifest already carries."""
    return {
        "git_commit": git_commit(),
        "engine_version": ENGINE_VERSION,
        "cost_model_version": COST_MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "certification_protocol_version": CERTIFICATION_PROTOCOL_VERSION,
    }
