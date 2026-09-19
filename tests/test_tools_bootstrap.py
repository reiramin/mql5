"""STAGE 5 R4 — the gate must grade THIS repo's mql5bot, not an installed copy.

gate_run16 imported an installed mql5bot on the Windows host, so R2's
run_backtest changes were absent while R3's tools-file constant applied — a
certification gate grading a different copy of the code than it shipped. These
tests pin the fix: every tools/ entry point resolves mql5bot inside the repo
(even with a competing copy on PYTHONPATH), the stage-0 provenance decision
fails closed when it would resolve outside, and the resolved path + version are
recorded as evidence.
"""

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
REPO_MQL5BOT = REPO / "python" / "mql5bot" / "__init__.py"
DECIDE = TOOLS / "owner_gate_decide.py"


def _load_bootstrap():
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("_bootstrap", TOOLS / "_bootstrap.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BOOTSTRAP = _load_bootstrap()


def _mql5bot_importing_tools() -> list[Path]:
    """Every tools/*.py (except the bootstrap itself) that imports mql5bot."""
    out = []
    for p in sorted(TOOLS.glob("*.py")):
        if p.name == "_bootstrap.py":
            continue
        if re.search(r"^\s*(from|import)\s+mql5bot", p.read_text(encoding="utf-8"),
                     re.MULTILINE):
            out.append(p)
    return out


def _decoy_env() -> tuple[str, dict]:
    """A temp dir holding a competing ``mql5bot`` and an env pointing at it."""
    decoy = tempfile.mkdtemp(prefix="decoy_mql5bot_")
    pkg = Path(decoy) / "mql5bot"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('__version__ = "DECOY"\n', encoding="utf-8")
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = decoy + os.pathsep + env.get("PYTHONPATH", "")
    return decoy, env


# ---------------------------------------------------------------------------
# the shared bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_pins_repo_python_at_front():
    BOOTSTRAP.ensure_repo_first()
    assert sys.path[0] == str(REPO / "python")


def test_is_inside_repo_true_for_repo_false_for_outside(tmp_path):
    assert BOOTSTRAP.is_inside_repo(REPO_MQL5BOT) is True
    assert BOOTSTRAP.is_inside_repo(tmp_path / "mql5bot" / "__init__.py") is False


def test_build_provenance_ok_only_when_inside_repo(tmp_path):
    inside = BOOTSTRAP.build_provenance(REPO_MQL5BOT, "1.0.0")
    assert inside["ok"] is True and inside["inside_repo"] is True
    assert inside["mql5bot_version"] == "1.0.0"
    assert inside["repo_root"] == str(REPO)

    outside_file = tmp_path / "site-packages" / "mql5bot" / "__init__.py"
    out = BOOTSTRAP.build_provenance(outside_file, "9.9.9")
    # the stage-0 check FAILS when mql5bot resolves outside the repo
    assert out["ok"] is False and out["inside_repo"] is False
    # and the record names BOTH paths so the failure is diagnosable
    assert out["repo_root"] == str(REPO)
    assert str(outside_file.resolve()) == out["mql5bot_file"]


def test_mql5bot_provenance_resolves_repo_copy():
    prov = BOOTSTRAP.mql5bot_provenance()
    assert prov["ok"] is True
    assert prov["mql5bot_file"] == str(REPO_MQL5BOT.resolve())
    assert prov["mql5bot_version"] != "DECOY"


# ---------------------------------------------------------------------------
# every tools entry point resolves mql5bot inside the repo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", _mql5bot_importing_tools(),
                         ids=lambda p: p.name)
def test_tool_resolves_mql5bot_inside_repo_despite_decoy(tool):
    # Load the tool with a COMPETING mql5bot first on PYTHONPATH; the bootstrap
    # must still resolve THIS repo's copy — the exact gate_run16 failure mode.
    _decoy, env = _decoy_env()
    tools_dir = str(TOOLS)
    tool_path = str(tool)
    runner = (
        "import importlib.util, sys\n"
        f"sys.path.insert(0, r'{tools_dir}')\n"
        f"spec = importlib.util.spec_from_file_location('t', r'{tool_path}')\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "sys.modules['t'] = m\n"
        "spec.loader.exec_module(m)\n"
        "import mql5bot\n"
        "print(mql5bot.__file__)\n"
    )
    res = subprocess.run([sys.executable, "-c", runner], capture_output=True,
                         text=True, env=env, check=False)
    assert res.returncode == 0, f"{tool.name}: {res.stderr}"
    resolved = res.stdout.strip().splitlines()[-1]
    assert resolved == str(REPO_MQL5BOT), f"{tool.name} resolved {resolved}"


def test_all_mql5bot_tools_are_covered():
    # guard: the discovery actually found the entry points, incl. the one that
    # regressed (run_mt5_backtest) and the decision maker (owner_gate_decide).
    names = {p.name for p in _mql5bot_importing_tools()}
    assert "run_mt5_backtest.py" in names
    assert "owner_gate_decide.py" in names
    assert len(names) >= 10


# ---------------------------------------------------------------------------
# stage-0 provenance decision (owner_gate_decide provenance)
# ---------------------------------------------------------------------------


def test_provenance_decision_passes_and_records_path_and_version():
    _decoy, env = _decoy_env()
    res = subprocess.run(
        [sys.executable, str(DECIDE), "--repo", str(REPO), "provenance"],
        capture_output=True, text=True, env=env, check=False)
    assert res.returncode == 0, res.stderr
    prov = json.loads(res.stdout)
    assert prov["ok"] is True and prov["inside_repo"] is True
    # the evidence names the code it graded: resolved path + version
    assert prov["mql5bot_file"] == str(REPO_MQL5BOT.resolve())
    assert prov["mql5bot_version"] == "1.0.0"
    assert prov["mql5bot_version"] != "DECOY"


# ---------------------------------------------------------------------------
# the gate wires the check fail-closed and records the path in evidence
# ---------------------------------------------------------------------------


def _gate_source() -> str:
    return (TOOLS / "owner_gate.ps1").read_text(encoding="utf-8")


def test_gate_runs_provenance_failclosed_in_stage0():
    src = _gate_source()
    assert 'Invoke-Decide @("provenance")' in src
    # fail-closed: a non-ok provenance records a stage-0 FAIL and finishes
    assert re.search(r"if \(-not \$prov\.ok\)", src)
    assert 'Record-Stage 0 "self_protection" "FAIL"' in src
    # the FAIL reason names BOTH the repo root and where mql5bot came from
    assert "repo_root" in src and "mql5bot_file" in src


def test_gate_records_resolved_path_in_evidence():
    src = _gate_source()
    # the provenance JSON is attached as an artifact and the path/version are
    # folded into the stage-0 PASS reason (the verdict names the graded code)
    assert "New-Artifact $prov.raw" in src
    assert "mql5bot IN-REPO" in src
