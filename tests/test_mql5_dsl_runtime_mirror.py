"""Behavioural mirror of the MQL5 generic runtime (final closure wave).

``mql5_dsl_runtime/`` cannot be compiled on Mac, so this test ports the
EXACT algorithms its source encodes — the canonical indicator functions
(DslIndicators.mqh, including the numpy-order pairwise seed sums), the
per-bar recursive evaluator (DslRuntime.mqh: generic CROSS operands,
rising/falling vs EACH previous value, state/instant modes), the filter
chain (trading_days → session → spread → atr-pct → regime, then the
original-vector cooldown) and the runner's series construction
(DslParityRunner.mq5) — and requires them to reproduce EVERY golden
fixture's expected trace EXACTLY (positions, events, exit geometry).

The OLD source could not have passed: it used MT5 built-ins with
different EMA seeds, stubbed DONCHIAN/HIGHEST/LOWEST, evaluated CROSS
with tie semantics that diverge from indicators.crossover, ran cooldown
over the partially-suppressed vector and had no session/trading-day
filters at all.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

GOLD = Path(__file__).resolve().parents[1] / "artifacts" / "dsl_parity"
MANIFEST = json.loads((GOLD / "manifest.json").read_text())
NAMES = sorted(MANIFEST["fixtures"])

NAN = float("nan")


def _isnan(v) -> bool:
    return math.isnan(v) if isinstance(v, float) else False


# ---------------------------------------------------------------------------
# DslIndicators.mqh — ported verbatim
# ---------------------------------------------------------------------------


def numpy_sum(a, offset, n):
    """DslNumpySum: numpy pairwise add.reduce (8 partials, block 128)."""
    if n < 8:
        res = 0.0
        for i in range(n):
            res += a[offset + i]
        return res
    if n <= 128:
        r = [a[offset + j] for j in range(8)]
        i = 8
        while i < n - (n % 8):
            for j in range(8):
                r[j] += a[offset + i + j]
            i += 8
        res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5])
                                                 + (r[6] + r[7]))
        while i < n:
            res += a[offset + i]
            i += 1
        return res
    n2 = n // 2
    n2 -= n2 % 8
    return numpy_sum(a, offset, n2) + numpy_sum(a, offset + n2, n - n2)


def dsl_ema(v, period):
    n = len(v)
    out = [NAN] * n
    p = max(period, 1)
    if n < p:
        return out
    alpha = 2.0 / (p + 1.0)
    out[p - 1] = numpy_sum(v, 0, p) / p
    for i in range(p, n):
        out[i] = out[i - 1] + alpha * (v[i] - out[i - 1])
    return out


def dsl_rsi(v, period):
    n = len(v)
    out = [NAN] * n
    p = max(period, 1)
    if n <= p:
        return out
    gain, loss = [], []
    for j in range(p):
        d = v[j + 1] - v[j]
        gain.append(max(0.0, d))
        loss.append(-d if d < 0.0 else 0.0)
    avg_g = numpy_sum(gain, 0, p) / p
    avg_l = numpy_sum(loss, 0, p) / p
    rs = avg_g / max(avg_l, 1e-12)
    out[p] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(p + 1, n):
        d = v[i] - v[i - 1]
        g = max(0.0, d)
        lo = -d if d < 0.0 else 0.0
        avg_g = (avg_g * (p - 1) + g) / p
        avg_l = (avg_l * (p - 1) + lo) / p
        rs = avg_g / max(avg_l, 1e-12)
        out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def dsl_atr(high, low, close, period):
    n = len(high)
    out = [NAN] * n
    p = max(period, 1)
    if n <= p:
        return out
    tr = []
    for i in range(1, p + 1):
        pc = close[i - 1]
        tr.append(max(high[i] - low[i],
                      abs(high[i] - pc), abs(low[i] - pc)))
    out[p] = numpy_sum(tr, 0, p) / p
    for i in range(p + 1, n):
        pc = close[i - 1]
        t = max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc))
        out[i] = (out[i - 1] * (p - 1) + t) / p
    return out


def dsl_donchian(high, low, period):
    n = len(high)
    upper, lower = [NAN] * n, [NAN] * n
    p = max(period, 1)
    if n <= p:
        return upper, lower
    for i in range(p, n):
        window_h = high[i - p:i]
        window_l = low[i - p:i]
        if any(_isnan(x) for x in window_h + window_l):
            continue
        upper[i] = max(window_h)
        lower[i] = min(window_l)
    return upper, lower


def dsl_highest(v, period):
    n = len(v)
    out = [NAN] * n
    p = max(period, 1)
    for i in range(p - 1, n):
        w = v[i - p + 1:i + 1]
        if not any(_isnan(x) for x in w):
            out[i] = max(w)
    return out


def dsl_lowest(v, period):
    n = len(v)
    out = [NAN] * n
    p = max(period, 1)
    for i in range(p - 1, n):
        w = v[i - p + 1:i + 1]
        if not any(_isnan(x) for x in w):
            out[i] = min(w)
    return out


# ---------------------------------------------------------------------------
# DslParityRunner.mq5 BuildSeries — ported verbatim
# ---------------------------------------------------------------------------


class Refused(Exception):
    pass


def build_series(spec, open_, high, low, close):
    """Mirror of DslSeries.mqh::DslBuildSeriesFromArrays — ONLY the six
    kinds the integrated runtime supports (EMA/RSI/ATR + channels).
    SMA/BBANDS/MACD and every other kind are refused, exactly as the
    loader refuses them."""
    series = {"open": open_, "high": high, "low": low, "close": close}
    cols = {"close": close, "open": open_, "high": high, "low": low,
            "": close}
    for ind in spec["indicators"]:
        kind = ind["kind"]
        iid = ind["id"]
        period = int(ind.get("period", 14))
        shift = int(ind.get("shift", 0))
        applied = ind.get("applied", "close")
        if applied not in cols and kind not in ("ATR", "DONCHIAN"):
            raise Refused(f"unsupported applied {applied!r}")
        vals = cols.get(applied, close)
        if kind == "EMA":
            buf = dsl_ema(vals, period)
        elif kind == "RSI":
            buf = dsl_rsi(vals, period)
        elif kind == "HIGHEST":
            buf = dsl_highest(vals, period)
        elif kind == "LOWEST":
            buf = dsl_lowest(vals, period)
        elif kind == "ATR":
            buf = dsl_atr(high, low, close, period)
        elif kind == "DONCHIAN":
            up, lo = dsl_donchian(high, low, period)
            series[f"{iid}__upper"] = up
            series[f"{iid}__lower"] = lo
            buf = up
        else:
            raise Refused(f"unsupported indicator kind {kind!r}")
        if shift > 0:
            shifted = [NAN] * len(buf)
            for i in range(shift, len(buf)):
                shifted[i] = buf[i - shift]
            buf = shifted
        series[iid] = buf
    return series


# ---------------------------------------------------------------------------
# DslRuntime.mqh — ported verbatim
# ---------------------------------------------------------------------------


class MirrorRuntime:
    def __init__(self, spec, series, times):
        self.spec = spec
        self.series = series
        self.times = times
        self.bars = len(times)

    def series_at(self, name, bar):
        if name not in self.series:
            raise Refused(f"series {name!r} not computed")
        if bar < 0 or bar >= self.bars:
            return NAN
        return self.series[name][bar]

    def operand(self, op, bar):
        if "ind" in op:
            return self.series_at(op["ind"], bar)
        if "price" in op:
            return self.series_at(op["price"], bar)
        if "const" in op:
            return float(op["const"])
        for key in ("add", "sub", "mul", "div"):
            if key in op:
                a, b = op[key]
                x, y = self.operand(a, bar), self.operand(b, bar)
                if key == "add":
                    return x + y
                if key == "sub":
                    return x - y
                if key == "mul":
                    return x * y
                return NAN if y == 0.0 else x / y
        raise Refused("unrecognized operand node")

    def cross_sign(self, a_op, b_op, bar):
        if bar < 1:
            return 0
        a0, a1 = self.operand(a_op, bar), self.operand(a_op, bar - 1)
        b0, b1 = self.operand(b_op, bar), self.operand(b_op, bar - 1)
        if any(_isnan(x) for x in (a0, a1, b0, b1)):
            return 0
        above, p_above = a0 > b0, a1 > b1
        if above and not p_above:
            return 1
        if not above and p_above:
            return -1
        return 0

    def cond(self, cond, bar):
        if "and" in cond:
            return all(self.cond(c, bar) for c in cond["and"])
        if "or" in cond:
            return any(self.cond(c, bar) for c in cond["or"])
        if "not" in cond:
            return not self.cond(cond["not"], bar)
        if "cmp" in cond:
            lft = self.operand(cond["left"], bar)
            r = self.operand(cond["right"], bar)
            if _isnan(lft) or _isnan(r):
                return False
            c = cond["cmp"]
            return {"GT": lft > r, "GE": lft >= r, "LT": lft < r,
                    "LE": lft <= r, "EQ": lft == r, "NE": lft != r}[c]
        if "cross" in cond:
            s = self.cross_sign(cond["a"], cond["b"], bar)
            return s > 0 if cond["cross"] == "ABOVE" else s < 0
        if "rising" in cond or "falling" in cond:
            key = "rising" if "rising" in cond else "falling"
            win = int(cond.get("n", 2))
            cur = self.operand(cond[key], bar)
            if _isnan(cur):
                return False
            for k in range(1, win):
                if bar - k < 0:
                    return False
                prev = self.operand(cond[key], bar - k)
                if _isnan(prev):
                    return False
                if key == "rising" and not cur > prev:
                    return False
                if key == "falling" and not cur < prev:
                    return False
            return True
        if "within" in cond:
            x = self.operand(cond["within"], bar)
            if _isnan(x):
                return False
            return float(cond["low"]) <= x <= float(cond["high"])
        raise Refused("unrecognized condition node")

    def desired_positions(self):
        entry = self.spec["entry"]
        mode = entry.get("mode", "")
        if mode not in ("state", "instant"):
            raise Refused("no executable entry mode")
        out = []
        if mode == "instant":
            for i in range(self.bars):
                d = 0
                if entry.get("long") is not None \
                        and self.cond(entry["long"], i):
                    d = 1
                elif entry.get("short") is not None \
                        and self.cond(entry["short"], i):
                    d = -1
                out.append(d)
        else:
            state = 0
            for i in range(self.bars):
                if entry.get("long") is not None \
                        and self.cond(entry["long"], i):
                    state = 1
                elif entry.get("short") is not None \
                        and self.cond(entry["short"], i):
                    state = -1
                else:
                    if state == 1 and entry.get("exit_long") is not None \
                            and self.cond(entry["exit_long"], i) or state == -1 \
                            and entry.get("exit_short") is not None \
                            and self.cond(entry["exit_short"], i):
                        state = 0
                out.append(state)
        self.apply_filters(out)
        self.cooldown(out)
        return out

    def apply_filters(self, out):
        market = self.spec.get("market", {})
        filters = self.spec.get("filters", {}) or {}
        td = market.get("trading_days")
        if isinstance(td, list):
            allowed = {int(d) for d in td}
            for i in range(self.bars):
                mql_dow = (self.times[i].weekday() + 1) % 7  # Sun=0
                py_dow = (mql_dow + 6) % 7                   # Mon=0
                if py_dow not in allowed:
                    out[i] = 0
        sess = market.get("session")
        if not isinstance(sess, dict):
            sess = filters.get("session")
        if isinstance(sess, dict):
            sh, sm = map(int, sess["start"].split(":"))
            eh, em = map(int, sess["end"].split(":"))
            start, end = sh * 60 + sm, eh * 60 + em
            for i in range(self.bars):
                minutes = self.times[i].hour * 60 + self.times[i].minute
                inside = (start <= minutes < end) if start <= end \
                    else (minutes >= start or minutes < end)
                if not inside:
                    out[i] = 0
        if filters.get("max_spread_points") is not None:
            raise Refused("max_spread_points needs a spread feed")
        if filters.get("max_atr_pct") is not None:
            a = dsl_atr(self.series["high"], self.series["low"],
                        self.series["close"], 14)
            mx = float(filters["max_atr_pct"])
            for i in range(self.bars):
                if _isnan(a[i]):
                    continue
                c = self.series["close"][i]
                over = (a[i] > 0.0) if c == 0.0 else (a[i] / c > mx)
                if over:
                    out[i] = 0
        forb = (filters.get("regime", {}) or {}).get("forbidden")
        if forb:
            raise Refused("regime.forbidden needs a regime feed")

    def cooldown(self, out):
        k = int(self.spec.get("filters", {}).get("cooldown_bars", 0))
        if k <= 0:
            return
        orig = list(out)
        hold_until = -1
        for i in range(self.bars):
            if orig[i] != 0 and i <= hold_until and i > 0 \
                    and orig[i - 1] == 0:
                out[i] = 0
            if orig[i] != 0 and (i == 0 or orig[i - 1] == 0):
                hold_until = i + k


# runner exit-geometry mirror (raw-token values parsed back for compare)
def mirror_exit_geometry(spec):
    ex = spec.get("exit", {}) or {}
    out = {"trail_atr": float(ex.get("trail_atr", 0.0)),
           "breakeven_atr": float(ex.get("breakeven_atr", 0.0))}
    for side, atr_key in (("sl", "sl_atr"), ("tp", "tp_atr")):
        stop = ex.get(side)
        if stop is None:
            continue
        model = stop.get("model", "atr")
        if model == "atr":
            out[atr_key] = float(stop.get("mult", 0.0))
        else:
            out[atr_key] = None
            value_key = "points" if model == "points" else "pct"
            out[f"{model}_{side}"] = float(stop.get(value_key, 0.0))
    return out


# ---------------------------------------------------------------------------
# the mirror must reproduce EVERY golden expected trace EXACTLY
# ---------------------------------------------------------------------------


def _load_fixture(name):
    bundle = json.loads((GOLD / name / "bundle.json").read_text())
    expected = json.loads((GOLD / name / "expected_trace.json").read_text())
    df = pd.read_csv(GOLD / name / "ohlc.csv", index_col=0,
                     parse_dates=True)
    return bundle, expected, df


@pytest.mark.parametrize("name", NAMES)
def test_mql5_runtime_mirror_reproduces_golden_trace(name):
    bundle, expected, df = _load_fixture(name)
    spec = bundle["spec"]
    series = build_series(spec,
                          [float(x) for x in df["open"]],
                          [float(x) for x in df["high"]],
                          [float(x) for x in df["low"]],
                          [float(x) for x in df["close"]])
    rt = MirrorRuntime(spec, series, list(df.index))
    pos = rt.desired_positions()
    assert pos == expected["positions"], name
    events = []
    prev = 0
    for i, p in enumerate(pos):
        if p != prev:
            events.append({"bar": i, "from": prev, "to": p})
            prev = p
    assert events == expected["events"], name
    assert mirror_exit_geometry(spec) == expected["exit_geometry"], name


def test_old_cross_tie_semantics_would_fail():
    """The OLD MQL5 CrossSign fired -1 on EQUAL->BELOW and stayed
    silent on ABOVE->EQUAL; the canonical contract is the opposite.
    Pin one concrete divergence so a regression cannot hide."""
    series = {"a": [1.0, 2.0, 2.0], "b": [2.0, 2.0, 3.0]}
    rt = MirrorRuntime({}, series, [0, 1, 2])
    # bar1: prev a<b, now a==b (EQUAL): no strict-above entry -> 0
    assert rt.cross_sign({"ind": "a"}, {"ind": "b"}, 1) == 0
    # canonical: ABOVE->EQUAL fires -1
    series2 = {"a": [3.0, 2.0], "b": [2.0, 2.0]}
    rt2 = MirrorRuntime({}, series2, [0, 1])
    assert rt2.cross_sign({"ind": "a"}, {"ind": "b"}, 1) == -1


def test_old_inplace_cooldown_would_fail():
    """Cooldown must read the ORIGINAL vector: [1,0,1,1] with a long
    cooldown suppresses bar 2 but MUST keep bar 3 (its predecessor was
    nonzero in the original).  The old in-place scan zeroed bar 3."""
    spec = {"filters": {"cooldown_bars": 5}, "market": {}}
    rt = MirrorRuntime(spec, {}, [0, 1, 2, 3])
    out = [1, 0, 1, 1]
    rt.cooldown(out)
    assert out == [1, 0, 0, 1]


def test_missing_feeds_are_refused_not_guessed():
    spec = {"entry": {"mode": "instant"}, "market": {},
            "filters": {"max_spread_points": 3.0}}
    rt = MirrorRuntime(spec, {}, [])
    with pytest.raises(Refused):
        rt.apply_filters([])
    spec2 = {"market": {},
             "filters": {"regime": {"forbidden": ["CRISIS"]}}}
    rt2 = MirrorRuntime(spec2, {}, [])
    with pytest.raises(Refused):
        rt2.apply_filters([])
