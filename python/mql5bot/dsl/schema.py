"""mql5bot.dsl.schema — structural validation of strategy specs.

The authoritative validator for ``schemas/strategy.schema.json``.
Deterministic, dependency-free, and strict: unknown keys anywhere are
ERRORS (never silently ignored), every violation reports a stable
machine code and a JSON path.  Malformed specs are rejected whole —
they are never repaired into executable behavior.

Size limits (mission §43) are enforced here so a pathological
document cannot even reach the parser.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import LimitExceeded, SchemaInvalid

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" \
    / "strategy.schema.json"

# Resource limits (mission §43) — configurable at the Factory layer
# later; these are the parser-level hard bounds.
MAX_DOC_BYTES = 256 * 1024
MAX_DEPTH = 32
MAX_CONDITION_NODES = 512
MAX_INDICATORS = 32

SCHEMA_VERSION = "1.0"

STRATEGY_ID_RE = r"^[a-z][a-z0-9_]{2,63}$"
INDICATOR_ID_RE = r"^[a-z][a-z0-9_]{0,31}$"

INDICATOR_KINDS = {"EMA", "SMA", "RSI", "ATR", "BBANDS", "MACD",
                   "DONCHIAN", "HIGHEST", "LOWEST"}
# registry-driven universe (mission §8/§9): new kinds are validated
# from their contracts; baseline kinds keep the exact rules below
try:
    from ..indicator_universe import EXTENDED_KINDS
    from ..indicator_universe import contract as _ic
    REGISTRY_KINDS = frozenset(EXTENDED_KINDS)
    INDICATOR_KINDS = INDICATOR_KINDS | REGISTRY_KINDS
except (ImportError, KeyError):                # pragma: no cover
    REGISTRY_KINDS = frozenset()
PRICE_FIELDS = {"open", "high", "low", "close"}
COMPARATORS = {"GT", "GE", "LT", "LE", "EQ", "NE"}
SOURCE_TYPES = {"HUMAN", "COMMUNITY", "TRADINGVIEW", "ARTICLE", "PAPER",
                "BOOK", "USER_TEXT", "USER_VOICE", "AI_GENERATED",
                "MUTATION_OF_EXISTING", "RESEARCH_DISCOVERY"}
TIMEFRAMES = {"M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15",
              "M20", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12",
              "D1", "W1", "MN1"}

# Condition keys grouped by the node shape they select.
CONDITION_ALTERNATIVES = ("and", "or", "not", "cmp", "cross", "rising",
                          "falling", "within")
OPERAND_ALTERNATIVES = ("ind", "price", "const", "param", "ambiguous",
                        "add", "sub", "mul", "div")


def load_schema_file() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _as_int(v, path: str, what: str, lo=None, hi=None) -> int:
    """Strict-integer check tolerant of INTEGRAL floats (the canonical
    document floatifies numeric leaves; re-validation must stay
    idempotent, gate §29.1).  10.0 passes as 10; 10.5 is rejected."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) \
            or (isinstance(v, float) and not v.is_integer()):
        _fail(path, f"{what} must be an integer"
              + (f" in [{lo}, {hi}]" if lo is not None else ""))
    iv = int(v)
    if lo is not None and not lo <= iv <= hi:
        _fail(path, f"{what} must be an integer in [{lo}, {hi}]")
    return iv


def _fail(path: str, msg: str):
    raise SchemaInvalid(msg, path=path)


def _check_type(value, types: tuple, path: str, what: str):
    if not isinstance(value, types):
        _fail(path, f"{what} must be {' or '.join(types)}, "
                    f"got {type(value).__name__}")


def _keys(obj, allowed: set, path: str):
    extra = set(obj) - allowed
    if extra:
        _fail(path, f"unknown key(s) {sorted(extra)}; allowed: "
                    f"{sorted(allowed)}")


def _number(value, path: str, what: str = "value") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, f"{what} must be a number")
    import math
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        _fail(path, f"{what} must be finite (no NaN/inf)")
    return v


