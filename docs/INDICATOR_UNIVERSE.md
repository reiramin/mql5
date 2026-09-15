# Indicator Universe (mission §8–§10/§62/§77)

**Status: IMPLEMENTED.**

## Scope

71 declared kinds = 9 baseline kinds (EMA, SMA, RSI, ATR, MACD, BBANDS, STOCH, ADX-parity, CCI — parity-pinned, compute stays in `indicators.py`) + 62 extended kinds with pure causal computes in `mql5bot/indicator_universe/`. The registry is extensible: adding a kind = one contract + one compute function + one registry entry; NO DSL or runtime rewrite (schema/normalize/parse/runtime read the contract).

## Contracts (§9)

Every kind declares (`contracts.py:IndicatorContract`): `name`, `version=1`, `category`, typed params (`IndicatorParam`: name/int|float/minimum/maximum/default/required), named `outputs` (primary FIRST — the bare `id` reference maps to `outputs[0]`), `warmup(params)`, `price_source`, `determinism=True`, closed-bar `causality` note, and an HONEST `mql5_status` (`native` / `manual` / `manual-with-notes`) + `notes`. Multi-output is first-class: `SUPERTREND→(supertrend,direction)`, `ADX→(adx,plus_di,minus_di)`, `KELTNER→(upper,mid,lower)`, etc.; DSL references use `id__output`.

## Categories

Trend/momentum (27): WMA VWMA HMA DEMA TEMA KAMA ZLEMA ALMA TRIX T3 ICHIMOKU SUPERTREND PSAR AROON ADX VORTEX STOCH STOCHRSI CCI ROC MOM WILLR CMO TSI ULTOSC AO · volatility/volume (16): NATR KELTNER HISTVOL VOL_PERCENTILE OBV MFI CMF VWAP_SESSION VOL_OSC ADL CHAIKIN · structure (5): RANGE SWING_HIGH SWING_LOW FLOOR_PIVOTS BREAKOUT_DIST · candle (5): DOJI INSIDE_BAR ENGULFING PIN_BAR GAP · statistical (11): ROLLING_STD RETURNS LOG_RETURNS CHANNEL_SLOPE ROLLING_MEDIAN ROLLING_QUANTILE ZSCORE ROLLING_SKEW ROLLING_KURT AUTOCORR BETA · MTF (4): MTF_EMA MTF_SMA MTF_RSI MTF_ATR.

## Platform differences + parity (§10)

Canonical semantics are documented per contract in `notes` (e.g. Wilder smoothing for RSI/ATR/ADX, ALMA offset 0.85/σ 6, KAMA SC 2/3–2/31, Keltner EMA+ATR canonical). T3 = Tillson six-EMA cascade with volume factor; ICHIMOKU components are unshifted (displacements are plotting conventions); BETA is rolling OLS beta vs a required bar-aligned `benchmark_close` column (contract `requires_columns`). `mql5_status` marks where MQL5's built-in differs (Wilder `iRSI`/`iATR` match; several TA-Lib-style composites do not). Parity claims for baseline kinds are covered by the existing parity suite (179-trade fixture); extended kinds claim NO MT5 parity until the owner compiles the generated MQL5 and the fixtures run (§75/§76 — no MT5 claims without evidence).

## Closed-bar causality (§77)

- `SWING_HIGH/LOW`: `level` appears at CONFIRMATION (i+right); `pivot_time < confirmation_time` — property-tested with timestamps (`age == right`, first finite ≥ right).
- `MTF_*`: the k-th HTF value appears only after the HTF bar CLOSES, at base index (k+1)·m−1, carried forward; trailing incomplete HTF bars are dropped.
- `FLOOR_PIVOTS`: previous window's levels from the next bar; `BREAKOUT_DIST` uses shift(1) previous-window extremes.
- Registry-wide property test: mutating future rows never changes past values (rtol/atol 1e-12).

## Budgets (§62)

MAX_INDICATORS 32, MAX_DEPTH 32, 512 nodes, 256KB doc — the 33rd indicator raises `LimitExceeded` (pinned by test); limits are never silently raised for tests.
