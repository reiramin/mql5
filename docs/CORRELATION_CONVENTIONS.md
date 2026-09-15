# Correlation conventions (Phase 12)

How the Meta layer measures and uses correlation in the multi-asset
engine. These conventions are normative; `tests/test_doc_consistency.py`
pins the numbers against the code.

## Inputs

- **Bar frequency**: the engine consumes one shared `DatetimeIndex`
  frame per symbol (canonical research frequency: H1). Returns for the
  correlation matrix are per-book equity `pct_change` over bars
  **strictly before** the decision time `t` (as-of bounded).
- **Alignment**: every context must carry the SAME index
  (`MetaPortfolioEngine.__init__` refuses misaligned frames — one
  shared clock is a construction precondition, not a runtime repair).
- **Missing data**: a missing bar is a missing row of the shared frame;
  NaN OHLC never enters the engine (context `data_error` gate refuses
  the book — see the failure matrix F1). Missing *returns* (e.g. a
  book that has not traded) appear as a **zero-variance series**, not
  as zeros padded into other books.
- **Stale series**: there is no staleness imputation. A book whose
  equity has not moved contributes zero variance ⇒ its correlations
  are NaN ⇒ its correlation status is MISSING. We never fill a stale
  series with the last known correlation.

## Computation

- **Minimum observations**: `CORR_MIN_OBS = 30` overlapping return
  observations per pair (`meta_layer.CORR_MIN_OBS`); below that the
  pair's status is MISSING.
- **NaN policy**: NaN correlations are information ("not measurable"),
  never zero. Zero-fills are forbidden without a documented rationale;
  there is none on the canonical path.
- **Zero-return handling**: zero-variance series ⇒ NaN correlation ⇒
  MISSING. A series that is legitimately zero (flat equity) carries no
  co-movement information by definition.

## Coverage

The matrix is book × book where a book is `(strategy_id, symbol)`:
same-strategy cross-asset (boll on EURUSD vs boll on XAUUSD),
cross-strategy same-asset (boll vs ema on EURUSD) and cross-strategy
cross-asset cells all exist mechanically. Books never traded are
MISSING rows/columns.

## Penalty properties (contract invariants)

The weight penalty applied from this matrix is:

1. **Simultaneous** — computed once per decision from the same
   snapshot as every other input.
2. **Deterministic** — same snapshot ⇒ same matrix ⇒ same weights.
3. **Permutation-invariant** — book order does not change the matrix
   (pinned in the metamorphic suite via engine normalization).
4. **Historical** — only realized pre-`t` returns; no forward data.
5. **As-of bounded** — window ends strictly before `t`.
