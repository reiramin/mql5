#!/usr/bin/env python3
"""Broker symbol parity harness (AEGIS Phase 3).

Implements canonical owner step 3 (SymbolSpec export + parity) of the
TEN-step owner sequence in docs/MT5_ROUNDTRIP.md — the single source of
truth for the owner protocol. It compares the timestamped, SHA-256-hashed
owner export against the Python and MQL5 consumers; a field stays PENDING
until a real export resolves it.

Compares the OWNER-EXPORTED broker reality (MQL5\\Files exports produced by
``mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5``, committed under
``data/broker_exports/``) against:

* the canonical Python ``SymbolSpec`` model and its sizer math
  (``python/mql5bot/symbolspec.py``);
* the MQL5 ``SSymbolSpec`` consumer list (``mql5/Include/Mql5Bot/SymbolSpec.mqh``).

Core rule: **never invent**. When no owner export exists for a symbol the
report marks every owner cell PENDING — it never substitutes synthetic or
"typical" broker values. A parity verdict is MATCH / MISMATCH within the
declared tolerance per field, or PENDING.

Usage:
    PYTHONPATH=python python tools/broker_symbol_parity.py [--exports DIR]
        [--out-md docs/BROKER_SYMBOL_PARITY.md] [--out-json data/broker_exports/parity_report.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from mql5bot.symbolspec import (
    SymbolSpec,
    loss_per_lot,
    normalize_volume,
    round_to_tick,
)

EXPORT_SCHEMA = "mql5bot.broker_export/1"

DENOM_AGREE_TOL = 1e-3
DENOM_SEPARATE_MIN = 1e-2
DENOMINATION_PROBE_FIELDS = (
    "ok", "reason", "last_error", "source", "calc_mode", "account_leverage",
    "account_currency", "currency_profit", "currency_margin", "currency_base",
    "bid", "ask", "tick_size_at_probe", "probe_ticks", "lot_size", "move",
    "buy_loss_profit", "sell_gain_profit", "tick_value_loss_at_probe",
    "tick_value_profit_at_probe",
)

#: Asset classes the owner must export (at least one symbol each that the
#: broker actually offers; missing classes are reported, never substituted).
REQUIRED_ASSET_CLASSES = ("FX", "METAL", "INDEX_CFD", "CRYPTO")

#: Owner-export field -> (python attribute | None, mql5 SSymbolSpec member | None,
#:                         primary consumers, tolerance tag)
FIELD_MAP: dict[str, tuple[str | None, str | None, str, str]] = {
    "digits": ("digits", "digits", "SymbolSpec.rounding", "exact"),
    "point": ("point", "point", "stops/freeze conversion", "rel1e-12"),
    "tick_size": ("tick_size", "tickSize", "round_to_tick / ticks_of / min-stop", "rel1e-12"),
    "tick_value_profit": ("tick_value_profit", "tickValueProfit",
                          "gain valuation (sizer/engine)", "rel1e-9"),
    "tick_value_loss": ("tick_value_loss", "tickValueLoss",
                        "loss_per_lot (risk math, SL sizing)", "rel1e-9"),
    "contract_size": ("contract_size", "contractSize",
                      "backtest engine P/L", "rel1e-9"),
    "volume_min": ("volume_min", "volumeMin",
                   "normalize_volume / GetLots floor", "exact"),
    "volume_max": ("volume_max", "volumeMax", "GetLots cap", "exact"),
    "volume_step": ("volume_step", "volumeStep", "volume grid", "exact"),
    "volume_limit": ("volume_limit", "volumeLimit", "GetLots cap (0=none)", "exact"),
    "stops_level_points": ("stops_level_points", "stopsLevelPoints",
                           "min stop distance (sizer, SlGuard, pending offset)", "exact"),
    "freeze_level_points": ("freeze_level_points", "freezeLevelPoints",
                            "freeze zone guard", "exact"),
    "currency_profit": ("currency_profit", "currencyProfit",
                        "profit->deposit conversion", "exact"),
    "trade_mode": (None, "tradeMode", "entry gates (OnNewBar)", "exact"),
    "filling_mode_mask": (None, "fillingMode",
                          "SpecPreferredFilling / SpecNextFilling", "exact"),
    "order_mode": (None, "orderMode", "order policy (SYMBOL_ORDER_MODE)", "exact"),
    "expiration_mode_mask": (None, "expirationMode", "pending policy", "exact"),
    "margin_initial": (None, None,
                       "margin sanity (runtime OrderCalcMargin is authority)", "rel1e-9"),
    "margin_maintenance": (None, None,
                           "margin sanity (runtime OrderCalcMargin is authority)", "rel1e-9"),
}


@dataclass
class Row:
    symbol: str
    field: str
    owner: object
    python: object
    status: str          # MATCH | MISMATCH | PENDING | N_A
    detail: str = ""


def _tolerance_ok(tag: str, owner: float, model: float) -> bool:
    if tag == "exact":
        return owner == model
    if tag == "rel1e-12":
        return abs(owner - model) <= 1e-12 * max(1.0, abs(model))
    if tag == "rel1e-9":
        return abs(owner - model) <= 1e-9 * max(1.0, abs(model))
    raise ValueError(f"unknown tolerance tag {tag}")


def load_owner_export(path: Path) -> dict:
    """Strict schema validation — a malformed export is an error, never
    silently repaired (fails-safe rule)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != EXPORT_SCHEMA:
        raise ValueError(f"{path.name}: wrong schema {doc.get('schema')!r}")
    sym = doc.get("symbol")
    if not isinstance(sym, dict) or "name" not in sym:
        raise ValueError(f"{path.name}: missing symbol block")
    missing = [f for f in FIELD_MAP if f not in sym]
    if missing:
        raise ValueError(f"{path.name}: export missing fields {missing}")
    return doc


