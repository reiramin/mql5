"""mql5bot.gold_leg_inputs - the EA inputs a stage-5 tester leg must send.

MEASURED ROOT CAUSE (gate_run17 tester log): the EA started with
``InpStrategy=0, InpDslBundleFile= (empty), InpFastEma=10, InpSlowEma=30`` —
its compiled-in default strategy, not the gold strategy. STAGE 5 R5 filled
``[TesterInputs]`` from ``EA_INPUT_DEFAULTS``, but nothing fed the GOLD
strategy into the leg, so stage 8 compared two different strategies.

This module derives every decision-changing input from the gold's committed
manifest (read-only) and fails closed, naming the manifest field, for any
input it cannot derive. It never falls back to an EA default for a strategy
or risk input.

How the strategy reaches the EA. The manifest pins ``strategy_id``,
``strategy_version`` and ``spec_hash``. Exactly one committed spec under
``examples/strategies/`` must reproduce that ``spec_hash``; it is built into
the EA's executable DSL bundle and ``InpDslBundleFile`` points at it.

One transformation is unavoidable and is verified, not assumed. The EA
refuses a bundle whose market differs from the chart
(``CDslBundleLoader.MarketMatches``: exact symbol + timeframe, mql5/ is
frozen). The tester chart is the custom symbol (``EURUSD.G2``), while the
committed spec says ``EURUSD``, and the custom symbols cannot be named
``EURUSD`` (STAGE 4 R7). So the bundle is the committed spec with
``market.symbol`` set to the custom symbol and NOTHING else changed. The
module proves that by comparing the two normalized documents, and records
both hashes. The retargeted ``spec_hash`` necessarily differs from the
manifest's, because the market is part of the hash.

Staging. ``InpDslBundleFile`` is opened with ``FileOpen`` (no
``FILE_COMMON``) and the EA declares no ``#property tester_file``. Inside the
Strategy Tester that path resolves to the testing agent's own
``MQL5\\Files`` sandbox. The bundle is written there (every
``Tester\\...\\Agent-*`` directory found) and to the terminal's
``MQL5\\Files``, and each copy is sha256-checked. Whether MT5 keeps a file
placed in an agent sandbox for the next test is NOT yet measured. The EA's
own log answers it: ``generic DSL execution enabled: <strategy_id>`` means
the bundle loaded, and ``DSL bundle refused`` means it did not (INIT_FAILED,
never a silent default).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from mql5bot.mt5tester import EA_INPUT_DEFAULTS

STRATEGY_DIR = "examples/strategies"
# relative to MQL5\Files (the EA opens InpDslBundleFile there)
BUNDLE_DIR_PARTS = ("Mql5Bot", "gold_bundles")

# risk_config.mode -> ENUM_SIZING_MODE (mql5/Include/Mql5Bot/RiskManager.mqh).
# Only modes a gold manifest actually pins are mapped; any other value is
# underivable, never guessed.
SIZING_MODE_BY_MANIFEST = {"risk_percent_equity": 1}

# The EA refuses a DSL bundle when InpDslBars < 10x the longest period.
DSL_WARMUP_FACTOR = 10


def _fail(missing: str, reason: str) -> dict:
    return {"ok": False, "missing": missing, "reasons": [reason]}


def _get(doc: dict, dotted: str):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def bundle_bytes(envelope: dict) -> bytes:
    """Same serialisation as the committed parity bundles
    (tools/build_dsl_parity_golden.py)."""
    return json.dumps(envelope, indent=2, sort_keys=True).encode("utf-8")


def _find_spec(repo: Path, strategy_id: str, version: int, spec_hash: str):
    """The ONE committed spec reproducing the manifest's identity."""
    from mql5bot.dsl.errors import DslError
    from mql5bot.dsl.parse import parse_spec
    hits = []
    for path in sorted((repo / STRATEGY_DIR).glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            spec = parse_spec(doc)
        except (OSError, ValueError, DslError):
            # deliberately invalid examples cannot reproduce a gold spec_hash
            continue
        if spec.spec_hash == spec_hash:
            hits.append((path, doc, spec))
    if len(hits) != 1:
        return None, (f"{len(hits)} committed specs under {STRATEGY_DIR}/ "
                      f"reproduce spec_hash {spec_hash} (exactly 1 required)")
    path, doc, spec = hits[0]
    if spec.strategy_id != strategy_id or int(spec.version) != version:
        return None, (f"{path.name} reproduces spec_hash but is "
                      f"{spec.strategy_id} v{spec.version}, manifest pins "
                      f"{strategy_id} v{version}")
    return (path, doc, spec), None


def derive_gold_leg_inputs(repo: Path | str, manifest_path: Path | str,
                           chart_symbol: str) -> dict:
    """Derive one gold leg's EA inputs, tester deposit and DSL bundle.

    Returns ``ok=False`` with ``missing`` naming the FIRST manifest field (or
    derivation step) that fails. On success, ``inputs`` holds only the
    derived overrides, and ``sources`` maps every one of them to where it
    came from.
    """
    from mql5bot.dsl.bundle import build_bundle
    from mql5bot.dsl.parse import parse_spec
    repo = Path(repo)
    try:
        man = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail("manifest", f"manifest unreadable ({manifest_path}): "
                                 f"{exc}")
    required = ("strategy_id", "strategy_version", "spec_hash", "timeframe",
                "risk_config.mode", "risk_config.risk_percent",
                "risk_config.equity_start", "engine_config.allow_short")
    for field in required:
        if _get(man, field) is None:
            return _fail(field, f"manifest {Path(manifest_path).name} has no "
                                f"{field!r}; the leg cannot be configured "
                                "without it (no default is used)")
    mode = man["risk_config"]["mode"]
    if mode not in SIZING_MODE_BY_MANIFEST:
        return _fail("risk_config.mode",
                     f"risk_config.mode {mode!r} has no known EA sizing mode")
    allow_short = man["engine_config"]["allow_short"]
    if not isinstance(allow_short, bool):
        return _fail("engine_config.allow_short",
                     f"engine_config.allow_short {allow_short!r} is not a "
                     "boolean")

    found, why = _find_spec(repo, man["strategy_id"],
                            int(man["strategy_version"]), man["spec_hash"])
    if found is None:
        return _fail("spec_hash", why)
    spec_path, doc, spec = found
    if spec.market.timeframe != man["timeframe"]:
        return _fail("timeframe", f"spec timeframe {spec.market.timeframe} "
                                  f"!= manifest {man['timeframe']}")

    # retarget ONLY the market symbol to the tester chart, and prove it
    retarget_doc = copy.deepcopy(doc)
    retarget_doc["market"]["symbol"] = chart_symbol
    retarget = parse_spec(retarget_doc)
    same = copy.deepcopy(spec.document)
    same["market"]["symbol"] = retarget.document["market"]["symbol"]
    if same != retarget.document or \
            retarget.strategy_id != man["strategy_id"] or \
            int(retarget.version) != int(man["strategy_version"]):
        return _fail("spec_hash", "retargeting the market symbol changed "
                                  "more than market.symbol; refusing")
    envelope = build_bundle(retarget)
    raw = bundle_bytes(envelope)

    periods = [int(getattr(ind, "period", 0) or 0) for ind in spec.indicators]
    longest = max(periods) if periods else 0
    dsl_bars = int(EA_INPUT_DEFAULTS["InpDslBars"])
    if longest and dsl_bars < DSL_WARMUP_FACTOR * longest:
        return _fail("InpDslBars", f"InpDslBars={dsl_bars} < "
                                   f"{DSL_WARMUP_FACTOR}x longest period "
                                   f"{longest}; the EA would refuse the "
                                   "bundle")

    sl = _get(spec.document, "exit.sl.mult")
    tp = _get(spec.document, "exit.tp.mult")
    bundle_name = (f"{man['strategy_id']}_v{int(man['strategy_version'])}_"
                   f"{chart_symbol}.bundle.json")
    bundle_rel = "\\".join((*BUNDLE_DIR_PARTS, bundle_name))
    inputs: dict[str, object] = {
        "InpDslBundleFile": bundle_rel,
        "InpDslBars": dsl_bars,
        "InpSizingMode": SIZING_MODE_BY_MANIFEST[mode],
        "InpRiskPercent": float(man["risk_config"]["risk_percent"]),
        "InpAllowShort": allow_short,
        # the bundle's filters.session is the session rule; a second EA
        # session filter with different hours must never run beside it
        "InpUseSession": False,
    }
    sources = {
        "InpDslBundleFile": (f"manifest strategy_id/strategy_version/"
                             f"spec_hash -> {STRATEGY_DIR}/{spec_path.name}"),
        "InpDslBars": (f"EA default {dsl_bars} (checked >= "
                       f"{DSL_WARMUP_FACTOR}x longest period {longest})"),
        "InpSizingMode": f"manifest risk_config.mode={mode!r}",
        "InpRiskPercent": "manifest risk_config.risk_percent",
        "InpAllowShort": "manifest engine_config.allow_short",
        "InpUseSession": "rule: the DSL bundle carries the session filter",
    }
    if sl is not None and tp is not None:
        inputs["InpSlAtr"] = float(sl)
        inputs["InpTpAtr"] = float(tp)
        sources["InpSlAtr"] = "spec exit.sl.mult (the bundle drives stops)"
        sources["InpTpAtr"] = "spec exit.tp.mult (the bundle drives stops)"
    return {
        "ok": True, "missing": None, "reasons": [],
        "strategy_id": man["strategy_id"],
        "strategy_version": int(man["strategy_version"]),
        "manifest_spec_hash": man["spec_hash"],
        "spec_file": f"{STRATEGY_DIR}/{spec_path.name}",
        "retarget": {"from_symbol": spec.market.symbol,
                     "to_symbol": retarget.market.symbol,
                     "only_market_symbol_changed": True,
                     "bundle_spec_hash": retarget.spec_hash},
        "bundle_rel": bundle_rel,
        "bundle_sha256": hashlib.sha256(raw).hexdigest(),
        "bundle_hash": envelope["bundle_hash"],
        "bundle": envelope,
        "deposit": float(man["risk_config"]["equity_start"]),
        "inputs": inputs,
        "sources": {**sources,
                    "deposit": "manifest risk_config.equity_start"},
    }


def selector_check(inputs: dict, bundle: dict, strategy_id: str) -> dict:
    """Pre-launch assertion: the strategy selector is set and names the
    manifest's strategy."""
    path = str(inputs.get("InpDslBundleFile") or "")
    ident = (bundle or {}).get("identity") or {}
    reasons = []
    if not path:
        reasons.append("InpDslBundleFile is empty: the EA would run its "
                       "compiled-in default strategy")
    if ident.get("strategy_id") != strategy_id:
        reasons.append(f"bundle strategy_id {ident.get('strategy_id')!r} != "
                       f"manifest {strategy_id!r}")
    if strategy_id not in path:
        reasons.append(f"InpDslBundleFile {path!r} does not name "
                       f"{strategy_id!r}")
    return {"ok": not reasons, "reasons": reasons}


def stage_bundle(raw: bytes, bundle_rel: str,
                 data_folder: Path | str) -> dict:
    """Write the bundle under the terminal's MQL5\\Files AND every tester
    agent sandbox, and verify each copy's sha256."""
    root = Path(data_folder)
    parts = bundle_rel.split("\\")
    want = hashlib.sha256(raw).hexdigest()
    targets = [root / "MQL5" / "Files"]
    tester = root / "Tester"
    agents = sorted({p for p in tester.rglob("Agent-*") if p.is_dir()}) \
        if tester.is_dir() else []
    targets += [a / "MQL5" / "Files" for a in agents]
    staged, bad = [], []
    for base in targets:
        dest = base.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        got = hashlib.sha256(dest.read_bytes()).hexdigest()
        (staged if got == want else bad).append(str(dest))
    return {"ok": not bad, "sha256": want, "staged": staged, "bad": bad,
            "agent_sandboxes": [str(a) for a in agents]}


__all__ = [
    "SIZING_MODE_BY_MANIFEST",
    "bundle_bytes",
    "derive_gold_leg_inputs",
    "selector_check",
    "stage_bundle",
]
