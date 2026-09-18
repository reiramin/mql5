"""mql5bot.meta_layer — deterministic, explainable, risk-constrained
strategy allocation (Meta Layer, contract v1.1.1).

The Meta Layer is NOT a strategy, NOT a predictor, NOT a risk
authority.  It evaluates strategy eligibility, computes allocation
weights as the product of five factors, combines already-generated
strategy signals, and journals every decision deterministically.  The
Risk Engine remains the final authority for every trade; this module
has NO order API and can only REDUCE exposure.

Normative sources: docs/META_LAYER_CONTRACT.md (v1.1.1),
docs/META_LAYER_IMPLEMENTATION_SPEC.md, docs/DECISIONS.md ML-1..ML-7.

Guarantees pinned by tests (tests/test_meta_*.py):

* permutation invariance (strategy order can never change weights);
* hard zeros never resurrected (mask BEFORE normalize; no epsilon);
* simultaneous correlation snapshot (previous persisted weights only);
* byte-identical journals for identical inputs (canonical JSON);
* deterministic tie-breaks (strategy_id ascending);
* classified missing-data policy (never a neutral free pass);
* SAFE HOLD on any internal failure — never last-known-good weights.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import numpy as np
import pandas as pd

from .versions import COST_MODEL_VERSION, ENGINE_VERSION

__all__ = [
    "ALLOCATION_SCHEMA_VERSION",
    "DECISION_VERSION",
    "META_LAYER_VERSION",
    "Activation",
    "Eligibility",
    "EligibilityReason",
    "FactorStatus",
    "MetaConfig",
    "MetaConfigError",
    "MetaDecision",
    "MetaDecisionJournal",
    "MetaError",
    "MetaFactor",
    "MetaFileError",
    "MetaLayer",
    "MetaMode",
    "MetaPolicy",
    "MetaState",
    "MetaWeight",
    "NettedLeg",
    "RawMetaScore",
    "StrategyMetaInput",
    "canonical_json",
    "read_allocation_file",
    "safe_decision",
    "write_allocation_file",
]

CONTRACT_VERSION = "1.1.1"  # docs/META_LAYER_CONTRACT.md (authoritative)
META_LAYER_VERSION = "1.0.0"
DECISION_VERSION = "1.0.0"
ALLOCATION_SCHEMA_VERSION = "1"

# ---- fixed constants (NOT tunable; see spec §Factors/§A) --------------
PEN_FLOOR = 0.1            # correlation penalty lower bound
PERF_PRIOR_N = 20          # shrinkage prior in "trades"
PERF_CLIP = 0.02           # winsorize per-trade expectancy before shrink
PERF_MISSING = 0.5         # zero-observation / missing-source value
PERF_FLOOR, PERF_CAP = 0.1, 1.0
PERF_SCALE = 5.0           # expectancy (per-trade fraction) -> factor map
DRIFT_MILD = 0.10          # below: NO_DRIFT (factor 1.0)
DRIFT_BLOCK = 0.50         # at/above: DRIFT_BLOCK (hard zero)
DRIFT_MISSING = 0.5        # missing drift source value (never 1.0)
CORR_MIN_OBS = 30          # minimum overlapping observations per pair
GATE_WEIGHTS = {
    "VERIFIED": 1.0,
    "EMPIRICAL_VALIDATION_PENDING": 0.5,
    "SOFTWARE_PASS": 0.5,
}
STALE_AFTER_DAYS = 7       # SPEC line 107: allocation older than 7 days decays

_LOG = logging.getLogger(__name__)


class MetaError(Exception):
    """Base class for Meta Layer errors (never swallowed silently)."""


class MetaConfigError(MetaError):
    """Invalid configuration or input identity (duplicate ids, bad mode)."""


class MetaFileError(MetaError):
    """Malformed/invalid allocation or state file — MUST NOT be applied."""


class MetaMode(str, Enum):
    INDEPENDENT = "independent"
    WEIGHTED_NETTING = "weighted_netting"   # DEFAULT
    VOTE = "vote"
    BEST_OF_REGIME = "best_of_regime"


class MetaPolicy(str, Enum):
    META = "meta"
    EQUAL_WEIGHT = "equal_weight"           # first-class baseline


class Activation(str, Enum):
    DISABLED = "DISABLED"    # default
    SHADOW = "SHADOW"
    DEMO = "DEMO"
    LIVE_SMALL = "LIVE_SMALL"
    ACTIVE = "ACTIVE"

    @classmethod
    def ladder(cls) -> tuple[Activation, ...]:
        return (cls.DISABLED, cls.SHADOW, cls.DEMO, cls.LIVE_SMALL,
                cls.ACTIVE)

    def can_transition_to(self, target: Activation) -> bool:
        """Only explicit adjacent-or-backward transitions; never automatic."""
        lo, hi = self.ladder().index(self), self.ladder().index(target)
        return target != self and lo - 1 <= hi <= lo + 1

    @property
    def may_influence_sizing(self) -> bool:
        return self in (Activation.DEMO, Activation.LIVE_SMALL,
                        Activation.ACTIVE)


class EligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    KILL_SWITCH = "KILL_SWITCH"
    DISABLED = "DISABLED"
    CONFIG_INVALID = "CONFIG_INVALID"
    UNCERTIFIED = "UNCERTIFIED"
    CERT_FAILED = "CERT_FAILED"
    REGIME_FORBIDDEN = "REGIME_FORBIDDEN"
    REGIME_UNKNOWN = "REGIME_UNKNOWN"
    COOLDOWN = "COOLDOWN"
    STALE_DATA = "STALE_DATA"
    DRIFT_BLOCK = "DRIFT_BLOCK"
    MAX_POSITIONS = "MAX_POSITIONS"          # decision-level constraint
    BEST_OF_REGIME_LOSER = "BEST_OF_REGIME_LOSER"


class FactorStatus(str, Enum):
    OK = "OK"
    MISSING_FALLBACK = "MISSING_FALLBACK"    # single-strategy missing
    GLOBAL_FAILURE = "GLOBAL_FAILURE"        # source down for everyone


# ---- typed domain model (Phase 2) --------------------------------------


@dataclass(frozen=True)
class MetaFactor:
    """One factor value with its source, version and missing status."""

    name: str
    value: float
    source: str
    version: str
    status: FactorStatus = FactorStatus.OK

    def to_dict(self) -> dict:
        return {"name": self.name, "value": _r10(self.value),
                "source": self.source, "version": self.version,
                "status": self.status.value}


@dataclass(frozen=True)
class StrategyMetaInput:
    """Everything the layer may know about one strategy at decision
    time.  Factor INPUTS are raw observations; the layer computes the
    factors.  OOS-derived statistics only — in-sample/training
    performance is structurally unrepresentable here."""

    strategy_id: str
    symbol: str
    signal: int                       # -1 / 0 / +1 (0 = abstain)
    regime: str
    regimes_allowed: frozenset[str] = frozenset()
    regimes_preferred: frozenset[str] = frozenset()
    regimes_forbidden: frozenset[str] = frozenset()
    certification_state: str | None = None   # REQUIRED source
    enabled: bool = True
    cooldown_until: datetime | None = None
    stale: bool = False                      # source data stale flag
    kill_switch: bool = False                # account-level latch
    drift_score: float | None = None         # [0,1] divergence
    drift_available: bool = False
    currency: str = ""                       # for currency exposure
    strategy_version: str = ""               # Phase 21: version binding


@dataclass(frozen=True)
class Eligibility:
    strategy_id: str
    eligible: bool
    reason: EligibilityReason

    def to_dict(self) -> dict:
        return {"strategy_id": self.strategy_id, "eligible": self.eligible,
                "reason": self.reason.value}


@dataclass(frozen=True)
class RawMetaScore:
    strategy_id: str
    factors: tuple[MetaFactor, ...]
    raw_score: float

    def to_dict(self) -> dict:
        return {"strategy_id": self.strategy_id,
                "factors": [f.to_dict() for f in self.factors],
                "raw_score": _r10(self.raw_score)}


@dataclass(frozen=True)
class MetaWeight:
    strategy_id: str
    pre_cap_share: float
    final_weight: float
    clamp_reasons: tuple[str, ...] = ()
    zero_reason: EligibilityReason | None = None

    def to_dict(self) -> dict:
        return {"strategy_id": self.strategy_id,
                "pre_cap_share": _r10(self.pre_cap_share),
                "final_weight": _r10(self.final_weight),
                "clamp_reasons": list(self.clamp_reasons),
                "zero_reason": (self.zero_reason.value
                                if self.zero_reason else None)}


@dataclass(frozen=True)
class NettedLeg:
    """Attribution: one strategy's signed contribution to a symbol book.
    Authoritative attribution lives HERE and in the journal — never in
    position comments."""

    strategy_id: str
    symbol: str
    contribution: float              # weight * direction (signed)

    def to_dict(self) -> dict:
        return {"strategy_id": self.strategy_id, "symbol": self.symbol,
                "contribution": _r10(self.contribution)}


def _r10(x: float) -> float:
    return round(float(x), 10)


def canonical_json(obj) -> str:
    """Canonical serialization: sorted keys, compact separators, ASCII,
    floats rounded to 10 decimals.  Same input ⇒ byte-identical output."""
    return json.dumps(_round_floats(obj), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)


def _round_floats(obj):
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise MetaError(f"non-finite value in journal: {obj!r}")
        return _r10(obj)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v) for v in obj]
    return obj


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_text(path: str | os.PathLike, text: str) -> None:
    """File contract: atomic temp write + os.replace (same directory)."""
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".meta-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- configuration (Phase 16: exactly these tunables, no more) ---------


@dataclass(frozen=True)
class MetaConfig:
    """The COMPLETE tunable surface of the Meta Layer (six parameters).
    Everything else in the module is a fixed, documented constant."""

    mode: MetaMode = MetaMode.WEIGHTED_NETTING     # contract default
    policy: MetaPolicy = MetaPolicy.META           # or EQUAL_WEIGHT baseline
    vote_threshold: float = 0.6
    max_strategy_weight: float = 1.0
    gross_exposure_cap: float = 1.0
    max_weight_change: float = 1.0                 # 1.0 = limit off
    max_positions: int | None = None               # None = off

    def __post_init__(self):
        if not isinstance(self.mode, MetaMode):
            raise MetaConfigError("mode must be a MetaMode")
        if not isinstance(self.policy, MetaPolicy):
            raise MetaConfigError("policy must be a MetaPolicy")
        if not (0.5 < self.vote_threshold <= 1.0):
            raise MetaConfigError("vote_threshold must be in (0.5, 1.0]")
        for name in ("max_strategy_weight", "gross_exposure_cap",
                     "max_weight_change"):
            v = getattr(self, name)
            if not (math.isfinite(v) and 0.0 < v <= 1.0):
                raise MetaConfigError(f"{name} must be in (0, 1]")
        if self.max_positions is not None and (
                isinstance(self.max_positions, bool)
                or self.max_positions < 1):
            raise MetaConfigError("max_positions must be None or >= 1")

    @property
    def config_hash(self) -> str:
        return sha256_hex(canonical_json({
            "mode": self.mode.value, "policy": self.policy.value,
            "vote_threshold": self.vote_threshold,
            "max_strategy_weight": self.max_strategy_weight,
            "gross_exposure_cap": self.gross_exposure_cap,
            "max_weight_change": self.max_weight_change,
            "max_positions": self.max_positions}))[:16]


# ---- persisted restart state (Phase 19) --------------------------------


@dataclass
class MetaState:
    """Only runtime allocation state — NEVER training/OOS knowledge."""

    schema_version: int = 1
    decision_version: str = DECISION_VERSION
    config_hash: str = ""
    as_of: str = ""
    weights: dict[str, float] = field(default_factory=dict)
    zeroed: dict[str, str] = field(default_factory=dict)
    activation: str = ""                     # Phase 20: survives restart

    def to_dict(self) -> dict:
        return {"schema_version": self.schema_version,
                "decision_version": self.decision_version,
                "config_hash": self.config_hash, "as_of": self.as_of,
                "weights": {k: _r10(v) for k, v in sorted(self.weights.items())},
                "zeroed": dict(sorted(self.zeroed.items())),
                "activation": self.activation}

    def payload_json(self) -> str:
        return canonical_json(self.to_dict())

    def serialize(self) -> str:
        body = self.payload_json()
        return canonical_json({"body": json.loads(body),
                               "digest": sha256_hex(body)})

    @classmethod
    def deserialize(cls, text: str) -> MetaState:
        try:
            obj = json.loads(text)
            body = canonical_json(obj["body"])
            if sha256_hex(body) != obj["digest"]:
                raise MetaFileError("state digest mismatch")
            if obj["body"]["schema_version"] != 1:
                raise MetaFileError("unsupported state schema_version")
            if obj["body"]["decision_version"] != DECISION_VERSION:
                raise MetaFileError("decision_version mismatch")
            return cls(**obj["body"])
        except MetaFileError:
            raise
        except Exception as exc:
            raise MetaFileError(f"malformed meta state: {exc}") from exc


# ---- the layer (Phases 3–11) -------------------------------------------


@dataclass
class MetaDecision:
    as_of: str
    mode: str
    policy: str
    activation: str
    config_hash: str
    eligibility: dict[str, Eligibility]
    raw_scores: list[RawMetaScore]
    weights: list[MetaWeight]
    book: list[NettedLeg]                 # attribution (per contribution)
    net_by_symbol: dict[str, float]
    vote_by_symbol: dict[str, int]
    fallback: tuple[str, ...]             # (), ("equal_weight", src), ...
    versions: dict[str, str]
    prev_weights: dict[str, float]
    strategy_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of, "mode": self.mode, "policy": self.policy,
            "activation": self.activation, "config_hash": self.config_hash,
            "decision_version": DECISION_VERSION,
            "eligibility": [e.to_dict() for e in
                            _sorted_by_id(self.eligibility.values())],
            "raw_scores": [r.to_dict() for r in
                           _sorted_by_id(self.raw_scores)],
            "weights": [w.to_dict() for w in _sorted_by_id(self.weights)],
            "book": [b.to_dict() for b in _sorted_by_id(self.book)],
            "net_by_symbol": dict(sorted(self.net_by_symbol.items())),
            "vote_by_symbol": dict(sorted(self.vote_by_symbol.items())),
            "fallback": list(self.fallback),
            "versions": dict(sorted(self.versions.items())),
            "prev_weights": {k: _r10(v) for k, v in
                             sorted(self.prev_weights.items())},
            "strategy_versions": dict(sorted(
                self.strategy_versions.items())),
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def weight_of(self, strategy_id: str) -> float:
        for w in self.weights:
            if w.strategy_id == strategy_id:
                return w.final_weight
        return 0.0


def _sorted_by_id(items: Iterable) -> list:
    return sorted(items, key=lambda x: x.strategy_id)


class MetaLayer:
    """Deterministic allocation layer.  One instance may hold persisted
    restart state; decisions themselves are stateless functions of
    (inputs, config, previous persisted weights, returns window)."""

    def __init__(self, config: MetaConfig | None = None,
                 activation: Activation = Activation.DISABLED,
                 state: MetaState | None = None):
        self.config = config or MetaConfig()
        self.activation = activation
        self.state = state or MetaState(config_hash=self.config.config_hash)
        if self.state.config_hash and \
                self.state.config_hash != self.config.config_hash:
            raise MetaConfigError(
                "persisted state was produced by a different config; "
                "explicitly reset the state to change configuration")
        if self.state.activation:
            self.activation = Activation(self.state.activation)

    # -- Phase 18: activation ladder (explicit, audited, never automatic) -
    def transition(self, target: Activation, *, as_of: datetime,
                   journal: MetaDecisionJournal | None = None) -> None:
        if not self.activation.can_transition_to(target):
            raise MetaConfigError(
                f"illegal activation transition {self.activation.value} "
                f"-> {target.value} (ladder is "
                "DISABLED->SHADOW->DEMO->LIVE_SMALL->ACTIVE, explicit only)")
        self.activation = target
        if journal is not None:
            journal.append_transition(self.config.config_hash, _iso(as_of),
                                      target.value)

    # -- Phase 3: eligibility engine (BEFORE any scoring) ------------------
    def eligibility(self, inputs: Sequence[StrategyMetaInput],
                    *, as_of: datetime) -> dict[str, Eligibility]:
        out: dict[str, Eligibility] = {}
        for inp in _sorted_by_id(inputs):
            reason = self._ineligibility_reason(inp, as_of=as_of)
            out[inp.strategy_id] = Eligibility(
                inp.strategy_id, reason is None,
                reason or EligibilityReason.ELIGIBLE)
        return out

    @staticmethod
    def _ineligibility_reason(inp: StrategyMetaInput,
                              *, as_of: datetime) -> EligibilityReason | None:
        """First matching hard-block reason in fixed order."""
        if inp.kill_switch:
            return EligibilityReason.KILL_SWITCH
        if not inp.enabled:
            return EligibilityReason.DISABLED
        if inp.signal not in (-1, 0, 1):
            return EligibilityReason.CONFIG_INVALID
        if inp.drift_score is not None and (
                not math.isfinite(inp.drift_score)
                or not 0.0 <= inp.drift_score <= 1.0):
            return EligibilityReason.CONFIG_INVALID
        state = inp.certification_state
        if state is None:
            return EligibilityReason.UNCERTIFIED
        if state in ("FAILED", "NOT_ELIGIBLE"):
            return EligibilityReason.CERT_FAILED
        gate = GATE_WEIGHTS.get(state)
        if gate is None:
            return EligibilityReason.UNCERTIFIED
        if gate == 0.0:
            return EligibilityReason.CERT_FAILED
        if inp.regime in inp.regimes_forbidden:
            return EligibilityReason.REGIME_FORBIDDEN
        known = (inp.regimes_allowed | inp.regimes_preferred
                 | inp.regimes_forbidden)
        if inp.regime not in known:
            return EligibilityReason.REGIME_UNKNOWN
        if inp.cooldown_until is not None and as_of < inp.cooldown_until:
            return EligibilityReason.COOLDOWN
        if inp.stale:
            return EligibilityReason.STALE_DATA
        if inp.drift_available and inp.drift_score is not None \
                and inp.drift_score >= DRIFT_BLOCK:
            return EligibilityReason.DRIFT_BLOCK
        return None

    # -- Phase 4/5: factors -------------------------------------------------
    @staticmethod
    def _gate_factor(inp: StrategyMetaInput) -> MetaFactor:
        state = inp.certification_state
        return MetaFactor("gate_weight", GATE_WEIGHTS.get(state, 0.0),
                          "certification_record", "status-model-1")

    @staticmethod
    def _regime_factor(inp: StrategyMetaInput) -> MetaFactor:
        if inp.regime in inp.regimes_forbidden \
                or inp.regime not in (inp.regimes_allowed
                                      | inp.regimes_preferred
                                      | inp.regimes_forbidden):
            return MetaFactor("regime_fit", 0.0, "strategy_regime_metadata",
                              "regime-static-1")
        return MetaFactor("regime_fit", 1.0, "strategy_regime_metadata",
                          "regime-static-1")

    @staticmethod
    def _performance_factor(
            inp: StrategyMetaInput,
            oos_stats: Mapping[str, tuple[float, int]] | None
    ) -> MetaFactor:
        """OOS-derived ONLY, shrunk: e = (n·mean + k·0)/(n + k)."""
        if oos_stats and inp.strategy_id in oos_stats:
            mean_r, n = oos_stats[inp.strategy_id]
            n = int(n)
            if n > 0 and math.isfinite(mean_r):
                # winsorize BEFORE shrinking: a handful of outlier trades
                # can never dominate a long OOS record (spec Phase 5)
                mean_r = max(-PERF_CLIP, min(PERF_CLIP, float(mean_r)))
                e = (n * mean_r) / (n + PERF_PRIOR_N)
                val = min(PERF_CAP, max(PERF_FLOOR, PERF_SCALE * e + 0.5))
                return MetaFactor("performance_factor", val,
                                  "oos_attribution",
                                  f"shrink-k{PERF_PRIOR_N}")
        return MetaFactor("performance_factor", PERF_MISSING,
                          "oos_attribution", f"shrink-k{PERF_PRIOR_N}",
                          FactorStatus.MISSING_FALLBACK)

    @staticmethod
    def _drift_factor(inp: StrategyMetaInput) -> MetaFactor:
        if not inp.drift_available or inp.drift_score is None:
            return MetaFactor("drift_factor", DRIFT_MISSING, "drift_monitor",
                              "drift-1", FactorStatus.MISSING_FALLBACK)
        d = float(inp.drift_score)
        if d < DRIFT_MILD:
            val = 1.0
        elif d < DRIFT_BLOCK:
            # linear NO_DRIFT -> (worst mild) 0.5 over [0.10, 0.50)
            val = 1.0 - (d - DRIFT_MILD) / (DRIFT_BLOCK - DRIFT_MILD) * 0.5
        else:
            val = 0.0                      # hard-zeroed by eligibility
        return MetaFactor("drift_factor", val, "drift_monitor", "drift-1")

    # -- Phase 6: simultaneous correlation snapshot -------------------------
    @staticmethod
    def correlation_matrix(
            returns: pd.DataFrame | None, ids: Sequence[str], *,
            as_of: datetime
    ) -> tuple[pd.DataFrame, dict[str, FactorStatus], bool]:
        """Pairwise Pearson correlations over rows at or before ``as_of``.

        Returns (matrix, per-id status, global_failure).  Pairs with
        fewer than CORR_MIN_OBS overlapping observations contribute 0.0
        (flagged per id); NaN/inf stream values are invalid observations.
        A strategy's status is OK when AT LEAST ONE of its pairs is
        valid; global_failure is True when at least two candidates exist
        and NO pair reaches the minimum — the source is down for
        everyone.  (One missing pair or one uncorrelatable strategy is a
        per-strategy flag, never a global failure.)
        """
        ids = sorted(ids)
        has_valid = {i: False for i in ids}
        mat = pd.DataFrame(np.eye(len(ids)), index=ids, columns=ids)
        if returns is None or len(ids) < 2:
            return mat, {i: FactorStatus.OK for i in ids}, False
        ts = pd.Timestamp(as_of)
        if frame_index_tz := returns.index.tz:
            ts = ts.tz_localize(frame_index_tz) if ts.tzinfo is None \
                else ts.tz_convert(frame_index_tz)
        elif ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        frame = returns.loc[returns.index <= ts]
        for a_pos, a in enumerate(ids):
            for b in ids[a_pos + 1:]:
                if a not in frame.columns or b not in frame.columns:
                    continue
                pair = frame[[a, b]].dropna()
                pair = pair[np.isfinite(pair.to_numpy()).all(axis=1)]
                if len(pair) < CORR_MIN_OBS:
                    continue
                corr = float(np.corrcoef(pair[a].to_numpy(),
                                         pair[b].to_numpy())[0, 1])
                if not math.isfinite(corr):
                    continue
                mat.loc[a, b] = mat.loc[b, a] = max(-1.0, min(1.0, corr))
                has_valid[a] = has_valid[b] = True
        statuses = {i: (FactorStatus.OK if has_valid[i]
                        else FactorStatus.MISSING_FALLBACK) for i in ids}
        global_failure = len(ids) >= 2 and not any(has_valid.values())
        return mat, statuses, global_failure

    def _correlation_factors(
            self, ids: Sequence[str], corr: pd.DataFrame,
            corr_status: Mapping[str, FactorStatus]
    ) -> dict[str, MetaFactor]:
        """pen_i = clip(1 - Σ_j prior_j·max(corr_ij, 0), PEN_FLOOR, 1).

        ``prior`` = previous persisted final weights (renormalized), or
        equal prior.  The sum iterates ids in sorted order — a single
        simultaneous pass, identical under any input permutation.
        """
        ids = sorted(ids)
        prev = {k: v for k, v in self.state.weights.items() if k in ids}
        total = sum(prev.values())
        if total > 0.0 and len(prev) == len(ids):
            prior = {i: prev[i] / total for i in ids}
        else:
            prior = {i: 1.0 / len(ids) for i in ids} if ids else {}
        out: dict[str, MetaFactor] = {}
        for a in ids:
            pen = 1.0
            for b in ids:                       # sorted order: order-free sum
                if b == a:
                    continue
                c = float(corr.loc[a, b])
                pen -= prior[b] * max(c, 0.0)
            pen = min(1.0, max(PEN_FLOOR, pen))
            status = corr_status.get(a, FactorStatus.OK)
            out[a] = MetaFactor("correlation_penalty", pen,
                                "historical_returns+prev_allocation",
                                "corr-1", status)
        return out

    # -- Phase 7/8/9/10/11: decide ------------------------------------------
    def decide(
            self, inputs: Sequence[StrategyMetaInput], *,
            as_of: datetime,
            returns: pd.DataFrame | None = None,
            oos_stats: Mapping[str, tuple[float, int]] | None = None,
    ) -> MetaDecision:
        for other in _dupes(i.strategy_id for i in inputs):
            raise MetaConfigError(f"duplicate strategy_id: {other!r}")
        elig = self.eligibility(inputs, as_of=as_of)
        eligible_ids = [e.strategy_id for e in _sorted_by_id(elig.values())
                        if e.eligible]

        by_id = {i.strategy_id: i for i in inputs}
        fallback: list[str] = []
        weights: dict[str, MetaWeight] = {}
        raw_scores: list[RawMetaScore] = []
        pre_cap: dict[str, float] = {}

        if not eligible_ids:
            fallback.append("none_eligible")     # SAFE HOLD, not equal weight
        else:
            corr, corr_status, corr_global = self.correlation_matrix(
                returns, eligible_ids, as_of=as_of)
            perf_factors = {i: self._performance_factor(by_id[i], oos_stats)
                            for i in eligible_ids}
            perf_global = all(
                f.status is FactorStatus.MISSING_FALLBACK
                for f in perf_factors.values())
            drift_factors = {i: self._drift_factor(by_id[i])
                             for i in eligible_ids}
            drift_global = all(
                f.status is FactorStatus.MISSING_FALLBACK
                for f in drift_factors.values())
            global_source = next((src for src, bad in
                                  (("correlation", corr_global),
                                   ("performance", perf_global),
                                   ("drift", drift_global)) if bad), None)

            if global_source is not None \
                    and self.config.policy is MetaPolicy.META:
                # GLOBAL source failure -> equal-weight fallback over
                # ELIGIBLE strategies only (contract §5.3/§5.3a)
                fallback.append("equal_weight")
                fallback.append(f"source:{global_source}")
                eq = 1.0 / len(eligible_ids)
                pre_cap = {i: eq for i in eligible_ids}
                raw_scores = []
            else:
                for i in eligible_ids:
                    if self.config.policy is MetaPolicy.EQUAL_WEIGHT:
                        f5 = [MetaFactor(n, 1.0, "baseline", "equal-weight-1")
                              for n in ("gate_weight", "regime_fit",
                                        "performance_factor",
                                        "correlation_penalty",
                                        "drift_factor")]
                    else:
                        f5 = [self._gate_factor(by_id[i]),
                              self._regime_factor(by_id[i]),
                              perf_factors[i],
                              self._correlation_factors(eligible_ids,
                                                        corr,
                                                        corr_status)[i],
                              drift_factors[i]]
                    raw = 1.0
                    for f in f5:
                        raw *= f.value
                    raw_scores.append(RawMetaScore(i, tuple(f5), raw))
                total = sum(r.raw_score for r in raw_scores)
                if total <= 0.0:
                    # unreachable with non-negative factors, kept as a
                    # guard: proportional shares need a positive mass
                    fallback.append("none_eligible")
                else:
                    pre_cap = {r.strategy_id: r.raw_score / total
                               for r in raw_scores}

            weights = self._apply_budget(pre_cap, eligible_ids)
            weights = self._apply_modes(weights, by_id, raw_scores, elig)

        # every input gets a MetaWeight row (zero for ineligible)
        for e in _sorted_by_id(elig.values()):
            if e.strategy_id not in weights:
                weights[e.strategy_id] = MetaWeight(
                    e.strategy_id, 0.0, 0.0, (), e.reason)

        book, net_by_symbol, vote_by_symbol = self._build_book(
            weights, by_id)
        decision = MetaDecision(
            as_of=_iso(as_of), mode=self.config.mode.value,
            policy=self.config.policy.value,
            activation=self.activation.value,
            config_hash=self.config.config_hash,
            eligibility=elig, raw_scores=raw_scores,
            weights=[weights[e.strategy_id]
                     for e in _sorted_by_id(elig.values())],
            book=book, net_by_symbol=net_by_symbol,
            vote_by_symbol=vote_by_symbol, fallback=tuple(fallback),
            versions=self._versions(), prev_weights=dict(
                sorted(self.state.weights.items())),
            strategy_versions={
                i.strategy_id: i.strategy_version
                for i in inputs if i.strategy_version})
        self._advance_state(decision)
        return decision

    # -- budget: shares -> caps -> redistribution -> gross -> constraints ---
    def _apply_budget(self, pre_cap: Mapping[str, float],
                      eligible_ids: Sequence[str]
                      ) -> dict[str, MetaWeight]:
        out: dict[str, MetaWeight] = {}
        if not pre_cap:
            return {i: MetaWeight(i, 0.0, 0.0, (),
                                  EligibilityReason.ELIGIBLE)
                    for i in eligible_ids}
        cap = self.config.max_strategy_weight
        assigned = {i: min(pre_cap[i], cap) for i in pre_cap}
        capped = {i for i in assigned if assigned[i] < pre_cap[i] - 1e-15}
        # bounded deterministic redistribution into uncapped ELIGIBLE only
        for _ in range(100):
            if not capped:
                break
            open_ids = [i for i in sorted(pre_cap) if i not in capped]
            if not open_ids:
                break                      # leftover stays unallocated
            mass = sum(pre_cap[i] - assigned[i] for i in capped)
            base = sum(pre_cap[i] for i in open_ids)
            progressed = False
            for i in open_ids:
                add = mass * (pre_cap[i] / base) if base > 0 else \
                    mass / len(open_ids)
                room = cap - assigned[i]
                take = min(add, room)
                if take > 1e-15:
                    assigned[i] += take
                    progressed = True
                if assigned[i] >= cap - 1e-15:
                    capped.add(i)
            if not progressed:
                break
        budget = self.config.gross_exposure_cap
        for i in sorted(assigned):
            w = assigned[i] * budget
            reasons = []
            if i in capped:
                reasons.append("MAX_STRATEGY_WEIGHT")
            out[i] = MetaWeight(i, _r10(pre_cap[i]), _r10(w),
                                tuple(reasons))
        # portfolio constraints that only reduce: max_positions
        if self.config.max_positions is not None:
            live = [w for w in out.values() if w.final_weight > 0.0]
            keep = sorted(live, key=lambda w: (-w.final_weight,
                                               w.strategy_id))
            for w in keep[self.config.max_positions:]:
                out[w.strategy_id] = MetaWeight(
                    w.strategy_id, w.pre_cap_share, 0.0,
                    w.clamp_reasons, EligibilityReason.MAX_POSITIONS)
        return out

    # -- Phase 9: combination modes (mode fixed in config) ------------------
    def _apply_modes(self, weights: Mapping[str, MetaWeight],
                     by_id: Mapping[str, StrategyMetaInput],
                     raw_scores: Sequence[RawMetaScore],
                     elig: Mapping[str, Eligibility]
                     ) -> dict[str, MetaWeight]:
        out = dict(weights)
        if self.config.mode is MetaMode.BEST_OF_REGIME and raw_scores:
            # max by (score desc, id asc) — NOT a plain min/max: the
            # lexical tie-break is part of the contract
            best = sorted(  # noqa: FURB192 — lexical tie-break is contract
                raw_scores,
                key=lambda r: (-r.raw_score, r.strategy_id))[0]
            winner_w = min(1.0, self.config.max_strategy_weight) \
                * self.config.gross_exposure_cap
            for sid, w in list(out.items()):
                if sid == best.strategy_id:
                    out[sid] = MetaWeight(sid, w.pre_cap_share, _r10(winner_w),
                                          ("BEST_OF_REGIME_WINNER",))
                else:
                    out[sid] = MetaWeight(sid, w.pre_cap_share, 0.0,
                                          w.clamp_reasons,
                                          EligibilityReason
                                          .BEST_OF_REGIME_LOSER)
        # WEIGHTED_NETTING / VOTE / INDEPENDENT do not rescale weights;
        # they shape the BOOK (see _build_book).  The daily change limit
        # applies to surviving weights, constraint zeros stay zero.
        prev = self.state.weights
        maxc = self.config.max_weight_change
        changed: dict[str, MetaWeight] = {}
        for sid, w in out.items():
            target = w.final_weight
            if target == 0.0 and w.zero_reason is not None:
                changed[sid] = w              # hard/constraint zero: immediate
                continue
            if sid in prev and maxc < 1.0:
                lo, hi = prev[sid] - maxc, prev[sid] + maxc
                clipped = min(max(target, max(lo, 0.0)), min(hi, 1.0))
                if abs(clipped - target) > 1e-15:
                    changed[sid] = MetaWeight(
                        sid, w.pre_cap_share, _r10(clipped),
                        w.clamp_reasons + ("WEIGHT_CHANGE_LIMIT",),
                        w.zero_reason)
                    continue
            changed[sid] = w
        return changed

    # -- Phase 10: attribution book ------------------------------------------
    def _build_book(
            self, weights: Mapping[str, MetaWeight],
            by_id: Mapping[str, StrategyMetaInput]
    ) -> tuple[list[NettedLeg], dict[str, float], dict[str, int]]:
        book: list[NettedLeg] = []
        net: dict[str, float] = {}
        votes: dict[str, dict[int, float]] = {}
        for sid in sorted(weights):
            w = weights[sid].final_weight
            inp = by_id[sid]
            if w > 0.0 and inp.signal != 0:
                book.append(NettedLeg(sid, inp.symbol, w * inp.signal))
                net[inp.symbol] = net.get(inp.symbol, 0.0) + w * inp.signal
                d = votes.setdefault(inp.symbol, {})
                d[inp.signal] = d.get(inp.signal, 0.0) + w
        vote_by_symbol: dict[str, int] = {}
        if self.config.mode is MetaMode.VOTE:
            thr = self.config.vote_threshold
            for symbol in sorted(votes):
                masses = votes[symbol]
                agree_dir = 1 if masses.get(1, 0.0) >= masses.get(
                    -1, 0.0) else -1
                agree = masses.get(agree_dir, 0.0)
                against = masses.get(-agree_dir, 0.0)
                total = agree + against
                # fires iff threshold met AND strictly more agree mass;
                # exact tie or below-threshold -> no trade
                if total > 0.0 and agree > against \
                        and agree / total >= thr:
                    vote_by_symbol[symbol] = agree_dir
        return (_sorted_by_id(book),
                {k: _r10(v) for k, v in sorted(net.items())},
                vote_by_symbol)

    def _versions(self) -> dict[str, str]:
        return {"meta_layer_version": META_LAYER_VERSION,
                "decision_version": DECISION_VERSION,
                "engine_version": ENGINE_VERSION,
                "cost_model_version": COST_MODEL_VERSION,
                "contract_version": CONTRACT_VERSION}

    def _advance_state(self, decision: MetaDecision) -> None:
        """Restart state: final weights + zero reasons only."""
        self.state = MetaState(
            config_hash=self.config.config_hash, as_of=decision.as_of,
            weights={w.strategy_id: w.final_weight for w in decision.weights},
            zeroed={w.strategy_id: w.zero_reason.value
                    for w in decision.weights
                    if w.zero_reason is not None},
            activation=self.activation.value)

    # -- Phase 17/30: shadow comparison + safe failure -----------------------
    def shadow_divergence(self, shadow: MetaDecision,
                          actual: MetaDecision) -> dict:
        ids = sorted({w.strategy_id for w in shadow.weights}
                     | {w.strategy_id for w in actual.weights})
        wmap = {p.policy: {w.strategy_id: w.final_weight
                           for w in p.weights}
                for p in (shadow, actual)}
        l1 = sum(abs(wmap["meta"].get(i, 0.0) - wmap["equal_weight"]
                     .get(i, 0.0)) for i in ids)
        return {"weight_l1": _r10(l1),
                "signal_symbols_shadow": sorted(shadow.net_by_symbol),
                "signal_symbols_actual": sorted(actual.net_by_symbol),
                "gross_shadow": _r10(sum(abs(v) for v in
                                         wmap["meta"].values())),
                "gross_actual": _r10(sum(abs(v) for v in
                                         wmap["equal_weight"].values()))}


def _dupes(ids: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for i in ids:
        if i in seen and i not in out:
            out.append(i)
        seen.add(i)
    return out


def safe_decision(layer: MetaLayer, *args, **kwargs) -> tuple[
        MetaDecision, BaseException | None]:
    """Phase 30: any internal failure ⇒ SAFE HOLD decision (no weights,
    no new trades), never last-known-good weights, never a raise into
    the trading path."""
    try:
        return layer.decide(*args, **kwargs), None
    except BaseException as exc:  # noqa: BLE001 — fail-safe boundary
        _LOG.exception("meta decision failed -> SAFE HOLD")
        return MetaDecision(
            as_of=_iso(kwargs.get("as_of") or _utcnow()),
            mode=layer.config.mode.value, policy=layer.config.policy.value,
            activation=layer.activation.value,
            config_hash=layer.config.config_hash, eligibility={},
            raw_scores=[], weights=[], book=[], net_by_symbol={},
            vote_by_symbol={}, fallback=("failure_safe",),
            versions=layer._versions(), prev_weights={}), exc


# ---- Phase 21: allocation file (SPEC line 107 contract) -----------------


def write_allocation_file(decision: MetaDecision, path) -> str:
    """Canonical in/allocation.json writer: schema_version 1, computed_at,
    per-strategy weight + explanation fields; atomic temp write +
    os.replace; self-digest.  Malformed output is impossible by
    construction and detected by read_allocation_file."""
    body = {
        "schema_version": ALLOCATION_SCHEMA_VERSION,
        "computed_at": decision.as_of,
        "config_hash": decision.config_hash,
        "mode": decision.mode,
        "activation": decision.activation,
        "strategies": [
            {"id": w.strategy_id, "weight": _r10(w.final_weight),
             "eligible": _elig(decision, w.strategy_id),
             "reasons": _reasons(decision, w.strategy_id),
             "factors": _factors(decision, w.strategy_id)}
            for w in sorted(decision.weights,
                            key=lambda w: w.strategy_id)],
        "net_by_symbol": decision.net_by_symbol,
        "strategy_versions": dict(sorted(
            decision.strategy_versions.items())),
    }
    payload = canonical_json(body)
    doc = canonical_json({"body": json.loads(payload),
                          "digest": sha256_hex(payload)})
    _atomic_write_text(path, doc)
    return doc


def _elig(decision: MetaDecision, sid: str) -> bool:
    e = decision.eligibility.get(sid)
    return bool(e and e.eligible)


def _reasons(decision: MetaDecision, sid: str) -> list[str]:
    out = []
    e = decision.eligibility.get(sid)
    if e is not None:
        out.append(e.reason.value)
    w = next((w for w in decision.weights if w.strategy_id == sid), None)
    if w is not None:
        out.extend(w.clamp_reasons)
        if w.zero_reason is not None:
            out.append(w.zero_reason.value)
    return out


def _factors(decision: MetaDecision, sid: str) -> dict:
    r = next((r for r in decision.raw_scores if r.strategy_id == sid),
             None)
    return {f.name: _r10(f.value) for f in r.factors} if r else {}


def read_allocation_file(path, *, max_age_days: float = STALE_AFTER_DAYS,
                         now: datetime | None = None) -> dict:
    """Validate an allocation file.  Returns the parsed body with a
    ``stale`` flag.  Raises MetaFileError on ANY malformation — the
    caller (and the EA) must never apply a malformed allocation."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise MetaFileError(f"allocation unreadable: {exc}") from exc
    try:
        obj = json.loads(text)
        body = obj["body"]
        payload = canonical_json(body)
        if sha256_hex(payload) != obj["digest"]:
            raise MetaFileError("allocation digest mismatch")
        if str(body["schema_version"]) != ALLOCATION_SCHEMA_VERSION:
            raise MetaFileError("unsupported allocation schema_version")
        entries = body["strategies"]
        seen = set()
        for entry in entries:
            sid = entry["id"]
            if not isinstance(sid, str) or not sid or sid in seen:
                raise MetaFileError(f"bad strategy id: {sid!r}")
            seen.add(sid)
            w = entry["weight"]
            if isinstance(w, bool) or not isinstance(w, (int, float)) \
                    or not math.isfinite(w) or not 0.0 <= w <= 1.0:
                raise MetaFileError(f"bad weight for {sid}: {w!r}")
    except MetaFileError:
        raise
    except Exception as exc:
        raise MetaFileError(f"malformed allocation: {exc}") from exc
    body = dict(body)
    now = now or _utcnow()
    try:
        computed = datetime.fromisoformat(body["computed_at"])
        # tolerate naive callers/hosts: treat naive stamps as UTC
        if computed.tzinfo is None and now.tzinfo is not None:
            computed = computed.replace(tzinfo=timezone.utc)
        if now.tzinfo is None and computed.tzinfo is not None:
            now = now.replace(tzinfo=timezone.utc)
        age_days = (now - computed).total_seconds() / 86400.0
    except (ValueError, TypeError, KeyError) as exc:
        raise MetaFileError(f"bad computed_at: {exc}") from exc
    body["stale"] = bool(age_days > max_age_days)
    body["age_days"] = _r10(age_days)
    return body


# ---- Phase 20: journal ---------------------------------------------------


class MetaDecisionJournal:
    """Append-only decision journal; canonical, strategy_id-ascending,
    byte-identical for identical inputs."""

    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._transitions: list[dict] = []

    def append(self, decision: MetaDecision) -> None:
        self._entries.append(json.loads(decision.canonical_json()))

    def append_transition(self, config_hash: str, as_of: str,
                          target: str) -> None:
        self._transitions.append(json.loads(canonical_json(
            {"event": "ACTIVATION_TRANSITION", "as_of": as_of,
             "to": target, "config_hash": config_hash})))

    @property
    def entries(self) -> list[dict]:
        return list(self._entries)

    def canonical_json(self) -> str:
        return canonical_json({"decision_version": DECISION_VERSION,
                               "transitions": self._transitions,
                               "decisions": self._entries})

    def save(self, path) -> None:
        _atomic_write_text(path, self.canonical_json())
