"""mql5bot.dsl.runtime — deterministic spec → signal evaluation.

The canonical execution model for DSL strategies (mission §15's
preferred ``DSL → runtime interpreter``; no code generation, no eval,
no dynamic imports — the spec is DATA interpreted structurally).

Semantics (mirror ``mql5bot.strategies`` exactly — the parity target):

- Everything is computed from CLOSED bars of the OHLC frame; the
  backtest engine acts one bar later at the next open, so lookahead is
  impossible by construction (same contract as compiled strategies).
- ``mode: "instant"``: desired = +1 where long fires, −1 where short
  fires, else 0 (bollinger_reversal semantics).
- ``mode: "state"``: entries flip the state; it persists until the
  opposite entry, an explicit exit condition, or a NaN bar re-arms it
  (ema_crossover / macd_momentum / donchian_breakout / rsi_reversal
  semantics).
- NaN comparisons are False; a NaN bar EMITS 0 while carrying state
  (donchian warmup behavior); before the first valid bar state is 0.
- Filters (session / volatility / spread / cooldown / regime-forbidden
  / trading days) only ever FLATTEN bars — they can never create a
  position.
- Exit geometry (SL/TP models, trailing, breakeven) is RETURNED as
  parameters for the sizing/execution layers; the strategy never
  authorizes a risk amount (Risk Engine remains the veto).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .errors import AmbiguousParameter, NotExecutable, UnknownReference
from .model import IndicatorDef, StrategySpec

_TRADING_HOURS = None  # session filtering uses the frame index directly


# ------------------------------------------------------------- indicators


def _applied(df: pd.DataFrame, ind: IndicatorDef) -> np.ndarray:
    if ind.kind in {"ATR", "DONCHIAN", "MACD"}:
        return df["close"].to_numpy(dtype=float)
    return df[ind.applied].to_numpy(dtype=float)


def compute_indicators(df: pd.DataFrame,
                       indicators: tuple) -> dict[str, np.ndarray]:
    """Indicator matrix for the spec's declared indicators.  `shift`
    delays by whole CLOSED bars (a positive shift only looks BACK —
    shift > 0 is causal; the schema forbids negative shifts)."""
    from ..indicators import (
        atr,
        bollinger,
        donchian,
        ema,
        highest,
        lowest,
        macd,
        rsi,
        sma,
    )
    out: dict[str, np.ndarray] = {}
    from ..indicator_universe import EXTENDED_KINDS
    from ..indicator_universe import compute as _uc
    pre_shift: dict[str, np.ndarray] = {}
    for ind in indicators:
        if ind.kind in EXTENDED_KINDS:
            from ..indicator_universe import contract as _ucontract
            # canonical doc stores integral floats (§29.1); resolve()
            # re-coerces to the contract's declared types
            ct_vals = _uc(ind.kind, df,
                          _ucontract(ind.kind).resolve(dict(ind.params)))
            outs = _ucontract(ind.kind).outputs
            for name, arrv in ct_vals.items():
                out[f"{ind.id}__{name}"] = arrv
                pre_shift[f"{ind.id}__{name}"] = arrv
            arr = ct_vals[outs[0]]          # bare id → primary output
            pre_shift[ind.id] = arr
            out[ind.id] = arr
            if ind.shift:
                base = arr
                sh = np.full(len(base), np.nan)
                if ind.shift < len(base):
                    sh[ind.shift:] = base[:len(base) - ind.shift]
                out[ind.id] = sh
                for name in outs:
                    bv = ct_vals[name]
                    shn = np.full(len(bv), np.nan)
                    if ind.shift < len(bv):
                        shn[ind.shift:] = bv[:len(bv) - ind.shift]
                    out[f"{ind.id}__{name}"] = shn
            continue
        vals = _applied(df, ind)
        if ind.kind == "EMA":
            arr = ema(vals, ind.period)
        elif ind.kind == "SMA":
            arr = sma(vals, ind.period)
        elif ind.kind == "RSI":
            arr = rsi(vals, ind.period)
        elif ind.kind == "ATR":
            arr = atr(df["high"].to_numpy(dtype=float),
                      df["low"].to_numpy(dtype=float),
                      df["close"].to_numpy(dtype=float), ind.period)
        elif ind.kind == "BBANDS":
            mid, upper, lower = bollinger(vals, ind.period, ind.dev)
            out[f"{ind.id}__mid"] = mid
            out[f"{ind.id}__upper"] = upper
            out[f"{ind.id}__lower"] = lower
            arr = mid                      # bare id → middle band
        elif ind.kind == "MACD":
            line, sig, _hist = macd(vals, ind.fast, ind.slow,
                                    ind.signal)
            out[f"{ind.id}__line"] = line
            out[f"{ind.id}__signal"] = sig
            arr = line
        elif ind.kind == "DONCHIAN":
            upper, lower = donchian(
                df["high"].to_numpy(dtype=float),
                df["low"].to_numpy(dtype=float), ind.period)
            out[f"{ind.id}__upper"] = upper
            out[f"{ind.id}__lower"] = lower
            arr = upper                    # bare id → upper channel
        elif ind.kind == "HIGHEST":
            arr = highest(vals, ind.period)
        elif ind.kind == "LOWEST":
            arr = lowest(vals, ind.period)
        else:  # schema validates kinds; this is defense in depth
            raise NotExecutable(f"indicator kind {ind.kind!r} has no "
                                "runtime implementation")
        if ind.shift:
            base = _base_array(out, ind, df)
            arr = np.full_like(base, np.nan)
            if ind.shift < len(arr):
                # positive shift delays by whole CLOSED bars (causal:
                # the value known `shift` bars ago)
                arr[ind.shift:] = base[:len(base) - ind.shift]
        out[ind.id] = arr
    return out


def _base_array(out: dict, ind: IndicatorDef, df: pd.DataFrame
                ) -> np.ndarray:
    # recompute the unshifted array for the shift slice
    from ..indicators import (
        atr,
        bollinger,
        donchian,
        ema,
        highest,
        lowest,
        macd,
        rsi,
        sma,
    )
    vals = _applied(df, ind)
    if ind.kind == "EMA":
        return ema(vals, ind.period)
    if ind.kind == "SMA":
        return sma(vals, ind.period)
    if ind.kind == "RSI":
        return rsi(vals, ind.period)
    if ind.kind == "ATR":
        return atr(df["high"].to_numpy(dtype=float),
                   df["low"].to_numpy(dtype=float),
                   df["close"].to_numpy(dtype=float), ind.period)
    if ind.kind == "BBANDS":
        return bollinger(vals, ind.period, ind.dev)[0]
    if ind.kind == "MACD":
        return macd(vals, ind.fast, ind.slow, ind.signal)[0]
    if ind.kind == "DONCHIAN":
        return donchian(df["high"].to_numpy(dtype=float),
                        df["low"].to_numpy(dtype=float),
                        ind.period)[0]
    if ind.kind == "HIGHEST":
        return highest(vals, ind.period)
    return lowest(vals, ind.period)


# ------------------------------------------------------------- evaluation


def eval_operand(op: dict, series: dict[str, np.ndarray],
                 df: pd.DataFrame) -> np.ndarray:
    (key,) = tuple(op)
    n = len(df)
    if key == "ind":
        name = op[key]
        if name not in series:
            raise UnknownReference(f"indicator {name!r} not computed")
        return series[name]
    if key == "price":
        return df[op[key]].to_numpy(dtype=float)
    if key == "const":
        return np.full(n, float(op[key]))
    if key == "ambiguous":
        raise AmbiguousParameter(f"unresolved ambiguous value "
                                 f"{op[key]!r}")
    if key == "param":
        raise UnknownReference(f"param {op[key]!r} unresolved at parse")
    a = eval_operand(op[key][0], series, df)
    b = eval_operand(op[key][1], series, df)
    if key == "add":
        return a + b
    if key == "sub":
        return a - b
    if key == "mul":
        return a * b
    # div: divide-by-zero yields NaN (comparison False), not an exception
    with np.errstate(divide="ignore", invalid="ignore"):
        return a / b


def eval_condition(cond: dict, series: dict[str, np.ndarray],
                   df: pd.DataFrame) -> np.ndarray:
    """Boolean array; NaN-safe (NaN comparisons are False)."""
    n = len(df)
    if "and" in cond:
        out = np.ones(n, dtype=bool)
        for c in cond["and"]:
            out &= eval_condition(c, series, df)
        return out
    if "or" in cond:
        out = np.zeros(n, dtype=bool)
        for c in cond["or"]:
            out |= eval_condition(c, series, df)
        return out
    if "not" in cond:
        return ~eval_condition(cond["not"], series, df)
    if "cmp" in cond:
        left = eval_operand(cond["left"], series, df)
        right = eval_operand(cond["right"], series, df)
        cmp = cond["cmp"]
        if cmp == "GT":
            return left > right
        if cmp == "GE":
            return left >= right
        if cmp == "LT":
            return left < right
        if cmp == "LE":
            return left <= right
        if cmp == "EQ":
            return left == right
        return left != right
    if "cross" in cond:
        # crossover() is the single source of truth: +1 above-cross,
        # -1 below-cross (crossunder()'s sign is not used here)
        from ..indicators import crossover
        a = eval_operand(cond["a"], series, df)
        b = eval_operand(cond["b"], series, df)
        co = crossover(a, b)
        return co > 0 if cond["cross"] == "ABOVE" else co < 0
    if "rising" in cond or "falling" in cond:
        key = "rising" if "rising" in cond else "falling"
        arr = eval_operand(cond[key], series, df)
        win = int(cond.get("n", 2))
        ok = ~np.isnan(arr)
        out = ok.copy()
        for k in range(1, win):
            prev = np.roll(arr, k)
            prev[:k] = np.nan
            with np.errstate(invalid="ignore"):
                if key == "rising":
                    out &= ok & ~np.isnan(prev) & (arr > prev)
                else:
                    out &= ok & ~np.isnan(prev) & (arr < prev)
        return out
    if "within" in cond:
        arr = eval_operand(cond["within"], series, df)
        with np.errstate(invalid="ignore"):
            return (arr >= float(cond["low"])) & \
                (arr <= float(cond["high"]))
    raise NotExecutable(f"unrecognized condition node {sorted(cond)}")


# ------------------------------------------------------------- positions


def _apply_filters(desired: np.ndarray, spec: StrategySpec,
                   df: pd.DataFrame, *, spread_points=None,
                   atr_series=None, regime_series=None) -> np.ndarray:
    """Filters only ever FLATTEN bars (mission §70: strategies propose)."""
    f = spec.filters
    mask = np.ones(len(df), dtype=bool)

    if spec.market is not None and spec.market.trading_days:
        days = df.index.dayofweek.to_numpy()
        mask &= np.isin(days, list(spec.market.trading_days))

    for sess in (spec.market.session, f.session):
        if sess:
            minutes = df.index.hour.to_numpy() * 60 \
                + df.index.minute.to_numpy()
            sh, sm = map(int, sess[0].split(":"))
            eh, em = map(int, sess[1].split(":"))
            start, end = sh * 60 + sm, eh * 60 + em
            if start <= end:
                mask &= (minutes >= start) & (minutes < end)
            else:  # overnight session
                mask &= (minutes >= start) | (minutes < end)
            break  # market-level and filter-level sessions agree; one applies

    if f.max_spread_points is not None:
        if spread_points is None:
            raise NotExecutable(
                "filters.max_spread_points set but no spread series "
                "supplied — refusing to guess (never a silent pass)")
        mask &= np.asarray(spread_points, dtype=float) \
            <= float(f.max_spread_points)

    if f.max_atr_pct is not None:
        if atr_series is None:
            atr_series = _default_atr(df)
        close = df["close"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            pct = atr_series / close
        mask &= ~(pct > float(f.max_atr_pct))

    if f.regime_forbidden:
        if regime_series is None:
            raise NotExecutable(
                "regime.forbidden set but no regime series supplied — "
                "refusing to guess (causal regime feed is an input)")
        labels = np.asarray(regime_series)
        mask &= ~np.isin(labels, list(f.regime_forbidden))

    desired = desired.copy()
    desired[~mask] = 0
    return desired


def _default_atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    from ..indicators import atr
    return atr(df["high"].to_numpy(dtype=float),
               df["low"].to_numpy(dtype=float),
               df["close"].to_numpy(dtype=float), period)


def _cooldown(desired: np.ndarray, cooldown_bars: int) -> np.ndarray:
    """After an entry, suppress NEW entries for k bars (state carried)."""
    if cooldown_bars <= 0:
        return desired
    out = desired.copy()
    hold_until = -1
    for i in range(len(desired)):
        if desired[i] != 0 and i <= hold_until and i > 0 \
                and desired[i - 1] == 0:
            out[i] = 0
        if desired[i] != 0 and (i == 0 or desired[i - 1] == 0):
            hold_until = i + cooldown_bars
    return out


def desired_positions(spec: StrategySpec, df: pd.DataFrame, *,
                      spread_points=None, regime_series=None,
                      apply_filters: bool = True) -> pd.Series:
    """Evaluate the spec over an OHLC frame → desired-position series
    in {−1, 0, +1} (the SAME contract as mql5bot.strategies)."""
    if spec.ambiguities:
        raise AmbiguousParameter(
            "spec has unresolved ambiguities: "
            f"{[a['name'] for a in spec.ambiguities]} — resolve them "
            "before execution (drafts never run)")
    if spec.entry is None or spec.entry.mode not in {"state", "instant"}:
        raise NotExecutable("spec has no executable entry mode")

    series = compute_indicators(df, spec.indicators)
    entry = spec.entry
    n = len(df)

    long_fire = eval_condition(entry.long, series, df) \
        if entry.long is not None else np.zeros(n, dtype=bool)
    short_fire = eval_condition(entry.short, series, df) \
        if entry.short is not None else np.zeros(n, dtype=bool)
    exit_long = eval_condition(entry.exit_long, series, df) \
        if entry.exit_long is not None else None
    exit_short = eval_condition(entry.exit_short, series, df) \
        if entry.exit_short is not None else None

    desired = np.zeros(n, dtype=int)
    if entry.mode == "instant":
        desired[long_fire] = 1
        desired[short_fire] = -1
    else:
        state = 0
        for i in range(n):
            if long_fire[i]:
                state = 1
            elif short_fire[i]:
                state = -1
            else:
                if state == 1 and exit_long is not None \
                        and exit_long[i] or state == -1 and exit_short is not None \
                        and exit_short[i]:
                    state = 0
            desired[i] = state

    if apply_filters:
        atr_series = None
        if spec.filters.max_atr_pct is not None:
            atr_series = _default_atr(df)
        desired = _apply_filters(desired, spec, df,
                                 spread_points=spread_points,
                                 atr_series=atr_series,
                                 regime_series=regime_series)
        desired = _cooldown(desired, spec.filters.cooldown_bars)

    return pd.Series(desired, index=df.index,
                     name=f"dsl:{spec.strategy_id}")


def exit_params(spec: StrategySpec) -> dict:
    """Exit geometry for the sizing/execution layers.  The engine's
    canonical ATR seam accepts atr models directly; points/percent
    models are reported honestly and REJECTED by the engine bridge
    (never silently converted)."""
    out: dict = {"trail_atr": spec.exit.trail_atr if spec.exit else 0.0,
                 "breakeven_atr":
                     spec.exit.breakeven_atr if spec.exit else 0.0}
    for key, stop in (("sl_atr", spec.exit.sl if spec.exit else None),
                      ("tp_atr", spec.exit.tp if spec.exit else None)):
        if stop is None:
            continue
        if stop.model == "atr":
            out[key] = stop.value
        else:
            out[key] = None      # honest: not an ATR model
            out[f"{stop.model}_sl" if key == "sl_atr" else
                f"{stop.model}_tp"] = stop.value
    return out
