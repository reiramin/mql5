"""Regression: hashed and canonical files must not depend on os.linesep.

reports/windows_pytest/failures.txt (gate-reports, master 3337bfa) listed
80 Windows failures. 64 came from text-mode newline translation:
- `to_csv()` defaults its line terminator to os.linesep;
- `write_text()` turns "\\n" into "\\r\\n" on Windows.

Either way the bytes, and so every sha256 the verifier compares, differ
from the POSIX bytes. tests/windows_newlines.py reproduces that on any OS
(os.linesep = "\\r\\n" and the pure-Python `_pyio` text layer). These tests
run the affected paths under it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import windows_newlines as wn

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"


@pytest.fixture()
def crlf(monkeypatch):
    """Windows text-mode newline behaviour, in this process, undone after
    the test."""
    for target, name, value in wn.patches():
        monkeypatch.setattr(target, name, value)


def test_the_emulation_really_translates(crlf, tmp_path):
    # the premise: under the emulation, a plain text write IS the Windows
    # write (otherwise the tests below would prove nothing)
    p = tmp_path / "t.txt"
    p.write_text("a\nb\n", encoding="utf-8")
    assert p.read_bytes() == b"a\r\nb\r\n"
    import pandas as pd

    assert "\r\n" in pd.DataFrame({"x": [1, 2]}).to_csv()


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_wn_{name}", REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("tool,fixture_rel,frozen_key", [
    ("build_gold_standard", "artifacts/gold/gold_fixture.csv", "gold_1"),
    ("build_gold2_standard", "artifacts/gold_2/gold2_fixture.csv", "gold_2"),
])
def test_gold_builders_write_the_frozen_fixture_bytes_under_crlf(
        crlf, tmp_path, tool, fixture_rel, frozen_key):
    import json

    mod = _load_tool(tool)
    text = mod.build_fixture().to_csv(float_format="%.10f",
                                      lineterminator="\n")
    out = tmp_path / "fixture.csv"
    mod._write_artifact(out, text)
    raw = out.read_bytes()
    assert b"\r" not in raw
    frozen = json.loads((REPO / "artifacts/owner_mt5_gate/"
                         "frozen_inputs.json").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == \
        frozen[frozen_key]["fixture_sha256"] == \
        hashlib.sha256((REPO / fixture_rel).read_bytes()).hexdigest()


# the tests reports/windows_pytest/failures.txt listed for newline
# translation (one or more per affected file), run under the emulation
CRLF_SENSITIVE = [
    "tests/test_ema_seed_parity.py::test_legacy_series_is_the_formerly_frozen_fixture",
    "tests/test_gold2_standard.py::test_fixture_replay_is_deterministic_and_bound_to_artifact",
    "tests/test_reality_gate.py::test_gold_manifest_and_fixture_deterministic",
    "tests/test_owner_gate.py::test_complete_valid_package_reaches_mt5_validated",
    "tests/test_owner_gate.py::test_safety_valid_evidence_accepted",
    "tests/test_gate_scope.py::test_default_verify_is_unchanged",
    "tests/test_verdict_bar_models.py::test_bar_only_complete_package_is_mt5_validated_bar_models",
    "tests/test_owner_gate_log_trades.py::test_tampered_log_trade_list_fails",
    "tests/test_s8_count_ts_tickpath.py::test_window_copies_are_packaged_and_bound",
    "tests/test_stage8_package_from_gate.py::test_reconciliation_pairs_by_time_never_by_position",
    "tests/test_s8_spec3_identity_and_anchor.py::test_descendant_with_identical_frozen_bytes_is_accepted",
]


def test_newline_sensitive_tests_pass_with_windows_line_separators(
        tmp_path):
    env = dict(os.environ)
    env[wn.ENV] = "1"
    # a git that converts line endings on commit, as Git for Windows does
    # by default: the throwaway repos must pin core.autocrlf=false
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_bytes(b"[core]\n\tautocrlf = true\n")
    env["HOME"] = str(home)
    env.pop("XDG_CONFIG_HOME", None)
    cp = subprocess.run([sys.executable, "-m", "pytest", "-q",
                         "-p", "no:cacheprovider", *CRLF_SENSITIVE],
                        cwd=REPO, env=env, capture_output=True, text=True,
                        check=False)
    assert cp.returncode == 0, cp.stdout[-4000:] + cp.stderr[-2000:]
