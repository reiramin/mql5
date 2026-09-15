"""mql5bot.dsl.normalize — canonical normalization + hashing.

Equivalent DSL documents must produce equivalent normalized
representations (mission §8).  Normalization is deterministic:

- enums upper-cased, timeframes canonicalized (``h1`` → ``H1``)
- indicator lists sorted by id; regime/tag lists sorted
- ``and``/``or`` children sorted by their canonical JSON (SAFE: the
  runtime evaluates pure bar-level predicates with no side effects;
  comparisons/arithmetic are never reordered)
- numbers canonicalized through ``repr`` round-trip (2.50 → 2.5)

Two hashes:

- :func:`spec_hash` — identity of a strategy VERSION: canonical
  (schema_version, strategy_id, version, semantic core).  Display
  name, description, provenance, claims, hypothesis and free-text
  metadata are NOT part of it: renaming a strategy never changes its
  identity (mission §59.1) and a source-URL edit never mutates logic
  (§59.10).
- :func:`semantic_hash` — dedup key across identities: the semantic
  core alone (mission §24).  Two specs with equal semantic hashes are
  effectively the same strategy regardless of naming.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

TF_MAP = {
    "m1": "M1", "m2": "M2", "m3": "M3", "m4": "M4", "m5": "M5",
    "m6": "M6", "m10": "M10", "m12": "M12", "m15": "M15", "m20": "M20",
    "m30": "M30", "h1": "H1", "h2": "H2", "h3": "H3", "h4": "H4",
    "h6": "H6", "h8": "H8", "h12": "H12", "d1": "D1", "w1": "W1",
    "mn": "MN1", "mn1": "MN1",
}

# spec fields that never affect trading semantics or identity
NON_SEMANTIC = {"name", "description", "source", "claims", "hypothesis",
                "metadata", "params"}


def canon_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, tight separators, repr numbers."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def _num(x) -> Any:
    """Canonical number: keep ints as ints; normalize -0.0 → 0.0."""
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if x == 0.0:
            return 0.0
        return x
    return x


def _floatify(obj):
    """Uniform numeric canonicalization: every int/float leaf becomes
    float (bools and strings untouched).  55 and 55.0 are the same
    semantics and MUST hash identically (mission §8)."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        f = float(obj)
        return 0.0 if f == 0.0 else f    # -0.0 == 0.0
    if isinstance(obj, dict):
        return {k: _floatify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floatify(v) for v in obj]
    return obj


def normalize_timeframe(tf: str) -> str:
    key = str(tf).strip().lower()
    if key in TF_MAP:
        return TF_MAP[key]
    upper = str(tf).strip().upper()
    if re.match(r"^(M|H|D|W|MN)\d+$", upper):
        return upper
    raise ValueError(f"unknown timeframe {tf!r}")


def normalize_operand(op: dict) -> dict:
    if "ambiguous" in op:
        out = {"ambiguous": op["ambiguous"]}
        if "range" in op:
            out["range"] = [_num(op["range"][0]), _num(op["range"][1])]
        return out
    (key,) = tuple(op)  # validators guarantee exactly one alternative
    if key in {"add", "sub", "mul", "div"}:
        a, b = op[key]
        return {key: [normalize_operand(a), normalize_operand(b)]}
    if key == "const":
        return {"const": _num(op[key])}
    return {key: op[key]}


def normalize_condition(cond: dict) -> dict:
    if not cond:
        # DRAFT placeholder (version 0): empty condition invents
        # nothing; such specs can never execute or promote
        return {}
    if "and" in cond or "or" in cond:
        key = "and" if "and" in cond else "or"
        # commutative + associative + side-effect-free ⇒ order-free
        children = sorted((normalize_condition(c) for c in cond[key]),
                          key=canon_json)
        return {key: children}
    if "not" in cond:
        return {"not": normalize_condition(cond["not"])}
    if "cmp" in cond:
        return {"left": normalize_operand(cond["left"]),
                "cmp": cond["cmp"].upper(),
                "right": normalize_operand(cond["right"])}
    if "cross" in cond:
        return {"cross": cond["cross"].upper(),
                "a": normalize_operand(cond["a"]),
                "b": normalize_operand(cond["b"])}
    if "rising" in cond or "falling" in cond:
        key = "rising" if "rising" in cond else "falling"
        out = {key: normalize_operand(cond[key])}
        out["n"] = int(cond.get("n", 2))
        return out
    if "within" in cond:
        return {"within": normalize_operand(cond["within"]),
                "low": _num(cond["low"]), "high": _num(cond["high"])}
    raise ValueError(f"unrecognized condition shape: {sorted(cond)}")