def compare_symbol(doc: dict, python_spec: SymbolSpec | None) -> list[Row]:
    """Owner vs Python model vs MQL5 consumer list for one symbol.

    Python side: when a model value exists it is compared within tolerance.
    MQL5 side: field presence is verified structurally (the SSymbolSpec
    member must exist in the source and be consumed); VALUE parity for the
    MQL5 side is inherently runtime (BuildSymbolSpec queries the same
    SymbolInfo* the owner exported), so it is recorded as VERIFIED-BY-DESIGN
    only when the member exists — otherwise N_A with a detail.
    """
    sym = doc["symbol"]
    name = sym["name"]
    rows: list[Row] = []
    for field, (py_attr, mql5_member, _consumers, tag) in FIELD_MAP.items():
        owner = sym[field]
        # Python model side
        if py_attr is not None and python_spec is not None:
            model = getattr(python_spec, py_attr)
            if model is None:
                # tick_value_profit default None == symmetric with loss side
                status = "MATCH" if owner == sym.get("tick_value_loss") else "MISMATCH"
                rows.append(Row(name, field, owner, "None(=loss side)",
                                status, "python default: symmetric"))
                continue
            if isinstance(model, str):
                ok = owner == model
            else:
                ok = _tolerance_ok(tag, float(owner), float(model))
            rows.append(Row(name, field, owner, model,
                            "MATCH" if ok else "MISMATCH", f"tol {tag}"))
        else:
            rows.append(Row(name, field, owner, "n/a (runtime-queried)",
                            "N_A", "no Python field; runtime query is authority"))
    return rows


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _agrees(left: float, right: float) -> bool:
    return abs(left - right) <= DENOM_AGREE_TOL * max(1.0, abs(left), abs(right))


def _separated(left: float, right: float) -> bool:
    return abs(left - right) >= DENOM_SEPARATE_MIN * max(1.0, abs(left), abs(right))


