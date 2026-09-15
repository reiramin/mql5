"""mql5bot.dsl.parse — document → validated, normalized StrategySpec.

Pipeline (all deterministic):

    raw dict/JSON
      → structural validation   (schema.py: strict, unknown keys = error)
      → normalization           (normalize.py: canonical forms + sorting)
      → param resolution        ({"param": name} → declared default or
                                 an explicitly supplied override)
      → ambiguity collection    ({"ambiguous": name, "range": [lo,hi]}
                                 stays symbolic; the runtime refuses
                                 such specs — mission §10)
      → reference checks        (every {"ind": id} exists)
      → StrategySpec (frozen) + spec_hash + semantic_hash

Draft-vs-final rule: a spec containing ambiguities parses fine (so it
can be shown, diffed, stored) but ``spec.executable`` is False and the
runtime refuses it.  Nothing is auto-defaulted behind the user's back.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import schema as schema_mod
from .errors import UnknownReference
from .model import (
    EntrySpec,
    ExitSpec,
    Filters,
    IndicatorDef,
    MarketSpec,
    StopModel,
    StrategySpec,
)
from .normalize import _num, dedup_hash, normalize_spec, semantic_hash, spec_hash

# ------------------------------------------------------------ document IO


def load_document(path: str | Path) -> dict:
    raw = Path(path).read_text()
    schema_mod.validate_document_size(raw)
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise schema_mod.SchemaInvalid(f"invalid JSON: {e}") from e
    return doc


# ------------------------------------------------------------ param walk


def _walk_operands(node: dict, fn, *, allow_empty: bool = False) -> dict:
    """Rebuild a condition tree applying ``fn`` to every operand.
    ``allow_empty`` passes an empty DRAFT placeholder through
    unchanged (version 0 only — never executable)."""
    if not node and allow_empty:
        return {}
    if "and" in node or "or" in node:
        key = "and" if "and" in node else "or"
        return {key: [_walk_operands(c, fn) for c in node[key]]}
    if "not" in node:
        return {"not": _walk_operands(node["not"], fn)}
    if "cmp" in node:
        return {"left": fn(node["left"]), "cmp": node["cmp"],
                "right": fn(node["right"])}
    if "cross" in node:
        return {"cross": node["cross"], "a": fn(node["a"]),
                "b": fn(node["b"])}
    if "rising" in node or "falling" in node:
        key = "rising" if "rising" in node else "falling"
        out = {key: fn(node[key]), "n": node.get("n", 2)}
        return out
    if "within" in node:
        return {"within": fn(node["within"]), "low": node["low"],
                "high": node["high"]}
    if not node and allow_empty:
        return {}
    raise ValueError(f"unrecognized condition: {sorted(node)}")


def _walk_stops(doc: dict, fn) -> dict:
    out = dict(doc)
    exit_ = dict(out.get("exit", {}))
    for key in ("sl", "tp"):
        if exit_.get(key) is not None:
            exit_[key] = fn(exit_[key])
    if exit_:
        out["exit"] = exit_
    return out


def _resolve_in_operand(op: dict, params: dict, ambiguities: list,
                        path: str) -> dict:
    if "ambiguous" in op:
        # stays symbolic; the runtime refuses such specs (drafts never
        # run — mission §10)
        ambiguities.append({"name": op["ambiguous"], "path": path,
                            "range": list(op.get("range") or [])
                            if op.get("range") else None})
        return dict(op)
    (key,) = tuple(op)
    if key in {"add", "sub", "mul", "div"}:
        a, b = op[key]
        return {key: [
            _resolve_in_operand(a, params, ambiguities,
                                f"{path}.{key}[0]"),
            _resolve_in_operand(b, params, ambiguities,
                                f"{path}.{key}[1]")]}
    if key == "param":
        name = op["param"]
        if name in params:
            return {"const": _num(params[name]["default"])}
        raise UnknownReference(
            f"param {name!r} has no declaration with a default",
            path=path)
    return op


class _Resolver:
    def __init__(self, params: dict):
        self.params = params
        self.ambiguities: list = []

    def operand(self, op: dict, path: str) -> dict:
        return _resolve_in_operand(op, self.params, self.ambiguities,
                                   path)

    def condition(self, cond: dict, path: str) -> dict:
        return _walk_operands(cond, lambda op: self.operand(op, path))

    def stop(self, stop: dict) -> dict:
        out = dict(stop)
        for key in ("mult", "points", "pct"):
            if key in out:
                v = out[key]
                if isinstance(v, dict) and "param" in v:
                    name = v["param"]
                    if name in self.params:
                        out[key] = _num(self.params[name]["default"])
                    else:
                        raise UnknownReference(
                            f"param {name!r} has no declaration",
                            path=f"exit.{key}")
                elif isinstance(v, dict) and "ambiguous" in v:
                    self.ambiguities.append(
                        {"name": v["ambiguous"],
                         "path": f"exit.{key}",
                         "range": list(v.get("range") or []) or None})
        return out


# ------------------------------------------------------------ lints


def _semantic_lints(doc: dict) -> list[str]:
    """Cheap semantic lints (mission §10.2 SPEC). Precision-critical
    ones (lookahead, contradictions) are structural by construction."""
    lints: list[str] = []
    exit_ = doc.get("exit", {}) or {}
    if exit_.get("sl") is None:
        lints.append("MISSING_SL: no stop-loss model defined — every "
                     "position must have an SL (DECISIONS §4.2)")
    if exit_.get("sl") and exit_.get("tp"):
        def val(s):
            return (s.get("mult") if s["model"] == "atr"
                    else s.get("points") if s["model"] == "points"
                    else s.get("pct"))
        if val(exit_["sl"]) and val(exit_["tp"]) \
                and exit_["sl"]["model"] == exit_["tp"]["model"] \
                and val(exit_["tp"]) < val(exit_["sl"]):
            lints.append("UNREALISTIC_TP_SL: TP is closer than SL "
                         "(risk multiple < 1) — allowed but flagged")
    return lints


# ------------------------------------------------------------ main entry


def parse_spec(doc: dict, *, overrides: dict | None = None
               ) -> StrategySpec:
    """Parse + validate + normalize.  ``overrides`` supplies explicit
    values for ``{"param": name}`` references without a declared
    default (deterministic resolution at the boundary; the resolved
    document is what gets hashed)."""
    schema_mod.validate_spec(doc)

    params = dict(doc.get("params", {}) or {})
    # apply declared defaults as the resolution source
    resolved = json.loads(json.dumps(doc))          # deep copy
    resolver = _Resolver(params)
    if overrides:
        # precedence: explicit override > declared default
        resolver.params = {
            **{k: {"default": v} for k, v in params.items()},
            **{k: {"default": v} for k, v in overrides.items()}}

    is_draft = doc.get("version") == 0
    entry = resolved.get("entry", {})
    for key in ("long", "short", "exit_long", "exit_short"):
        if entry.get(key) is not None:
            if entry[key] == {} and is_draft:
                continue          # DRAFT placeholder invents nothing
            entry[key] = resolver.condition(entry[key], f"entry.{key}")
    resolved["entry"] = entry
    resolved = _walk_stops(resolved, resolver.stop)

    normalized = normalize_spec(resolved)

    # reference check: every operand indicator exists
    from ..indicator_universe import EXTENDED_KINDS as EXTENDED
    from ..indicator_universe import EXTENDED_KINDS as _EXT
    ind_ids = {i["id"] for i in normalized["indicators"]}

    def check_operand(op, path):
        if "ambiguous" in op:
            return  # symbolic: unresolved values cannot reference data
        (key,) = tuple(op)
        if key == "ind":
            name = op[key]
            base = name.split("__", 1)[0]
            if name not in ind_ids and base not in ind_ids:
                raise UnknownReference(
                    f"operand references undefined indicator {name!r}; "
                    f"defined: {sorted(ind_ids)}", path=path)
            if name not in ind_ids:
                # derived output: suffix must exist for the base kind
                kind = next(i["kind"] for i in normalized["indicators"]
                            if i["id"] == base)
                suffix = name.split("__", 1)[1]
                if kind in {"BBANDS", "MACD", "DONCHIAN"}:
                    allowed = {"BBANDS": {"mid", "upper", "lower"},
                               "MACD": {"line", "signal"},
                               "DONCHIAN": {"upper", "lower"}}[kind]
                else:
                    from ..indicator_universe import contract as _ic2
                    allowed = set(_ic2(kind).outputs) \
                        if kind in EXTENDED else set()
                if suffix not in allowed:
                    raise UnknownReference(
                        f"{kind} indicator {base!r} has no output "
                        f"{suffix!r}; outputs: {sorted(allowed)}",
                        path=path)
        if key in {"add", "sub", "mul", "div"}:
            check_operand(op[key][0], f"{path}.{key}[0]")
            check_operand(op[key][1], f"{path}.{key}[1]")

    def check_condition(cond, path):
        if "and" in cond or "or" in cond:
            key = "and" if "and" in cond else "or"
            for i, c in enumerate(cond[key]):
                check_condition(c, f"{path}.{key}[{i}]")
        elif "not" in cond:
            check_condition(cond["not"], f"{path}.not")
        elif "cmp" in cond:
            check_operand(cond["left"], f"{path}.left")
            check_operand(cond["right"], f"{path}.right")
        elif "cross" in cond:
            check_operand(cond["a"], f"{path}.a")
            check_operand(cond["b"], f"{path}.b")
        elif "rising" in cond or "falling" in cond:
            key = "rising" if "rising" in cond else "falling"
            check_operand(cond[key], f"{path}.{key}")
        elif "within" in cond:
            check_operand(cond["within"], f"{path}.within")

    for key in ("long", "short", "exit_long", "exit_short"):
        if normalized["entry"].get(key) is not None:
            check_condition(normalized["entry"][key], f"entry.{key}")

    # build the frozen model
    indicators = tuple(
        IndicatorDef(
            id=i["id"], kind=i["kind"],
            period=int(i.get("period", 14)),
            applied=i.get("applied", "close"),
            shift=int(i.get("shift", 0)),
            dev=float(i.get("dev", 2.0)),
            fast=int(i.get("fast", 12)),
            slow=int(i.get("slow", 26)),
            signal=int(i.get("signal", 9)),
            params={} if i["kind"] not in _EXT else
            {k: v for k, v in i.items()
             if k not in ("id", "kind", "shift", "applied")})
        for i in normalized["indicators"])

    e = normalized["entry"]

    def stop_of(key):
        s = normalized.get("exit", {}).get(key)
        if s is None:
            return None
        value = (s.get("mult") if s["model"] == "atr"
                 else s.get("points") if s["model"] == "points"
                 else s.get("pct"))
        return StopModel(model=s["model"], value=float(value))

    ex = normalized.get("exit", {}) or {}
    exit_spec = ExitSpec(
        sl=stop_of("sl"), tp=stop_of("tp"),
        trail_atr=float(ex.get("trail_atr", 0.0)),
        breakeven_atr=float(ex.get("breakeven_atr", 0.0)),
        time_bars=ex.get("time_bars"),
        reversal=bool(ex.get("reversal", False)))

    flt = normalized.get("filters", {}) or {}
    sess = flt.get("session")
    filters = Filters(
        max_spread_points=flt.get("max_spread_points"),
        max_atr_pct=flt.get("max_atr_pct"),
        cooldown_bars=int(flt.get("cooldown_bars", 0)),
        session=((sess["start"], sess["end"],
                  sess.get("tz", "UTC")) if sess else None),
        regime_forbidden=tuple(
            flt.get("regime", {}).get("forbidden", ())),
        regime_allowed=tuple(flt.get("regime", {}).get("allowed", ())),
        regime_preferred=tuple(
            flt.get("regime", {}).get("preferred", ())))

    mk = normalized["market"]
    market = MarketSpec(
        symbol=mk["symbol"], timeframe=mk["timeframe"],
        session=mk.get("session"),
        trading_days=tuple(mk.get("trading_days") or ()))

    return StrategySpec(
        strategy_id=normalized["strategy_id"],
        version=int(normalized["version"]),
        document=normalized,
        indicators=indicators,
        entry=EntrySpec(mode=e["mode"], long=e.get("long"),
                        short=e.get("short"),
                        exit_long=e.get("exit_long"),
                        exit_short=e.get("exit_short")),
        exit=exit_spec,
        filters=filters,
        market=market,
        name=normalized.get("name", ""),
        description=normalized.get("description", ""),
        source=normalized.get("source", {}),
        hypothesis=normalized.get("hypothesis", {}),
        claims=tuple(normalized.get("claims", ())),
        metadata=normalized.get("metadata", {}),
        param_decls=dict(normalized.get("params", {})),
        ambiguities=tuple(resolver.ambiguities),
        spec_hash=spec_hash(normalized),
        semantic_hash=semantic_hash(normalized),
        dedup_hash=dedup_hash(normalized))


def lint_spec(doc: dict) -> list[str]:
    """Non-fatal semantic lints for the UI/review flow."""
    return _semantic_lints(doc)


def parse_file(path: str | Path, *, overrides: dict | None = None
               ) -> StrategySpec:
    return parse_spec(load_document(path), overrides=overrides)
