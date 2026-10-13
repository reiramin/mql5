"""REPO-SECURITY-1: strategy secrets under strategies/private/ are committed
ENCRYPTED (git-crypt), and nothing the gate, tests or verifier read is.

Runs tools/git_crypt_guard.py against this repository and against throwaway
repositories: a plaintext file under the private path fails, a blob carrying
the git-crypt header passes, and routing evidence through git-crypt fails.
No key is generated or needed: the guard checks the stored bytes.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "git_crypt_guard", REPO / "tools" / "git_crypt_guard.py")
gg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gg)


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    return subprocess.run(["git", *args], cwd=repo, input=stdin,
                          capture_output=True, check=True).stdout.decode()


def _repo(tmp_path: Path, rules: str = gg.GITATTRIBUTES_RULE) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    (r / ".gitattributes").write_text(rules + "\n", encoding="utf-8")
    _git(r, "add", ".gitattributes")
    return r


def _stage_raw(repo: Path, path: str, data: bytes) -> None:
    """Stage exact bytes (as git-crypt's clean filter would store them)."""
    sha = _git(repo, "hash-object", "-w", "--stdin", stdin=data).strip()
    _git(repo, "update-index", "--add", "--cacheinfo",
         f"100644,{sha},{path}")


def test_this_repository_passes_the_guard():
    assert gg.check(REPO) == []


def test_the_rule_is_in_gitattributes_and_applies_to_the_private_path():
    assert gg.GITATTRIBUTES_RULE in (REPO / ".gitattributes").read_text(
        encoding="utf-8").splitlines()
    out = _git(REPO, "check-attr", "filter", "diff", "--",
               "strategies/private/x/bundle.json")
    assert "filter: git-crypt" in out and "diff: git-crypt" in out


def test_evidence_and_gate_inputs_stay_plaintext():
    out = _git(REPO, "check-attr", "filter", "--", *gg.MUST_STAY_PLAINTEXT)
    assert "git-crypt" not in out


def test_a_plaintext_strategy_file_fails(tmp_path):
    r = _repo(tmp_path)
    _stage_raw(r, "strategies/private/s.json", b'{"params": {"fast": 8}}')
    problems = gg.check(r)
    assert len(problems) == 1 and "PLAINTEXT" in problems[0]
    assert "strategies/private/s.json" in problems[0]


def test_an_encrypted_blob_passes(tmp_path):
    r = _repo(tmp_path)
    _stage_raw(r, "strategies/private/s.json",
               gg.GITCRYPT_HEADER + b"\x8a\x11opaque-ciphertext")
    assert gg.check(r) == []


def test_a_missing_rule_fails(tmp_path):
    r = _repo(tmp_path, rules="*.py text eol=lf")
    assert any("lacks the rule" in p for p in gg.check(r))


def test_routing_evidence_through_git_crypt_fails(tmp_path):
    r = _repo(tmp_path, rules=gg.GITATTRIBUTES_RULE +
              "\nartifacts/** filter=git-crypt diff=git-crypt")
    problems = gg.check(r)
    assert any("artifacts/gold/manifest.json must stay plaintext" in p
               for p in problems)


def test_header_detection():
    assert gg.is_encrypted(b"\x00GITCRYPT\x00rest")
    assert not gg.is_encrypted(b"{}")
    assert not gg.is_encrypted(b"GITCRYPT")