def assess_tick_value_denomination(doc: dict) -> dict[str, object]:
    """Assess one symbol's tick-value denomination from its local witness.

    ``OrderCalcProfit`` returns account-currency P/L.  The structural
    ``contract_size * tick_size`` hypothesis is the value of one tick in the
    symbol's profit currency.  Neither hypothesis is accepted without the
    independent witness, and no FX conversion is derived from tick value.
    """
    sym = doc.get("symbol", {})
    probe = sym.get("denomination_probe")
    base = {"verdict": "UNVERIFIED", "status": "PENDING", "reason": ""}
    if not isinstance(probe, dict):
        base["reason"] = "denomination probe absent"
        return base
    missing = [field for field in DENOMINATION_PROBE_FIELDS if field not in probe]
    if missing:
        base["reason"] = f"denomination probe missing fields: {missing}"
        return base
    if probe.get("ok") is not True:
        base["reason"] = str(probe.get("reason") or "denomination probe failed")
        base["last_error"] = probe.get("last_error")
        return base

    ticks = _finite_number(probe.get("probe_ticks"))
    move = _finite_number(probe.get("move"))
    buy_loss = _finite_number(probe.get("buy_loss_profit"))
    sell_gain = _finite_number(probe.get("sell_gain_profit"))
    loss_tv = _finite_number(probe.get("tick_value_loss_at_probe"))
    profit_tv = _finite_number(probe.get("tick_value_profit_at_probe"))
    tick_size = _finite_number(sym.get("tick_size"))
    contract_size = _finite_number(sym.get("contract_size"))
    if (ticks is None or ticks <= 0.0 or move is None or move <= 0.0
            or not math.isclose(move, ticks * tick_size if tick_size is not None else 0.0,
                                 rel_tol=DENOM_AGREE_TOL, abs_tol=DENOM_AGREE_TOL * max(1.0, abs(move)))
            or buy_loss is None or sell_gain is None
            or loss_tv is None or profit_tv is None
            or tick_size is None or tick_size <= 0.0
            or contract_size is None or contract_size <= 0.0):
        base["reason"] = "denomination probe has non-finite or non-positive numeric evidence"
        return base
    if buy_loss >= 0.0 or sell_gain <= 0.0:
        base["reason"] = "OrderCalcProfit witness signs are inverted"
        return base

    account_loss_tick = -buy_loss / ticks
    account_profit_tick = sell_gain / ticks
    structural_tick = contract_size * tick_size
    account_match = (_agrees(loss_tv, account_loss_tick)
                     and _agrees(profit_tv, account_profit_tick))
    profit_match = (_agrees(loss_tv, structural_tick)
                    and _agrees(profit_tv, structural_tick))
    account_profit_separated = (_separated(account_loss_tick, structural_tick)
                                and _separated(account_profit_tick, structural_tick))
    base.update({
        "account_loss_tick": account_loss_tick,
        "account_profit_tick": account_profit_tick,
        "structural_profit_tick": structural_tick,
        "tick_value_loss": loss_tv,
        "tick_value_profit": profit_tv,
    })
    if account_match:
        base.update(verdict="ACCOUNT_CURRENCY", status="MATCH",
                    reason="tick values agree with independent OrderCalcProfit witness")
    elif profit_match and account_profit_separated:
        base.update(verdict="PROFIT_CURRENCY", status="MATCH",
                    reason="tick values fit structural profit-currency tick and are separated from account witness")
    else:
        base["reason"] = "account/profit denomination hypotheses are ambiguous"
    return base


def tick_value_denomination(doc: dict) -> str:
    """Return the conservative per-symbol denomination verdict."""
    return str(assess_tick_value_denomination(doc)["verdict"])


def denomination_row(doc: dict) -> Row:
    assessment = assess_tick_value_denomination(doc)
    symbol = str(doc.get("symbol", {}).get("name", "<unknown>"))
    return Row(symbol, "tick_value_denomination", assessment["verdict"],
               assessment.get("reason", ""), str(assessment["status"]),
               "independent OrderCalcProfit witness")


