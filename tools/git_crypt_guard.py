#!/usr/bin/env python3
"""tools/git_crypt_guard.py - REPO-SECURITY-1: strategy secrets are
committed ENCRYPTED.

``strategies/private/**`` holds strategy DSL bundles and parameter sets that
are NOT part of the certified golds. ``.gitattributes`` routes that path
through git-crypt (``filter=git-crypt diff=git-crypt``). If git-crypt is not
installed, or the repository was never ``git-crypt init``-ed / unlocked, git
silently passes the file through in PLAINTEXT - so this guard checks the
bytes git actually stores: every staged blob under the path must start with
the git-crypt header ``\\x00GITCRYPT\\x00``.

It also checks the other direction: the evidence the gate, the tests and
the verifier read (``artifacts/``, ``examples/strategies/``, the sources)
must NOT be routed through git-crypt - those stay plaintext and frozen.

Exit code: 0 = OK, 1 = a violation (each named). Standard library only;
it reads the index (``git ls-files -s``), so it checks what the next commit
would contain, and in CI (index == HEAD) what was committed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PRIVATE_DIR = "strategies/private/"
GITATTRIBUTES_RULE = "strategies/private/** filter=git-crypt diff=git-crypt"
GITCRYPT_HEADER = b"\x00GITCRYPT\x00"
# paths that must stay plaintext: evidence and everything the gate,
# the tests or the verifier read
MUST_STAY_PLAINTEXT = (
    "artifacts/gold/manifest.json",
    "artifacts/gold_2/manifest.json",
    "artifacts/owner_mt5_gate/frozen_inputs.json",
    "artifacts/dsl_parity/ema_cross/bundle.json",
    "examples/strategies/ema_crossover.json",
    "examples/strategies/gold2_multifactor.json",
    "mql5/Experts/Mql5Bot/Mql5Bot.mq5",
    "python/mql5bot/owner_gate.py",
    "tools/verify_owner_mt5_gate.py",
    "strategies/README.md",
)


def is_encrypted(blob: bytes) -> bool:
    return blob.startswith(GITCRYPT_HEADER)


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          check=True).stdout


def staged_private_blobs(repo: Path) -> list[tuple[str, str]]:
    """(path, blob sha) for every staged file under strategies/private/."""
    out = _git(repo, "ls-files", "-s", "-z", "--", PRIVATE_DIR)
    rows = []
    for rec in out.decode("utf-8").split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        rows.append((path, meta.split()[1]))
    return rows


def check(repo: Path) -> list[str]:
    problems: list[str] = []
    attrs = repo / ".gitattributes"
    text = attrs.read_text(encoding="utf-8") if attrs.is_file() else ""
    if GITATTRIBUTES_RULE not in text.splitlines():
        problems.append(f".gitattributes lacks the rule {GITATTRIBUTES_RULE!r}")
    for path, sha in staged_private_blobs(repo):
        if not is_encrypted(_git(repo, "cat-file", "blob", sha)):
            problems.append(
                f"{path} is staged/committed in PLAINTEXT (no git-crypt "
                "header): run `git-crypt unlock` (or `git-crypt init` on a "
                "new clone with the key) and re-add it; see docs/SECURITY.md")
    out = _git(repo, "check-attr", "filter", "--", *MUST_STAY_PLAINTEXT)
    for line in out.decode("utf-8").splitlines():
        path, _, value = line.split(": ", 2)
        if value.strip() == "git-crypt":
            problems.append(f"{path} must stay plaintext (evidence / read by "
                            "the gate, tests or verifier) but is routed "
                            "through git-crypt")
    return problems


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    problems = check(repo)
    for p in problems:
        print(f"git_crypt_guard: {p}")
    if problems:
        return 1
    print(f"git_crypt_guard: OK ({len(staged_private_blobs(repo))} encrypted "
          f"file(s) under {PRIVATE_DIR})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
