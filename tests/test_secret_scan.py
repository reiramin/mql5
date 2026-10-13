"""REPO-SECURITY-1: the secret scan (tools/secret_scan.py).

The whole tracked tree must scan clean (whitelist applied), every pattern
must fire on a secret-shaped string and stay quiet on placeholders, and
every whitelist entry must still be needed. Secret-shaped strings are built
at run time so this file does not itself carry one.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "secret_scan", REPO / "tools" / "secret_scan.py")
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)


def _j(*parts: str) -> str:
    return "".join(parts)


SHAPED = {
    "private_key_block": _j("-----BEGIN ", "OPENSSH PRIVATE KEY", "-----"),
    "age_secret_key": _j("AGE-SECRET-KEY-1", "Q" * 58),
    "github_token": _j("gh", "p_", "a" * 36),
    "aws_access_key": _j("AK", "IA", "ABCDEFGHIJKLMNOP"),
    "sk_api_key": _j("sk-", "ant-", "x" * 40),
    "slack_token": _j("xo", "xb-", "1234567890-abc"),
    "google_api_key": _j("AI", "za", "b" * 35),
    "telegram_bot_token": _j("123456789", ":AA", "c" * 33),
}


def test_the_tracked_tree_scans_clean():
    hits = ss.scan_paths(REPO, ss.tracked_files(REPO))
    assert hits == [], hits


def test_the_cli_exits_zero_on_the_tree_and_never_prints_values():
    cp = subprocess.run([sys.executable, str(REPO / "tools/secret_scan.py")],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "0 hits" in cp.stdout


@pytest.mark.parametrize("pattern", sorted(SHAPED))
def test_every_token_pattern_fires(pattern):
    hits = ss.scan_text(f"x = '{SHAPED[pattern]}'\n")
    assert (1, pattern) in hits


def test_mt5_ini_credentials():
    ini = _j("[Common]\nLogin=", "51234567", "\nPassword=", "Hunter2x", "\n")
    assert (3, "mt5_ini_credentials") in ss.scan_text(ini)
    # the harness template / docs: placeholders never fire
    for pw in ("...", "<password>", "${MT5_PASSWORD}", "%PASSWORD%"):
        assert ss.scan_text(_j("Login=", "51234567", "\nPassword=", pw)) == []
    # no 5+ digit login: no credential shape
    assert ss.scan_text("Login=1111\nPassword=abc\n") == []


def test_mt5_json_and_demo_accounts_shape():
    doc = _j('{"hedging": {"login": "', "51234567", '", "password": "',
             "Hunter2x", '", "server": "MetaQuotes-Demo"}}')
    names = {p for _, p in ss.scan_text(doc)}
    assert names == {"mt5_json_credentials", "demo_accounts_shape"}
    # the documented template in docs/SAFETY_DEMO_PLAN.md stays quiet
    template = ('{"hedging": {"login": "...", "password": "...", '
                '"server": "MetaQuotes-Demo"}}')
    assert ss.scan_text(template) == []


def test_files_under_the_encrypted_path_are_skipped(tmp_path):
    p = tmp_path / "strategies" / "private" / "a.json"
    p.parent.mkdir(parents=True)
    p.write_text(SHAPED["github_token"])
    assert ss.scan_paths(tmp_path, ["strategies/private/a.json"]) == []
    q = tmp_path / "b.txt"
    q.write_text(SHAPED["github_token"])
    assert ss.scan_paths(tmp_path, ["b.txt"]) == [("b.txt", 1,
                                                    "github_token")]


def test_utf16_text_is_scanned_binary_is_not(tmp_path):
    (tmp_path / "u.log").write_bytes(
        ("x " + SHAPED["aws_access_key"]).encode("utf-16"))
    (tmp_path / "b.bin").write_bytes(b"\x00\x01" + SHAPED["aws_access_key"]
                                     .encode())
    assert [h[0] for h in ss.scan_paths(tmp_path, ["u.log", "b.bin"])] == [
        "u.log"]


def test_every_whitelist_entry_is_still_needed():
    for (path, pattern), why in ss.WHITELIST.items():
        assert why.strip(), (path, pattern)
        if pattern == "*":
            continue
        raw = ss.scan_paths(REPO, [path], apply_whitelist=False)
        assert any(p == pattern for _, _, p in raw), \
            f"stale whitelist entry {path}:{pattern}"


def test_the_whitelist_is_narrow():
    # only test files may be whitelisted, never source, docs or tools
    for path, _ in ss.WHITELIST:
        assert path.startswith("tests/"), path


def test_pre_commit_runs_the_scan_and_ruff():
    cfg = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "tools/secret_scan.py" in cfg
    assert "ruff check python/ tests/ tools/ factory/" in cfg