def _normalize_stop(stop: dict | None) -> dict | None:
    if stop is None:
        return None
    out = {"model": str(stop["model"]).lower()}
    for k in ("mult", "points", "pct"):
        if k in stop:
            out[k] = _num(stop[k])
    return out


def _norm_session(sess: dict | None) -> dict | None:
    if sess is None:
        return None
    return {"start": str(sess["start"]), "end": str(sess["end"]),
            "tz": str(sess.get("tz", "UTC"))}


def normalize_spec(spec: dict) -> dict:
    """Full normalized document (all fields, canonical forms)."""
    from .schema import SCHEMA_VERSION
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("normalize_spec: unsupported schema_version "
                         f"{spec.get('schema_version')!r}")

    market = spec["market"]
    out: dict = {
        "schema_version": SCHEMA_VERSION,
        "strategy_id": spec["strategy_id"],
        "version": int(spec["version"]),
        "market": {
            "symbol": str(market["symbol"]).upper(),
            "timeframe": normalize_timeframe(market["timeframe"]),
            "session": _norm_session(market.get("session")),
            "trading_days": (sorted(int(d) for d in
                                    market["trading_days"])
                             if market.get("trading_days") else None),
        },
        "indicators": [
            _normalize_indicator(ind)
            for ind in sorted(spec["indicators"],
                              key=lambda i: i["id"])
        ],
        "entry": {},
        "exit": {},
    }

    entry = spec["entry"]
    out["entry"] = {"mode": str(entry["mode"]).lower()}
    for key in ("long", "short", "exit_long", "exit_short"):
        if entry.get(key) is not None:
            out["entry"][key] = normalize_condition(entry[key])
    if "max_entries_per_bar" in entry:
        out["entry"]["max_entries_per_bar"] = \
            int(entry["max_entries_per_bar"])

    ex = spec.get("exit", {})
    for key in ("sl", "tp"):
        if ex.get(key) is not None:
            out["exit"][key] = _normalize_stop(ex[key])
    for key in ("trail_atr", "breakeven_atr"):
        if key in ex:
            out["exit"][key] = _num(ex[key])
    if ex.get("time_bars") is not None:
        out["exit"]["time_bars"] = int(ex["time_bars"])
    if "reversal" in ex:
        out["exit"]["reversal"] = bool(ex["reversal"])

    filters = spec.get("filters", {}) or {}
    nf: dict = {}
    for key in ("max_spread_points", "max_atr_pct"):
        if filters.get(key) is not None:
            nf[key] = _num(filters[key])
    if filters.get("cooldown_bars"):
        nf["cooldown_bars"] = int(filters["cooldown_bars"])
    if filters.get("session") is not None:
        nf["session"] = _norm_session(filters["session"])
    regime = filters.get("regime", {}) or {}
    if regime:
        nf["regime"] = {
            k: sorted(str(x).upper() for x in regime.get(k, []))
            for k in ("allowed", "preferred", "forbidden")
            if regime.get(k)
        }
    if nf:
        out["filters"] = nf

    if spec.get("risk"):
        note = spec["risk"].get("note")
        if note:
            out["risk"] = {"note": str(note)}

    params = spec.get("params", {}) or {}
    if params:
        out["params"] = {
            name: {
                "type": decl["type"],
                "default": _num(decl["default"]),
                **({"min": _num(decl["min"])} if "min" in decl else {}),
                **({"max": _num(decl["max"])} if "max" in decl else {}),
                **({"step": _num(decl["step"])} if "step" in decl else {}),
            }
            for name, decl in sorted(params.items())
        }

    # ---- non-semantic payload: normalized but excluded from hashes ----
    meta = spec.get("metadata", {}) or {}
    nm: dict = {}
    if meta.get("regime_tags"):
        nm["regime_tags"] = sorted(str(t).lower()
                                   for t in meta["regime_tags"])
    for key in ("explanation", "confidence", "author_notes"):
        if meta.get(key) is not None:
            nm[key] = meta[key]
    if meta.get("requires_codegen"):
        nm["requires_codegen"] = True
    if meta.get("missing_features"):
        nm["missing_features"] = sorted(meta["missing_features"])
    if nm:
        out["metadata"] = nm
    if spec.get("name"):
        out["name"] = str(spec["name"])
    if spec.get("description"):
        out["description"] = str(spec["description"])
    if spec.get("source"):
        out["source"] = {k: v for k, v in spec["source"].items()
                         if v is not None} or {"type": "HUMAN"}
    if spec.get("hypothesis"):
        hyp = {k: v for k, v in spec["hypothesis"].items()
               if v is not None}
        if hyp:
            out["hypothesis"] = hyp
    if spec.get("claims"):
        out["claims"] = [dict(c) for c in spec["claims"]]
    res = _floatify(out)
    res["version"] = int(spec["version"])   # identity stays integer so
    return res                              # canonical docs re-validate
                                            # (idempotency, gate §29.1)