def validate_document_size(raw: bytes | str) -> None:
    n = len(raw.encode("utf-8") if isinstance(raw, str) else raw)
    if n > MAX_DOC_BYTES:
        raise LimitExceeded(
            f"strategy document is {n} bytes; hard limit {MAX_DOC_BYTES}")


def validate_condition(cond, path: str, *, depth: int = 0,
                       counter: list | None = None) -> None:
    """Structural walk over a condition tree (dicts only, strict keys)."""
    if depth > MAX_DEPTH:
        raise LimitExceeded(f"condition nesting deeper than {MAX_DEPTH}",
                            path=path)
    if counter is not None:
        counter[0] += 1
        if counter[0] > MAX_CONDITION_NODES:
            raise LimitExceeded(
                f"more than {MAX_CONDITION_NODES} condition nodes",
                path=path)
    _check_type(cond, dict, path, "condition")
    keys = set(cond)
    if len(keys & set(CONDITION_ALTERNATIVES)) != 1:
        _fail(path, "condition needs exactly one of "
             f"{CONDITION_ALTERNATIVES}, got {sorted(keys)}")

    def sub(node, p):
        validate_condition(node, p, depth=depth + 1, counter=counter)

    if "and" in cond or "or" in cond:
        key = "and" if "and" in cond else "or"
        _keys(cond, {key}, path)
        arr = cond[key]
        _check_type(arr, (list,), path, f"{key} operand list")
        if len(arr) < 2:
            _fail(f"{path}.{key}",
                  f"{key} needs at least 2 operands (use a single "
                  "condition directly)")
        for i, c in enumerate(arr):
            sub(c, f"{path}.{key}[{i}]")
    elif "not" in cond:
        _keys(cond, {"not"}, path)
        sub(cond["not"], f"{path}.not")
    elif "cmp" in cond:
        _keys(cond, {"left", "cmp", "right"}, path)
        if cond["cmp"] not in COMPARATORS:
            _fail(f"{path}.cmp", f"comparator must be one of "
                  f"{sorted(COMPARATORS)}")
        validate_operand(cond.get("left"), f"{path}.left")
        validate_operand(cond.get("right"), f"{path}.right")
    elif "cross" in cond:
        _keys(cond, {"cross", "a", "b"}, path)
        if cond["cross"] not in {"ABOVE", "BELOW"}:
            _fail(f"{path}.cross", "cross must be ABOVE or BELOW")
        validate_operand(cond.get("a"), f"{path}.a")
        validate_operand(cond.get("b"), f"{path}.b")
    elif "rising" in cond or "falling" in cond:
        key = "rising" if "rising" in cond else "falling"
        _keys(cond, {key, "n"}, path)
        validate_operand(cond[key], f"{path}.{key}")
        n = cond.get("n", 2)
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            _fail(f"{path}.n", f"{key} needs integer n >= 1")
    elif "within" in cond:
        _keys(cond, {"within", "low", "high"}, path)
        validate_operand(cond["within"], f"{path}.within")
        lo = _number(cond.get("low"), f"{path}.low", "low")
        hi = _number(cond.get("high"), f"{path}.high", "high")
        if lo > hi:
            _fail(path, f"within: low {lo} > high {hi}")


