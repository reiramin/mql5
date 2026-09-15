"""mql5bot.ml_interfaces — ML interfaces ONLY (plan Phase E).

The owner brief is explicit: machine learning interfaces are defined,
implementations are NOT (no neural networks / LSTM / RL / transformers
anywhere, no ML training, no new strategies).  This module is the
contract those future implementations must satisfy, plus the
risk-invariant seam every ML output must cross.

Four interface stubs — :class:`TripleBarrierLabeler`,
:class:`MetaLabeler`, :class:`ProbabilityCalibrator`,
:class:`FeatureStore` — raise ``NotImplementedError`` on every method:
they document signatures and semantics, they never run.

Risk invariants (pinned by tests/test_ml_interfaces.py, true BY
CONSTRUCTION today because the canonical engine has no ML hooks):

1. ML can never REMOVE a stop loss — the advice schema carries no SL
   field and the seam never touches order stops;
2. ML can never OVERRIDE the risk engine — sizing/risk live in
   ``mql5bot.sizer`` / ``RunConfig``; advice only ever CAPS size;
3. ML can never CREATE uncontrolled trades — the seam can only drop or
   shrink the engine's desired orders, never add rows;
4. ML can never RAISE hard risk limits — ``RiskContext`` is frozen and
   ``apply_ml_advice`` refuses caps above the context's ``max_lots``.

Everything here is pure and engine-free so the invariants are testable
today without any ML dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# ---------------------------------------------------------------------------
# Interface stubs (no implementations anywhere by design)
# ---------------------------------------------------------------------------

_NOT_IMPLEMENTED = ("interface-only stub (plan Phase E): ML implementations "
                    "are explicitly out of scope — no training, no neural "
                    "networks, no inference hooks exist in this codebase")


class TripleBarrierLabeler:
    """Contract: label observations with the triple-barrier method.

    Semantics (future): given a price path and three barriers — a
    profit-taking level, a stop level and a vertical (time) barrier —
    label each observation with which barrier was hit first.  The
    canonical engine fills stops first when a bar touches both levels;
    any implementation must honour the same conservative ordering and
    must NOT alter order risk levels (invariant 1).
    """

    def label(self, df: pd.DataFrame, *,
              profit_atr: float, stop_atr: float,
              max_bars: int) -> pd.Series:
        raise NotImplementedError(_NOT_IMPLEMENTED)


class MetaLabeler:
    """Contract: secondary (meta) model over primary labels.

    Semantics (future): a primary signal proposes a trade; the meta
    model predicts the probability the proposed trade is a winner and
    the engine decides size from the RISK ENGINE alone.  A meta model
    can only ever VETO or shrink a proposed trade — never enlarge it,
    never alter its stop (invariants 1-4 apply to every output).
    """

    def fit(self, features: pd.DataFrame, labels: pd.Series) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        raise NotImplementedError(_NOT_IMPLEMENTED)


class ProbabilityCalibrator:
    """Contract: map raw scores to well-calibrated probabilities.

    Semantics (future): isotonic/Platt-style calibration of a meta
    model's scores on a strictly separated calibration slice.  The
    calibration slice is data; the one-look policy of the staged
    pipeline (docs/STAGED_PIPELINE.md) applies to it like any other
    optimisation surface.
    """

    def calibrate(self, scores: pd.Series, outcomes: pd.Series) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def predict_proba(self, scores: pd.Series) -> pd.Series:
        raise NotImplementedError(_NOT_IMPLEMENTED)


class FeatureStore:
    """Contract: immutable, versioned feature storage.

    Semantics (future): features are written once per (dataset version,
    feature version) and read back verbatim — a feature matrix must be
    reproducible from its content digest alone (same convention as the
    pipeline's run manifests).  No feature may ever encode post-entry
    information (lookahead is forbidden by the engine contract).
    """

    def put(self, dataset_version: str, feature_version: str,
            frame: pd.DataFrame) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get(self, dataset_version: str, feature_version: str) -> pd.DataFrame:
        raise NotImplementedError(_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Risk-invariant seam (the ONLY shape ML output may take)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskContext:
    """Frozen snapshot of the hard risk limits in force.

    Immutable by construction — no ML output can raise these numbers.
    """

    max_lots: float
    initial_capital: float = 10_000.0
    max_daily_loss_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sizing_mode: str = "risk_percent_equity"
    risk_value: float = 1.0

    def __post_init__(self):
        for name, value in (
            ("max_lots", self.max_lots),
            ("initial_capital", self.initial_capital),
            ("risk_value", self.risk_value),
        ):
            if not value > 0.0:
                raise ValueError(f"{name} must be > 0")


@dataclass(frozen=True)
class MLAdvice:
    """The ONLY shape an ML output may take at the engine seam.

    Schema-level invariants: there is no field for stops, no field for
    risk values, no field for position counts or limits — an advice can
    only express ``confidence`` (informational), a ``suggested_side``
    (veto/direction) and a ``max_lots_cap`` (shrink).  It can never
    remove an SL, override the risk engine, create trades or raise a
    hard limit.
    """

    confidence: float = 0.5
    suggested_side: int | None = None  # -1 short / 0 flat / +1 long / None
    max_lots_cap: float | None = None  # None = no cap (engine sizes)
    note: str = ""

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.suggested_side not in (-1, 0, 1, None):
            raise ValueError("suggested_side must be -1, 0, 1 or None")
        if self.max_lots_cap is not None and not self.max_lots_cap > 0.0:
            raise ValueError("max_lots_cap must be > 0 (or None)")


# invariant checkers ---------------------------------------------------------


def check_ml_invariants(orders_before: pd.DataFrame,
                        orders_after: pd.DataFrame,
                        advice: MLAdvice,
                        context: RiskContext,
                        *,
                        order_key=("entry_time", "side")) -> list[str]:
    """Return every invariant violation between engine orders and the
    seam output.  Empty list == the four invariants hold.

    * no uncontrolled trades: ``orders_after`` is a subset of
      ``orders_before`` on ``order_key``;
    * no enlarged trades: per order, lots never increase;
    * no SL removal / no risk override: the advice schema has no such
      fields (checked by construction) and the seam keeps all columns;
    * no raised hard limits: the frozen ``context`` is untouched and
      the advice cap never exceeds ``context.max_lots``.
    """
    violations: list[str] = []
    if orders_before.empty:
        if not orders_after.empty:
            violations.append("ML created trades out of nothing")
        return violations
    b = orders_before.set_index(list(order_key))
    a = orders_after.set_index(list(order_key))
    extra = a.index.difference(b.index)
    if len(extra):
        violations.append(f"ML created {len(extra)} uncontrolled trade(s): "
                          f"{sorted(map(str, extra))[:3]}...")
    for key in a.index.intersection(b.index):
        if float(a.loc[key, "lots"]) > float(b.loc[key, "lots"]) + 1e-12:
            violations.append(f"ML enlarged trade {key!r}: "
                              f"{float(b.loc[key, 'lots'])} -> "
                              f"{float(a.loc[key, 'lots'])} lots")
    for col in ("sl", "tp", "stop_loss"):
        if col in b.columns and col in a.columns \
                and b[col].isna().sum() == 0 and a[col].isna().sum() > 0:
            violations.append(
                f"ML output has rows without stops (column {col!r}) where "
                "the input had none missing")
    if advice.max_lots_cap is not None \
            and advice.max_lots_cap > context.max_lots + 1e-12:
        violations.append("ML cap exceeds the hard max_lots limit")
    return violations


def _side_value(side) -> int:
    """Normalise an order side (int or 'long'/'short') to -1/0/+1."""
    if isinstance(side, str):
        return 1 if side == "long" else -1
    return 1 if float(side) > 0 else (-1 if float(side) < 0 else 0)


def apply_ml_advice(orders: pd.DataFrame, advice: MLAdvice,
                    context: RiskContext) -> pd.DataFrame:
    """Merge one ML advice into the engine's desired orders.

    The seam: side vetoes (flat) and conflicting directions DROP orders,
    the lots cap SHRINKS them; nothing is ever added and stops are never
    touched.  A cap above ``context.max_lots`` is refused outright, and
    the result is re-checked against all four invariants before it is
    returned — the check runs on the OUTPUT, not the input.
    """
    if advice.max_lots_cap is not None \
            and advice.max_lots_cap > context.max_lots + 1e-12:
        raise ValueError("MLAdvice cap would raise the hard max_lots limit")
    out = orders.copy(deep=True)
    if out.empty:
        return out
    if advice.suggested_side == 0:
        out = out.iloc[0:0].copy()  # veto everything
    elif advice.suggested_side in (-1, 1):
        keep = out["side"].map(
            lambda s: _side_value(s) == advice.suggested_side)
        out = out[keep]
    if advice.max_lots_cap is not None and not out.empty:
        lots = pd.to_numeric(out["lots"], errors="coerce").clip(
            upper=advice.max_lots_cap)
        out = out.assign(lots=lots)
    violations = check_ml_invariants(orders, out, advice, context)
    if violations:
        raise ValueError(f"advice refused by the risk seam: {violations}")
    return out


# ---------------------------------------------------------------------------
# Invariant registry (importable list — the seam, documented)
# ---------------------------------------------------------------------------

ML_INVARIANTS = (
    ("ML can never remove a stop loss (advice has no SL field; seam never "
     "touches stops)"),
    ("ML can never override the risk engine (sizing stays in sizer/RunConfig; "
     "advice only caps)"),
    ("ML can never create uncontrolled trades (seam only drops/shrinks engine "
     "desired orders)"),
    ("ML can never raise hard risk limits (RiskContext frozen; caps bounded "
     "by context.max_lots)"),
)
