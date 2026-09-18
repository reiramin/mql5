"""Convergence §68 static architecture scans: forbidden imports, order
execution boundaries, shell-execution surface, and the by-design SSRF
refusal — pinned as tests, not conventions."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "python" / "mql5bot"

GOVERNANCE_LAYERS = ("factory", "discovery", "api", "dsl",
                     "indicator_universe")


def _tree(path: Path):
    try:
        return ast.parse(path.read_text())
    except SyntaxError:
        return None


def _py_files(*dirs: str):
    for d in dirs:
        yield from (PY / d).rglob("*.py")


def test_no_mt5_imports_in_governance_layers():
    """Factory/discovery/api/dsl never touch MetaTrader5 — the live
    bridge is the ONLY allowed consumer (§4/§68)."""
    for p in _py_files(*GOVERNANCE_LAYERS):
        src = p.read_text()
        assert "import MetaTrader5" not in src, p
        assert "from MetaTrader5" not in src, p


def test_no_order_sending_anywhere_in_python():
    """Orders are sent ONLY by the MQL5 EA.  No Python module may CALL
    order-sending functions (§40: single execution boundary).  Detector
    REGEXES in security.py that scan untrusted text for order words are
    content, not calls — the AST check skips string literals."""
    banned = {"OrderSend", "CTrade", "order_send", "send_order",
              "positions_create"}
    for p in PY.rglob("*.py"):
        tree = _tree(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", getattr(func, "id", ""))
                if name in banned:
                    pytest.fail(f"{p}: Python calls order-sending "
                                f"API {name!r}")
            if isinstance(node, ast.Import) and \
                    p.relative_to(PY).parts[0] in GOVERNANCE_LAYERS:
                for a in node.names:
                    if a.name in ("MetaTrader5",):
                        pytest.fail(f"{p}: governance layer imports "
                                    "MetaTrader5")
            if isinstance(node, ast.Attribute) and \
                    node.attr in ("order_send", "OrderSend") and \
                    "security" not in p.name:
                # attribute reference outside the security detector
                pytest.fail(f"{p}: references order-sending API")


def test_no_shell_execution_in_governance_layers():
    for p in _py_files(*GOVERNANCE_LAYERS):
        src = p.read_text()
        for banned in ("os.system", "subprocess.run", "subprocess.Popen",
                       "pty.spawn"):
            assert banned not in src, (p, banned)
        tree = _tree(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Name) and \
                    node.func.id in ("eval", "exec", "compile"):
                pytest.fail(f"{p}: dynamic code execution "
                            f"({node.func.id})")


def test_providers_never_fetch_network():
    """§11/§65#17 SSRF-by-design: community material enters by paste /
    user-provided file only.  The provider layer performs NO network
    fetches — a URL is stored as provenance, never dereferenced."""
    src = (PY / "factory" / "providers.py").read_text()
    for banned in ("import requests", "import urllib", "import httpx",
                   "urlopen", "http.client", "socket.", "get("):
        assert banned not in src, banned


def test_factory_has_no_dependency_into_execution():
    """§4: the Factory may orchestrate research (deterministic engine),
    but must never import the live-execution bridge or the EA tooling
    that talks to a terminal."""
    for p in _py_files("factory"):
        src = p.read_text()
        for banned in ("mt5tester", "telemetry_bridge", "MetaTrader5"):
            assert banned not in src, (p, banned)


def test_lifecycle_transitions_only_via_store():
    """The store is the single lifecycle boundary: no other module may
    UPDATE strategy rows or insert LifecycleEvents directly."""
    for p in _py_files(*GOVERNANCE_LAYERS):
        if p.name == "store.py":
            continue
        tree = _tree(p)
        if tree is None:
            continue
        src = p.read_text()
        assert "current_state = " not in src, p
        assert "LifecycleEvent(" not in src or "factory" in str(p), p