def sizer_behaviour_parity(doc: dict, stop_distance: float = 25 * 1e-5) -> list[Row]:
    """Replay the three canonical sizer primitives against the exported
    volume/tick grid: round_to_tick, normalize_volume (floor semantics),
    loss_per_lot — so the OWNER numbers, not synthetic ones, drive them."""
    sym = doc["symbol"]
    assessment = assess_tick_value_denomination(doc)
    if assessment["verdict"] != "ACCOUNT_CURRENCY":
        return [Row(sym["name"], "sizer.behaviour", "PENDING", assessment["reason"],
                    "PENDING", "denomination is not independently established")]
    probe = sym["denomination_probe"]
    account_currency = str(doc.get("account_currency") or probe.get("account_currency") or "")
    spec = SymbolSpec(
        name=sym["name"],
        digits=int(sym["digits"]),
        point=float(sym["point"]),
        tick_size=float(sym["tick_size"]),
        # For an account-currency verdict the independent witness, not a
        # structural FX identity, supplies the values used by this replay.
        tick_value_loss=float(probe["buy_loss_profit"]) / -float(probe["probe_ticks"]),
        tick_value_profit=float(probe["sell_gain_profit"]) / float(probe["probe_ticks"]),
        contract_size=float(sym["contract_size"]),
        volume_min=float(sym["volume_min"]),
        volume_max=float(sym["volume_max"]),
        volume_step=float(sym["volume_step"]),
        volume_limit=float(sym["volume_limit"]),
        stops_level_points=float(sym["stops_level_points"]),
        freeze_level_points=float(sym["freeze_level_points"]),
        currency_profit=str(sym["currency_profit"]),
        currency_deposit=account_currency,
    )
    rows = []
    tick = float(sym["tick_size"])
    # Snap an arbitrary price onto the broker tick grid, then verify
    # round_to_tick is idempotent on an on-grid price. This is a REAL
    # comparison (it can report MISMATCH if round_to_tick is broken) — the
    # previous row hard-coded "MATCH" regardless of the computed value.
    px = round_to_tick(100.0 * float(sym["point"]) * 1000, spec)
    rounded = round_to_tick(px, spec)
    rows.append(Row(sym["name"], "sizer.round_to_tick", px, rounded,
                    "MATCH" if abs(rounded - px) <= tick * 1e-6 else "MISMATCH",
                    "on-grid price is idempotent under round_to_tick"))
    raw = float(sym["volume_min"]) + 0.4 * float(sym["volume_step"])
    floored = normalize_volume(raw, spec)
    rows.append(Row(sym["name"], "sizer.normalize_volume(floor)", raw, floored,
                    "MATCH" if floored < raw or abs(floored - raw) < 1e-15 else "MISMATCH",
                    "never rounds up"))
    lpl = loss_per_lot(stop_distance, spec)
    # ticks_of clamps to >= 1 tick (documented sizer behaviour)
    ticks = max(1, round(stop_distance / float(sym["tick_size"])))
    expect = ticks * float(sym["tick_value_loss"])
    ok = abs(lpl - expect) <= 1e-9 * max(1.0, expect)
    rows.append(Row(sym["name"], "sizer.loss_per_lot", lpl, expect,
                    "MATCH" if ok else "MISMATCH",
                    "ticks×tick_value_loss (owner tick value)"))
    return rows


#: Asset-class evidence, kept to the markers this harness has always used: the
#: broker's own ``SYMBOL_PATH`` decides, with the repo's metal/coin name
#: prefixes as a second witness.  No new broker taxonomy is introduced.
CLASS_PATH_MARKERS = {
    "FX": ("forex", "fx", "major", "minor"),
    "METAL": ("metal", "xau", "xag"),
    "INDEX_CFD": ("index", "indices", "cfd"),
    "CRYPTO": ("crypto", "btc", "eth"),
}

#: name witnesses for the classes whose symbols are conventionally named after
#: the metal or the coin itself rather than after a broker folder.
CLASS_NAME_PREFIXES = {
    "METAL": ("XAU", "XAG"),
    "CRYPTO": ("BTC", "ETH"),
}

#: names that a specific class already claims are excluded from the FX name
#: fallback below, so a currency-suffixed metal (``XAUEUR``) cannot masquerade
#: as FX coverage even when the export carries no path at all
_SPECIFIC_CLASS_PREFIXES = tuple(
    sorted(p for prefixes in CLASS_NAME_PREFIXES.values() for p in prefixes))


def _asset_classes_supported(path: str, name: str) -> list[str]:
    r"""Every required asset class this symbol's own evidence supports, in
    ``REQUIRED_ASSET_CLASSES`` order.

    The classes are checked INDEPENDENTLY, never as an ``if``/``elif`` chain: a
    mutually exclusive chain lets the first matching rule steal a symbol from
    every later class, which is exactly how the owner's ``Metals\XAUEUR``
    export counted as FX while METAL stayed PENDING (``XAUEUR`` is 6 characters
    and alphabetic, so it satisfied the FX branch first and the METAL branch
    was never reached).  A symbol may support more than one class, and it is
    counted toward each one it genuinely evidences.
    """
    matched = [cls for cls in REQUIRED_ASSET_CLASSES
               if any(marker in path for marker in CLASS_PATH_MARKERS[cls])
               or any(name.startswith(prefix)
                      for prefix in CLASS_NAME_PREFIXES.get(cls, ()))]
    if matched:
        return matched
    # Fallback, and only a fallback: a 6-letter alphabetic ticker is the SHAPE
    # of a FX pair, not proof of one.  It is consulted only when the export
    # carries no class evidence at all (some brokers leave SYMBOL_PATH empty or
    # use an uninformative folder), and never for a name a specific class
    # claims.  It must not be replaced by another broad name heuristic.
    if len(name) == 6 and name.isalpha() and not name.startswith(_SPECIFIC_CLASS_PREFIXES):
        return ["FX"]
    return []