def validate_operand(op, path: str, *, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise LimitExceeded(f"operand nesting deeper than {MAX_DEPTH}",
                            path=path)
    _check_type(op, dict, path, "operand")
    keys = set(op)
    if len(keys & set(OPERAND_ALTERNATIVES)) != 1:
        _fail(path, "operand needs exactly one of "
              f"{OPERAND_ALTERNATIVES}, got {sorted(keys)}")
    first = next(k for k in OPERAND_ALTERNATIVES if k in op)
    allowed_keys = {first} | (
        {"range"} if first == "ambiguous" else set())
    _keys(op, allowed_keys, path)
    if first == "ind":
        import re
        if not re.match(INDICATOR_ID_RE, str(op["ind"])):
            _fail(path, f"indicator id {op['ind']!r} malformed")
    elif first == "price":
        if op["price"] not in PRICE_FIELDS:
            _fail(path, f"price must be one of {sorted(PRICE_FIELDS)}")
    elif first == "const":
        _number(op["const"], path, "const")
    elif first == "param":
        import re
        if not re.match(INDICATOR_ID_RE, str(op["param"])):
            _fail(path, f"param name {op['param']!r} malformed")
    elif first == "ambiguous":
        _check_type(op["ambiguous"], (str,), path, "ambiguous name")
        if "range" in op:
            rng = op["range"]
            _check_type(rng, (list,), f"{path}.range", "range")
            if len(rng) != 2:
                _fail(f"{path}.range", "range needs [lo, hi]")
            lo = _number(rng[0], f"{path}.range[0]", "range lo")
            hi = _number(rng[1], f"{path}.range[1]", "range hi")
            if lo > hi:
                _fail(f"{path}.range", f"range lo {lo} > hi {hi}")
    else:  # arithmetic
        arr = op[first]
        _check_type(arr, (list,), path, f"{first} operand pair")
        if len(arr) != 2:
            _fail(path, f"{first} needs exactly 2 operands")
        validate_operand(arr[0], f"{path}.{first}[0]", depth=depth + 1)
        validate_operand(arr[1], f"{path}.{first}[1]", depth=depth + 1)


def validate_indicator(ind: dict, path: str) -> None:
    _check_type(ind, dict, path, "indicator")
    import re
    if not re.match(INDICATOR_ID_RE, str(ind.get("id", ""))):
        _fail(f"{path}.id", f"indicator id {ind.get('id')!r} malformed")
    kind = ind.get("kind")
    if kind in REGISTRY_KINDS:
        # registry-driven universe (mission §8/§9): contract-validated
        ct = _ic(kind)
        unknown = set(ind) - {"id", "kind", "shift"} - set(ct.param_map())
        if unknown:
            _fail(path, f"unknown parameters for {kind}: {sorted(unknown)}")
        given = {k: v for k, v in ind.items() if k in ct.param_map()}
        for err in ct.validate(given):
            _fail(path, f"{kind}: {err}")
        return
    _keys(ind, {"id", "kind", "period", "applied", "shift", "dev",
                "fast", "slow", "signal"}, path)
    if kind not in INDICATOR_KINDS:
        _fail(f"{path}.kind", f"unsupported indicator {kind!r}; "
              f"supported: {sorted(INDICATOR_KINDS)}")
    needs_period = kind in {"EMA", "SMA", "RSI", "ATR", "BBANDS",
                            "DONCHIAN", "HIGHEST", "LOWEST"}
    if needs_period and "period" not in ind:
        _fail(path, f"{kind} requires period")
    if "period" in ind:
        _as_int(ind["period"], f"{path}.period", "period", 1, 5000)
    if kind == "BBANDS" and "dev" in ind:
        _number(ind["dev"], f"{path}.dev", "dev")
    if kind == "MACD":
        for k in ("fast", "slow", "signal"):
            if k not in ind:
                _fail(path, f"MACD requires {k}")
            _as_int(ind[k], f"{path}.{k}", f"MACD {k}", 1, 5000)
        if ind["fast"] >= ind["slow"]:
            _fail(path, "MACD fast must be < slow")
    if "applied" in ind and ind["applied"] not in PRICE_FIELDS:
        _fail(f"{path}.applied",
              f"applied must be one of {sorted(PRICE_FIELDS)}")
    if kind in {"ATR", "DONCHIAN"} and "applied" in ind:
        _fail(f"{path}.applied", f"{kind} is computed from high/low/close")
    if "shift" in ind:
        _as_int(ind["shift"], f"{path}.shift", "shift", 0, 10**6)


def validate_stop(model, path: str) -> None:
    if model is None:
        return
    _check_type(model, dict, path, "stop model")
    _keys(model, {"model", "mult", "points", "pct"}, path)
    kind = model.get("model")
    if kind == "atr":
        _number(model.get("mult"), f"{path}.mult", "atr mult")
    elif kind == "points":
        _number(model.get("points"), f"{path}.points", "points")
    elif kind == "percent":
        _number(model.get("pct"), f"{path}.pct", "percent")
    else:
        _fail(f"{path}.model", "stop model must be atr|points|percent")


def validate_spec(spec: dict) -> None:
    """Validate a full strategy document. Raises SchemaInvalid /
    LimitExceeded with precise paths. Returns nothing (valid or raise)."""
    if not isinstance(spec, dict):
        _fail("", "strategy document must be a JSON object")
    _keys(spec, {"schema_version", "strategy_id", "version", "name",
                 "description", "source", "hypothesis", "claims",
                 "market", "indicators", "entry", "exit", "filters",
                 "risk", "metadata", "params"}, "")
    if spec.get("schema_version") != SCHEMA_VERSION:
        _fail("schema_version",
              f"unsupported schema_version {spec.get('schema_version')!r}; "
              f"this validator speaks {SCHEMA_VERSION!r}")
    import re
    sid = spec.get("strategy_id")
    if not isinstance(sid, str) or not re.match(STRATEGY_ID_RE, sid):
        _fail("strategy_id", f"strategy_id {sid!r} must match "
              f"{STRATEGY_ID_RE}")
    ver = spec.get("version")
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 0:
        _fail("version", "version must be a non-negative integer "
              "(0 = DRAFT: ambiguous, never executable)")

    for key in ("name", "description"):
        if key in spec and not isinstance(spec[key], str):
            _fail(key, f"{key} must be a string")

    src = spec.get("source", {})
    if src is not None:
        _check_type(src, dict, "source", "source")
        _keys(src, {"type", "url", "author", "platform", "retrieved_at",
                    "license_note", "reference", "notes"}, "source")
        if "type" in src and src["type"] not in SOURCE_TYPES:
            _fail("source.type",
                  f"source type {src['type']!r} not in {sorted(SOURCE_TYPES)}")

    market = spec.get("market")
    _check_type(market, dict, "market", "market")
    _keys(market, {"symbol", "timeframe", "session", "trading_days"},
          "market")
    if not isinstance(market.get("symbol"), str) \
            or not market.get("symbol"):
        _fail("market.symbol", "market.symbol required")
    tf = str(market.get("timeframe", "")).upper()
    if tf not in TIMEFRAMES:
        _fail("market.timeframe",
              f"timeframe {market.get('timeframe')!r} not in "
              f"{sorted(TIMEFRAMES)}")
    days = market.get("trading_days")
    if days is not None:
        _check_type(days, (list,), "market.trading_days", "trading_days")
        for d in days:
            _as_int(d, "market.trading_days", "trading day", 0, 6)

    inds = spec.get("indicators")
    _check_type(inds, (list,), "indicators", "indicators")
    if not inds and spec.get("version") != 0:
        # version 0 (DRAFT) may carry zero indicators — a placeholder
        # draft invents nothing; it can never execute or promote
        _fail("indicators", "at least one indicator is required")
    if len(inds) > MAX_INDICATORS:
        raise LimitExceeded(
            f"{len(inds)} indicators exceeds MAX_INDICATORS="
            f"{MAX_INDICATORS}", path="indicators")
    seen_ids: set[str] = set()
    for i, ind in enumerate(inds):
        validate_indicator(ind, f"indicators[{i}]")
        if ind["id"] in seen_ids:
            _fail(f"indicators[{i}].id", f"duplicate id {ind['id']!r}")
        seen_ids.add(ind["id"])

    entry = spec.get("entry")
    _check_type(entry, dict, "entry", "entry")
    _keys(entry, {"mode", "long", "short", "exit_long", "exit_short",
                  "max_entries_per_bar"}, "entry")
    mode = entry.get("mode")
    if mode not in {"state", "instant"}:
        _fail("entry.mode", f"entry mode {mode!r} must be 'state' or "
              "'instant'")
    if mode == "state" and ("long" not in entry or "short" not in entry):
        _fail("entry", "state mode requires both long and short entry "
              "conditions (the position persists until the opposite "
              "entry or an exit condition)")
    if mode == "instant" and ("long" not in entry and "short" not in entry):
        _fail("entry", "instant mode requires at least one of long/short")
    is_draft = spec.get("version") == 0
    counter = [0]
    for key in ("long", "short", "exit_long", "exit_short"):
        if entry.get(key) is None:
            continue
        if entry[key] == {} and is_draft:
            # DRAFT placeholder: an empty condition invents nothing;
            # version 0 can never execute or promote
            continue
        validate_condition(entry[key], f"entry.{key}", counter=counter)

    exit_ = spec.get("exit", {})
    _check_type(exit_, dict, "exit", "exit")
    _keys(exit_, {"sl", "tp", "trail_atr", "breakeven_atr", "time_bars",
                  "reversal"}, "exit")
    validate_stop(exit_.get("sl"), "exit.sl")
    validate_stop(exit_.get("tp"), "exit.tp")
    for key in ("trail_atr", "breakeven_atr"):
        if key in exit_:
            v = _number(exit_[key], f"exit.{key}", key)
            if v < 0:
                _fail(f"exit.{key}", f"{key} must be >= 0")
    if "time_bars" in exit_ and exit_["time_bars"] is not None:
        _as_int(exit_["time_bars"], "exit.time_bars", "time_bars", 1,
                10**6)

    filters = spec.get("filters", {})
    if filters is not None:
        _check_type(filters, dict, "filters", "filters")
        _keys(filters, {"max_spread_points", "max_atr_pct",
                        "cooldown_bars", "session", "regime", "news",
                        "correlation"}, "filters")
        if filters.get("news") is not None:
            _fail("filters.news",
                  "news filter is reserved (external feed) in schema 1.0 "
                  "— declare it via metadata.missing_features instead")
        if filters.get("correlation") is not None:
            _fail("filters.correlation",
                  "correlation is a portfolio-layer concern (Meta), not "
                  "a strategy filter in schema 1.0")
        for key in ("max_spread_points", "max_atr_pct"):
            if filters.get(key) is not None:
                _number(filters[key], f"filters.{key}", key)
        cb = filters.get("cooldown_bars", 0)
        if isinstance(cb, bool) or not isinstance(cb, int) or cb < 0:
            _fail("filters.cooldown_bars",
                  "cooldown_bars must be a non-negative integer")
        if filters.get("session") is not None:
            sess = filters["session"]
            _check_type(sess, dict, "filters.session", "session filter")
            _keys(sess, {"start", "end", "tz"}, "filters.session")
            import re as _re
            for k in ("start", "end"):
                if not _re.match(r"^\d{2}:\d{2}$", str(sess.get(k, ""))):
                    _fail(f"filters.session.{k}",
                          "session times must be HH:MM")
        regime = filters.get("regime", {})
        if regime is not None:
            _check_type(regime, dict, "filters.regime", "regime filter")
            _keys(regime, {"allowed", "preferred", "forbidden"},
                  "filters.regime")
            for k in ("allowed", "preferred", "forbidden"):
                if not isinstance(regime.get(k, []), list):
                    _fail(f"filters.regime.{k}", f"{k} must be a list")

    params = spec.get("params", {})
    if params:
        _check_type(params, dict, "params", "params")
        if len(params) > 64:
            raise LimitExceeded("more than 64 params", path="params")
        for name, decl in params.items():
            if not re.match(INDICATOR_ID_RE, str(name)):
                _fail(f"params.{name}", "param name malformed")
            _check_type(decl, dict, f"params.{name}", "param declaration")
            _keys(decl, {"type", "default", "min", "max", "step",
                         "description"}, f"params.{name}")
            if decl.get("type") not in {"number", "integer"}:
                _fail(f"params.{name}.type", "param type must be "
                      "number|integer")
            dv = decl.get("default")
            if isinstance(dv, bool) or not isinstance(dv, (int, float)):
                _fail(f"params.{name}.default", "param default must be "
                      "a number")
            if decl.get("type") == "integer" \
                    and float(dv) != int(dv):
                _fail(f"params.{name}.default",
                      "integer param needs an integer default")
            if "min" in decl and "max" in decl and \
                    decl["min"] > decl["max"]:
                _fail(f"params.{name}", "param min > max")
