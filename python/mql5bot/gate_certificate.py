"""mql5bot.gate_certificate - stage 10 of the owner gate (STAGE10-CERT-1).

Stage 10 issues a certificate OF THE VERIFIER'S VERDICT. It never assigns
a verdict of its own: the verdict of record is what stage 8's
verify_owner_mt5_gate.py wrote (reconciliation_verify.json), and stage 9's
owner_evidence_bind.py manifest must bind that exact report by sha256.

It replaced tools/certify_strategy.py in stage 10 (owner decision,
2026-10-12). That tool runs a different protocol: its own tester ladder
over real 2020-2023 market regimes with a REQUIRED real-ticks leg, a
100-trade minimum and degradation bands. It cannot certify the bar-model
gold parity that S8-CEILING-1 defines, and without
artifacts/owner_mt5_gate/certify_config.json it never ran (stage 10 SKIP).

A certificate is issued ONLY when ALL of these hold, each refusal named:

* the verifier report parses, is NOT partial, has ``missing == []``, and
  its verdict is MT5_VALIDATED or MT5_VALIDATED_BAR_MODELS (a
  *_PARTIAL_SCOPE verdict is never accepted);
* it covers EVERY gold (gold1 and gold2), each ``result == MATCH`` and
  ``state == VALID``;
* every safety result is ``state == VALID``;
* the archive manifest parses and binds ``reconciliation_verify.json``
  with the sha256 the report has NOW.

The certificate states its scope ("bar models -- no real-tick claim;
m1_ohlc + every_tick only" for MT5_VALIDATED_BAR_MODELS), the trade
source of log-graded legs, and that it makes no profitability claim: it
certifies execution parity of the EA with the frozen Python expectation
on the frozen gold fixtures, and the safety behaviours listed.

Built, unit-tested, never run live.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from mql5bot import owner_gate as og

SCHEMA = "mql5bot.gate_certificate/1"
CERTIFIABLE = {
    og.MT5_VALIDATED: ("full", "full: m1_ohlc + every_tick + real ticks"),
    og.MT5_VALIDATED_BAR_MODELS: (
        "bar models",
        "bar models -- no real-tick claim; m1_ohlc + every_tick only"),
}
VERIFY_REL = "reconciliation_verify.json"
NO_PROFIT_CLAIM = (
    "No profitability claim. This certifies execution parity of the EA "
    "with the frozen Python expectation on the frozen gold fixtures, and "
    "the safety behaviours listed; it says nothing about future returns.")


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def issue_certificate(verify_path: str | Path, manifest_path: str | Path,
                      out_dir: str | Path, *,
                      coverage: dict[str, str] | None = None,
                      now: datetime | None = None) -> dict:
    """Check the conditions above; write certificate.json / certificate.md
    into ``out_dir`` only when all hold. Returns {ok, reasons, ...}."""
    verify_path, manifest_path = Path(verify_path), Path(manifest_path)
    reasons: list[str] = []
    rep = _load(verify_path)
    man = _load(manifest_path)
    if not isinstance(rep, dict):
        return {"ok": False,
                "reasons": [f"verifier report unreadable: {verify_path}"]}
    verdict = rep.get("verdict")
    if verdict not in CERTIFIABLE:
        reasons.append(f"verdict {verdict!r} is not certifiable (only "
                       f"{sorted(CERTIFIABLE)})")
    if rep.get("partial") is not False:
        reasons.append(f"verifier report is partial ({rep.get('partial')!r})")
    if rep.get("missing") != []:
        reasons.append(f"verifier report lists missing evidence: "
                       f"{rep.get('missing')!r}")
    golds = rep.get("gold") or {}
    absent = sorted(set(og.GOLD_TESTER_SYMBOLS) - set(golds))
    if absent:
        reasons.append(f"verifier report does not cover every gold: "
                       f"missing {absent}")
    for g, doc in sorted(golds.items()):
        if (doc or {}).get("result") != "MATCH" or \
                (doc or {}).get("state") != "VALID":
            reasons.append(f"{g}: result {(doc or {}).get('result')!r}, "
                           f"state {(doc or {}).get('state')!r}")
    safety = rep.get("safety") or {}
    if not safety:
        reasons.append("verifier report has no safety results")
    for name, doc in sorted(safety.items()):
        if (doc or {}).get("state") != "VALID":
            reasons.append(f"safety {name}: state {(doc or {}).get('state')!r}")
    verify_sha = _sha(verify_path)
    if not isinstance(man, dict):
        reasons.append(f"archive manifest unreadable: {manifest_path}")
    else:
        bound = (man.get("artifacts") or {}).get(VERIFY_REL)
        if bound is None:
            reasons.append(f"archive manifest does not bind {VERIFY_REL}")
        elif bound != verify_sha:
            reasons.append(f"archive manifest binds {VERIFY_REL} as "
                           f"{bound}, the report is {verify_sha}")
    if reasons:
        return {"ok": False, "verdict": verdict, "reasons": reasons}

    scope, statement = CERTIFIABLE[verdict]
    commit = ((rep.get("compile") or {}).get("source_commit_relation")
              or {}).get("recorded")
    cert = {
        "schema": SCHEMA,
        "issued_utc": (now or datetime.now(timezone.utc)).isoformat(),
        "verdict": verdict,
        "certificate_scope": scope,
        "scope_statement": statement,
        "source_commit": commit,
        "verifier": rep.get("verifier"),
        "reconciliation_verify_sha256": verify_sha,
        "archive_manifest_sha256": _sha(manifest_path),
        "golds": {g: {"result": d.get("result"), "state": d.get("state"),
                      "entry_counts": d.get("entry_counts")}
                  for g, d in sorted(golds.items())},
        "safety": {n: d.get("result") for n, d in sorted(safety.items())},
        "real_tick_coverage": dict(coverage or {}),
        "trade_source": {
            "log_sourced_legs": rep.get("log_sourced_legs") or [],
            "note": ("legs listed here were graded from the tester agent "
                     "log (no MT5 report was written for them)")},
        "claims": {"real_ticks": "none" if scope == "bar models" else "full",
                   "profitability": NO_PROFIT_CLAIM},
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "certificate.json").write_text(
        json.dumps(cert, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "certificate.md").write_text(render(cert), encoding="utf-8")
    return {"ok": True, "verdict": verdict, "certificate_scope": scope,
            "reasons": [], "certificate": str(out / "certificate.json")}


def render(cert: dict) -> str:
    lines = [
        "# AEGIS owner-gate certificate",
        "",
        f"- **Verdict:** {cert['verdict']}",
        f"- **Certificate scope:** {cert['scope_statement']}",
        f"- **Source commit:** {cert['source_commit']}",
        f"- **Issued (UTC):** {cert['issued_utc']}",
        ("- **reconciliation_verify.json sha256:** "
         f"{cert['reconciliation_verify_sha256']}"),
        ("- **archive_manifest.json sha256:** "
         f"{cert['archive_manifest_sha256']}"),
        "",
        "## Gold reconciliation",
        "",
    ]
    for g, d in cert["golds"].items():
        lines.append(f"- {g}: {d['result']} ({d['state']})")
    lines += ["", "## Safety results", ""]
    for n, r in cert["safety"].items():
        lines.append(f"- {n}: {r}")
    lines += ["", "## Real-tick coverage", ""]
    for g, c in (cert["real_tick_coverage"] or {"(not stated)": ""}).items():
        lines.append(f"- {g}: {c}")
    legs = cert["trade_source"]["log_sourced_legs"]
    lines += ["", "## Trade source", "",
              (f"- graded from the tester agent log: {', '.join(legs)}"
               if legs else "- every leg graded from an MT5 report"),
              "", "## Limits", "",
              f"- {cert['scope_statement']}",
              f"- {cert['claims']['profitability']}", ""]
    return "\n".join(lines)