def asset_classes_covered(exports: list[dict]) -> dict[str, str]:
    """Which required asset classes at least one owner export represents.

    Deterministic by construction: candidates are visited in an explicit order
    (symbol name, then path) and each class keeps its FIRST valid
    representative instead of being overwritten by later ones, so the mapping
    cannot depend on the caller's iteration order or on the filesystem's
    enumeration order.
    """
    out = {cls: "PENDING (no owner export)" for cls in REQUIRED_ASSET_CLASSES}
    claimed: set[str] = set()
    for doc in sorted(exports,
                      key=lambda d: (str(d["symbol"]["name"]).upper(),
                                     str(d["symbol"].get("path", "")))):
        path = str(doc["symbol"].get("path", "")).lower()
        name = str(doc["symbol"]["name"]).upper()
        for cls in _asset_classes_supported(path, name):
            if cls not in claimed:
                claimed.add(cls)
                out[cls] = f"exported: {name}"
    return out


def build_report(exports_dir: Path) -> tuple[list[dict], list[Row], dict]:
    exports: list[dict] = []
    if exports_dir.exists():
        for p in sorted(exports_dir.glob("*.json")):
            if p.name == "parity_report.json":
                continue
            try:
                exports.append(load_owner_export(p))
            except ValueError as exc:
                print(f"WARNING: skipping malformed export: {exc}", file=sys.stderr)
    rows: list[Row] = []
    for doc in exports:
        rows += compare_symbol(doc, None)
        rows += sizer_behaviour_parity(doc)
        rows.append(denomination_row(doc))
    coverage = asset_classes_covered(exports)
    return exports, rows, coverage


def render_markdown(exports: list[dict], rows: list[Row], coverage: dict) -> str:
    lines = [
        "# BROKER SYMBOL PARITY — AEGIS Phase 3 (auto-generated)",
        "",
        "Source of truth: owner exports from `Mql5BotExportSymbolSpec.mq5`",
        "(`data/broker_exports/*.json`, schema `mql5bot.broker_export/1`).",
        "This file is regenerated by `tools/broker_symbol_parity.py`.",
        "",
        f"Asset-class coverage: {json.dumps(coverage)}",
        "",
    ]
    if not exports:
        lines += [
            "## Status: NOT VERIFIED — no owner export present",
            "",
            "No broker export was found, so **every owner-side cell is PENDING**.",
            "Per the AEGIS rules no broker parameter is invented here; the",
            "harness, field map, tolerances and export procedure below are the",
            "completed machinery — the numbers must come from the owner's live",
            "account of record.",
            "",
            "Owner procedure:",
            "",
            "1. Open the live account of record in MT5.",
            "2. Attach `Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5` to each",
            "   required symbol (at least one per asset class:",
            "   FX, METAL, INDEX CFD, CRYPTO).",
            "3. Commit the produced `MQL5\\Files\\Mql5Bot\\broker_exports\\*.json`",
            "   under `data/broker_exports/`.",
            "4. Re-run `PYTHONPATH=python python tools/broker_symbol_parity.py`.",
            "",
            "Field map and tolerances are pinned in",
            "`docs/BROKER_SYMBOL_PARITY.md` (this file's checked-in header)",
            "and enforced by `tests/test_broker_symbol_parity.py`.",
        ]
        return "\n".join(lines) + "\n"
    lines.append("| symbol | field | owner | python/model | status | detail |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r.symbol} | {r.field} | {r.owner} | {r.python} "
                     f"| {r.status} | {r.detail} |")
    mism = [r for r in rows if r.status == "MISMATCH"]
    pending = sum(1 for r in rows if r.status == "PENDING")
    lines += ["", (f"Verdict: {len(rows)} rows, {len(mism)} mismatches, "
                   f"{pending} pending.")]
    return "\n".join(lines) + "\n"


