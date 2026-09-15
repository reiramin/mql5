"""mql5bot.factory.claims — AUTHOR_CLAIM extraction (mission §13/§27).

Claim extraction is DETERMINISTIC pattern matching over source text —
not an LLM feature.  Extracted claims are stored as ``AUTHOR_CLAIM``
and are NEVER merged into measured Aegis metrics; the UI shows them
side by side, clearly separated (claimed vs independently measured).
"""

from __future__ import annotations

import re

# metric → regexes over the source text (EN + FA phrasings)
_PATTERNS: dict[str, list[str]] = {
    "win_rate": [
        r"(?:win\s*rate|winrate)\D{0,15}?(\d{1,3}(?:\.\d+)?)\s*%",
        # reversed order: "90% win rate"
        r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:win\s*rate|winrate)",
        r"(?:نرخ\s*برد|وین\s*ریت)\D{0,15}?(\d{1,3}(?:\.\d+)?)\s*٪?%",
    ],
    "cagr": [r"cagr\D{0,15}?(\d{1,3}(?:\.\d+)?)\s*%",
             r"رشد\s*سالانه\D{0,15}?(\d{1,3}(?:\.\d+)?)\s*٪"],
    "sharpe": [r"sharpe\D{0,15}?(\d+(?:\.\d+)?)",
               r"شارپ\D{0,15}?(\d+(?:\.\d+)?)"],
    "max_drawdown": [
        r"(?:max(?:imum)?\s*(?:drawdown|dd)|mdd)\D{0,15}?(\d{1,3}(?:\.\d+)?)\s*%",
        r"(?:حداکثر\s*افت|درawdown)\D{0,15}?(\d{1,3}(?:\.\d+)?)\s*٪"],
    "trades": [r"(\d{2,7})\s*(?:trades|deals|transactions)",
               r"(\d{2,7})\s*(?:معامله|ترید)"],
    "profit_factor": [r"(?:profit\s*factor|pf)\D{0,15}?(\d+(?:\.\d+)?)",
                      r"فاکتور\s*سود\D{0,15}?(\d+(?:\.\d+)?)"],
}

_NUM_RE = re.compile(r"^\d+(?:\.\d+)?$")


def extract_claims(text: str) -> list[dict]:
    """Deterministic AUTHOR_CLAIM extraction.  Every hit records the
    verbatim context note; nothing here is evidence."""
    claims: list[dict] = []
    low = text or ""
    for metric, patterns in _PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, low, flags=re.IGNORECASE)
            if m:
                raw = m.group(1)
                if not _NUM_RE.match(raw):
                    continue
                value = float(raw)
                if metric in {"win_rate", "cagr", "max_drawdown"} and \
                        value > 1.0:
                    value = value / 100.0        # 82% → 0.82
                claims.append({
                    "metric": metric,
                    "value": value,
                    "unit": "ratio" if metric in {"win_rate",
                                                  "max_drawdown",
                                                  "cagr"} else None,
                    "note": f"AUTHOR_CLAIM matched '{m.group(0)}' in "
                            "source text",
                })
                break                            # one claim per metric
    return claims
