"""mql5bot.factory.security — intake hardening (mission §42/§58/§65/
§67).  External text is DATA, never instructions.

Every entry point that accepts human/community text funnels through
:mfunc:`sanitize_external_text`, which:

- enforces a size limit (oversized input is refused, not truncated);
- strips control characters;
- flags (but preserves verbatim, for provenance) instruction-like
  patterns ("ignore previous instructions", "place order",
  "disable risk", tool/CLI calls) as ``injection_warnings`` so
  downstream reviewers see the attempt and the interpreter treats
  them as strategy TEXT ONLY;
- never executes, evaluates, or follows anything it finds.

Path safety for artifact names (:mfunc:`safe_artifact_name`) closes
traversal (``../``), absolute paths, and control characters.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

MAX_TEXT_CHARS = 100_000

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction_override", re.compile(
        r"(ignore|disregard|forget)\s+(all\s+|any\s+)?(previous|prior|"
        r"above)\s+(instructions?|rules?|prompts?)", re.IGNORECASE)),
    ("role_hijack", re.compile(
        r"(you\s+are\s+now|act\s+as|pretend\s+to\s+be|new\s+"
        r"instructions?[:\s])", re.IGNORECASE)),
    ("execution_request", re.compile(
        r"\b(run|execute|eval|import|pip install|os\.system|subprocess|"
        r"shell|bash|powershell)\b", re.IGNORECASE)),
    ("trading_request", re.compile(
        r"\b(place|send|open)\s+(an?\s+)?(order|trade|position)\b|"
        r"\b(order_send|BUY\s+NOW|SELL\s+NOW)\b", re.IGNORECASE)),
    ("risk_disable", re.compile(
        r"\b(disable|bypass|turn\s+off|skip)\s+(the\s+)?(risk|stop\s*"
        r"loss|checks?|gates?|validation)\b", re.IGNORECASE)),
    ("exfiltration", re.compile(
        r"\b(send|upload|post|curl|http)\b[^.]{0,40}\b(api[_ ]?key|"
        r"token|secret|password|credential)\b", re.IGNORECASE)),
    ("policy_override", re.compile(
        r"\b(ignore|violate|override|bypass)\b[^.]{0,30}"
        r"\b(policy|policies|rules?|aegis|gate|gates)\b", re.IGNORECASE)),
    ("state_forgery", re.compile(
        r"\b(mark|set|promote|move|make)\b[^.]{0,30}\b(this\s+)?"
        r"(strategy|candidate|it|system)\b[^.]{0,20}"
        r"\b(live|demo|production|approved)\b", re.IGNORECASE)),
)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TextRefused(Exception):
    """Oversized or binary-looking input — refused whole (§41)."""


def sanitize_external_text(text: str, *, max_chars: int = MAX_TEXT_CHARS
                           ) -> dict:
    """Return ``{"text", "injection_warnings", "refused", "reason"}``.

    The returned ``text`` is VERBATIM except control-character
    removal — sanitizing never rewrites meaning (provenance §13);
    warnings are attached as data for humans and tests."""
    if not isinstance(text, str):
        raise TextRefused("external text must be str")
    if len(text) > max_chars:
        raise TextRefused(
            f"input too large: {len(text)} > {max_chars} chars "
            "(resource limit, §43)")
    if "\x00" in text:
        raise TextRefused("binary input refused")
    warnings = []
    for name, pat in _INJECTION_PATTERNS:
        m = pat.search(text)
        if m:
            warnings.append({"kind": name, "sample": m.group(0)[:80]})
    return {"text": _CONTROL_RE.sub("", text),
            "injection_warnings": warnings,
            "refused": False, "reason": ""}


def safe_artifact_name(name: str) -> str:
    """Whitelist artifact names: ``[A-Za-z0-9._-]+``, no traversal,
    no absolute paths, ≤128 chars.  Anything else is refused."""
    if not name or len(name) > 128:
        raise ValueError("artifact name must be 1..128 chars")
    if PurePosixPath(name).is_absolute() or \
            PureWindowsPath(name).is_absolute() or \
            ".." in name.split("/") or "\\" in name or \
            not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ValueError(f"unsafe artifact name {name!r}")
    return name