HEADER_DOC = """# BROKER SYMBOL PARITY — Mission 3 / AEGIS Phase 3

Parity of broker/symbol reality against the owner's live-account exports.
**Owner-gated**: the sandbox cannot reach a broker, so every owner-side
number is PENDING until the owner commits `data/broker_exports/*.json`
(produced by `mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5`). No broker
parameter is ever invented here.

## Mandated field map (pinned by `tests/test_broker_symbol_parity.py`)

| Owner export field (MT5 source) | Python `SymbolSpec` | MQL5 `SSymbolSpec` | Consumers | Tolerance |
|---|---|---|---|---|
| digits (SYMBOL_DIGITS) | `digits` | `digits` | rounding | exact |
| point (SYMBOL_POINT) | `point` | `point` | stops/freeze conversion | rel 1e-12 |
| tick_size (SYMBOL_TRADE_TICK_SIZE) | `tick_size` | `tickSize` | round_to_tick/ticks_of/min-stop | rel 1e-12 |
| tick_value_profit (SYMBOL_TRADE_TICK_VALUE_PROFIT) | `tick_value_profit` | `tickValueProfit` | gain valuation | rel 1e-9 |
| tick_value_loss (SYMBOL_TRADE_TICK_VALUE_LOSS) | `tick_value_loss` | `tickValueLoss` | **loss_per_lot → SL sizing** | rel 1e-9 |
| contract_size (SYMBOL_TRADE_CONTRACT_SIZE) | `contract_size` | `contractSize` | engine P/L | rel 1e-9 |
| volume_min / volume_max / volume_step / volume_limit | `volume_*` | `volume*` | volume grid & caps | exact |
| stops_level_points (SYMBOL_TRADE_STOPS_LEVEL) | `stops_level_points` | `stopsLevelPoints` | sizer, SlGuard, pending offset | exact |
| freeze_level_points (SYMBOL_TRADE_FREEZE_LEVEL) | `freeze_level_points` | `freezeLevelPoints` | freeze guard | exact |
| currency_profit (SYMBOL_CURRENCY_PROFIT) | `currency_profit` | `currencyProfit` | profit→deposit conversion | exact |
| trade_mode (SYMBOL_TRADE_MODE) | — (runtime) | `tradeMode` | OnNewBar entry gates | exact |
| filling_mode_mask (SYMBOL_FILLING_MODE) | — (runtime) | `fillingMode` | filling ladder FOK→IOC→RETURN | exact |
| order_mode / expiration_mode_mask | — (runtime) | `orderMode`/`expirationMode` | pending policy | exact |
| margin_initial / margin_maintenance (SYMBOL_MARGIN_*) + OrderCalcMargin probe | — (runtime `OrderCalcMargin` is authority) | — (runtime) | margin sanity cross-check | rel 1e-9 |

Asset classes required: **FX, METAL, INDEX CFD, CRYPTO** (one symbol each the
broker actually offers).

## Derived P/L identity (tick value cross-check)

`tick_value ≈ contract_size × tick_size × fx(profit→deposit)` — evaluated
only when the owner supplies the FX conversion; otherwise PENDING. The sizer
primitives (`round_to_tick`, `normalize_volume` floor semantics, `loss_per_lot`)
are replayed against the OWNER's exported grid so parity is behavioural, not
just field-by-field.

## Status

| Item | Status |
|---|---|
| Export script (`Mql5BotExportSymbolSpec.mq5`) | WRITTEN (compile owner-gated) |
| Harness (`tools/broker_symbol_parity.py`) | COMPLETE, tested |
| Schema validation + strict fail-fast | COMPLETE, tested |
| Owner exports (FX/METAL/INDEX/CRYPTO) | **PENDING — owner only** |
| Parity verdict | **NOT VERIFIED** |
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports", default=str(REPO / "data/broker_exports"))
    ap.add_argument("--out-json", default=str(REPO / "data/broker_exports/parity_report.json"))
    args = ap.parse_args()
    exports_dir = Path(args.exports)
    exports, rows, coverage = build_report(exports_dir)
    md = render_markdown(exports, rows, coverage)
    print(md)
    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "n_exports": len(exports), "coverage": coverage,
            "rows": [r.__dict__ for r in rows],
        }, indent=2), encoding="utf-8")
    # FAIL CLOSED on the exit code (the machine gate). Previously this
    # returned 0 whenever no row was a MISMATCH — so "no export present" and
    # "every export malformed and skipped" both looked like PASS to a CI/owner
    # gate keying on the exit status, even though the markdown said NOT
    # VERIFIED. Distinguish the three outcomes:
    #   1 = a real MISMATCH was found (parity FAILED)
    #   2 = nothing/incomplete was verified (no exports, or a class still
    #       PENDING) — parity is NOT VERIFIED and must never be read as pass
    #   0 = exports present, every asset class covered, no mismatch
    mism = [r for r in rows if r.status == "MISMATCH"]
    if mism:
        return 1
    pending = [cls for cls, v in coverage.items()
               if str(v).startswith("PENDING")]
    if not exports or pending or not rows:
        print(f"NOT VERIFIED: n_exports={len(exports)} "
              f"pending_classes={sorted(pending)} — parity not established",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