def _normalize_indicator(ind: dict) -> dict:
    out: dict = {"id": ind["id"], "kind": str(ind["kind"]).upper()}
    from ..indicator_universe import EXTENDED_KINDS, contract
    if out["kind"] in EXTENDED_KINDS:
        ct = contract(out["kind"])
        given = {k: v for k, v in ind.items() if k in ct.param_map()}
        resolved = ct.resolve(given)          # canonical param order
        for name in sorted(resolved):         # deterministic doc order
            v = resolved[name]
            out[name] = int(v) if ct.param_map()[name].type == "int" \
                else _num(v)
        if "shift" in ind:
            out["shift"] = int(ind["shift"])
        return out
    for key in ("period", "shift", "fast", "slow", "signal"):
        if key in ind:
            out[key] = int(ind[key])
    if "dev" in ind:
        out["dev"] = _num(ind["dev"])
    if "applied" in ind:
        out["applied"] = str(ind["applied"]).lower()
    elif out["kind"] not in {"ATR", "DONCHIAN", "MACD"}:
        out["applied"] = "close"
    return out


def _semantic_core(normalized: dict) -> dict:
    return {k: v for k, v in normalized.items() if k not in NON_SEMANTIC}


def semantic_hash(normalized: dict) -> str:
    """sha256 of the semantic core (dedup key, mission §24/§59.2).
    Computed over the FLOATIFIED core so 55 and 55.0 hash equal."""
    return hashlib.sha256(
        canon_json(_floatify(_semantic_core(normalized))).encode()) \
        .hexdigest()


def dedup_hash(normalized: dict) -> str:
    """Duplicate-detection key (mission §24): the semantic core with
    identity (strategy_id, version) removed.  Equal dedup hashes ⇒
    effectively identical strategies regardless of naming/versioning;
    promotion of a duplicate becomes an explicit review decision."""
    core = _semantic_core(normalized)
    core = {k: v for k, v in core.items()
            if k not in ("strategy_id", "version")}
    return hashlib.sha256(
        canon_json(_floatify(core)).encode()).hexdigest()


def spec_hash(normalized: dict) -> str:
    """sha256 of the version identity (semantic core + id + version)."""
    core = _floatify(_semantic_core(normalized))
    return hashlib.sha256(
        canon_json(_floatify({
            "schema_version": normalized["schema_version"],
            "strategy_id": normalized["strategy_id"],
            "version": normalized["version"],
            "semantic": core})).encode()).hexdigest()
