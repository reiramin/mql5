#!/usr/bin/env python3
"""tools/secret_scan.py - REPO-SECURITY-1: fail on secret-shaped content.

Scans the tracked tree (default) or the files given on the command line
(the pre-commit hook passes the staged files) for:

* private key blocks (PEM / OpenSSH / PGP) and age secret keys;
* API tokens with a recognisable shape (GitHub, AWS, Anthropic/OpenAI-style
  ``sk-``, Slack, Google, Telegram bot tokens);
* MT5 credentials: an ini ``Login=<5+ digits>`` with a non-placeholder
  ``Password=``, or a JSON object carrying a ``"login"`` of 5+ digits and a
  non-placeholder ``"password"``;
* the demo-accounts file shape: a ``"hedging"`` / ``"netting"`` object with a
  non-placeholder ``"password"`` (docs/SAFETY_DEMO_PLAN.md: that file lives
  OUTSIDE the repo).

A hit prints ``path:line: <pattern>`` and NEVER the matched value. The
whitelist below names each file + pattern that is allowed to match, with the
reason; ``tests/test_secret_scan.py`` fails if a whitelist entry stops
matching (so the whitelist cannot silently grow stale or broad).

Files under ``strategies/private/`` are git-crypt ciphertext in the
repository and are skipped (tests/test_git_crypt_guard.py checks that they
ARE ciphertext). Binary files (a NUL byte in the first 8 KiB, and not UTF-16
text) and files over 2 MiB are skipped.

Exit code: 0 = no hit, 1 = at least one hit, 2 = usage error.
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
ENCRYPTED_PREFIX = "strategies/private/"

PLACEHOLDER = re.compile(
    r"^(?:\.\.\.|<[^>]*>|\*+|x+|changeme|password|your[_-]?password|"
    r"\$\{?[A-Z0-9_]+\}?|%[A-Z0-9_]+%|REDACTED|<REDACTED>)$", re.IGNORECASE)

PATTERNS: dict[str, re.Pattern[str]] = {
    "private_key_block": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY"
        r"(?: BLOCK)?-----"),
    "age_secret_key": re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{58}"),
    "github_token": re.compile(
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"
        r"|\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "sk_api_key": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "telegram_bot_token": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"),
}

_INI_LOGIN = re.compile(r"^\s*Login\s*=\s*\d{5,}\s*$", re.MULTILINE)
_INI_PASSWORD = re.compile(r"^\s*Password\s*=\s*(\S+)\s*$", re.MULTILINE)
_JSON_LOGIN = re.compile(r"""["']login["']\s*:\s*["']?\d{5,}["']?""")
_JSON_PASSWORD = re.compile(r"""["']password["']\s*:\s*["']([^"']*)["']""")
_ACCOUNTS_ROLE = re.compile(
    r"""["'](?:hedging|netting)["']\s*:\s*\{[^{}]*?["']password["']\s*:"""
    r"""\s*["']([^"']*)["']""", re.DOTALL)

# (path, pattern) -> why the match is allowed. Every entry must still match
# (tests/test_secret_scan.py), so it cannot outlive its reason.
WHITELIST: dict[tuple[str, str], str] = {
    ("tests/test_safety_demo.py", "demo_accounts_shape"):
        "fake demo accounts fixture (logins 1111/2222, passwords s3cret-*) "
        "that proves credentials never reach the evidence",
    ("tests/test_demo_in_gate.py", "demo_accounts_shape"):
        "fake demo accounts fixture (logins 1111/2222, passwords s3cret-*)",
    ("tests/test_secret_scan.py", "*"):
        "the scanner's own tests build secret-shaped strings at run time",
}


def _real(value: str) -> bool:
    value = value.strip()
    return bool(value) and not PLACEHOLDER.match(value)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def scan_text(text: str) -> list[tuple[int, str]]:
    """(line, pattern) for every secret-shaped match in ``text``."""
    hits: list[tuple[int, str]] = []
    for name, rx in PATTERNS.items():
        hits += [(_line_of(text, m.start()), name) for m in rx.finditer(text)]
    login = _INI_LOGIN.search(text)
    if login:
        hits += [(_line_of(text, m.start()), "mt5_ini_credentials")
                 for m in _INI_PASSWORD.finditer(text) if _real(m.group(1))]
    if _JSON_LOGIN.search(text):
        hits += [(_line_of(text, m.start()), "mt5_json_credentials")
                 for m in _JSON_PASSWORD.finditer(text) if _real(m.group(1))]
    hits += [(_line_of(text, m.start()), "demo_accounts_shape")
             for m in _ACCOUNTS_ROLE.finditer(text) if _real(m.group(1))]
    return sorted(set(hits))


def _decode(raw: bytes) -> str | None:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="ignore")
    if b"\x00" in raw[:8192]:
        return None                              # binary
    return raw.decode("utf-8", errors="ignore")


def tracked_files(repo: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=repo,
                         capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def allowed(path: str, pattern: str) -> bool:
    return (path, pattern) in WHITELIST or (path, "*") in WHITELIST


def scan_paths(repo: Path, paths: list[str], *,
               apply_whitelist: bool = True) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for rel in paths:
        rel = rel.replace("\\", "/")
        if rel.startswith(ENCRYPTED_PREFIX):
            continue
        f = repo / rel
        if not f.is_file() or f.stat().st_size > MAX_BYTES:
            continue
        text = _decode(f.read_bytes())
        if text is None:
            continue
        for line, pattern in scan_text(text):
            if apply_whitelist and allowed(rel, pattern):
                continue
            found.append((rel, line, pattern))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*",
                    help="files to scan (default: every tracked file)")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    paths = args.files or tracked_files(repo)
    hits = scan_paths(repo, paths)
    for path, line, pattern in hits:
        print(f"{path}:{line}: {pattern} (value not printed)")
    if hits:
        print(f"secret_scan: {len(hits)} hit(s) -- remove the secret; it "
              "belongs in an environment variable or a file outside the repo")
        return 1
    print(f"secret_scan: {len(paths)} file(s), 0 hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
