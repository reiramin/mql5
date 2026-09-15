"""mql5bot.factory.models — Factory persistence schema (mission §18).

SQLAlchemy 2.0 models; SQLite storage, local-first.  Schema changes go
through Alembic ONLY (mission §72); this module is the baseline.

Immutability contract (mission §19/§40, enforced by the store facade):

- ``strategy_versions.spec_hash`` / ``spec_json`` are written ONCE;
- re-running validation INSERTS a new ``validation_runs`` row — prior
  evidence is never mutated;
- ``lifecycle_events`` is append-only;
- claims live in ``strategy_claims`` (AUTHOR_CLAIM) and are never
  merged into ``validation_metrics`` (measured).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Strategy(Base):
    """Identity + current lifecycle pointer (mutable pointer ONLY)."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    created_by: Mapped[str] = mapped_column(String(120), default="")
    current_state: Mapped[str] = mapped_column(String(24), default="DRAFT")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    family: Mapped[str] = mapped_column(String(60), default="")
    # flags
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class StrategyVersion(Base):
    """IMMUTABLE specification for one (strategy_id, version)."""

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version",
                         name="uq_strategy_version"),
        UniqueConstraint("spec_hash", name="uq_spec_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    spec_hash: Mapped[str] = mapped_column(String(64))
    semantic_hash: Mapped[str] = mapped_column(String(64))
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    spec_json: Mapped[str] = mapped_column(Text)     # normalized document
    parent_strategy_id: Mapped[str | None] = mapped_column(String(64),
                                                           nullable=True)
    parent_version: Mapped[int | None] = mapped_column(Integer,
                                                       nullable=True)
    dsl_version: Mapped[str] = mapped_column(String(16))
    generator_version: Mapped[str] = mapped_column(String(32),
                                                   default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class StrategySource(Base):
    """Provenance (mission §5): where an idea came from."""

    __tablename__ = "strategy_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(40))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(100),
                                                 nullable=True)
    retrieved_at: Mapped[str | None] = mapped_column(String(40),
                                                     nullable=True)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_claims: Mapped[list | None] = mapped_column(JSON,
                                                          nullable=True)
    provenance_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class StrategyClaim(Base):
    """AUTHOR_CLAIM (mission §13): claimed ≠ measured. Ever."""

    __tablename__ = "strategy_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    metric: Mapped[str] = mapped_column(String(60))
    claimed_value: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class ValidationRun(Base):
    """Every validation execution (append-only; §40)."""

    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    run_type: Mapped[str] = mapped_column(String(40))   # parse|schema|backtest|...
    status: Mapped[str] = mapped_column(String(16))     # PASS|FAIL|ERROR
    gate_version: Mapped[str] = mapped_column(String(32), default="")
    code_commit: Mapped[str] = mapped_column(String(64), default="")
    dataset_hash: Mapped[str] = mapped_column(String(64), default="")
    config_hash: Mapped[str] = mapped_column(String(64), default="")
    spec_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ValidationMetric(Base):
    """Measured metrics (independently measured — never claims)."""

    __tablename__ = "validation_metrics"
    __table_args__ = (Index("ix_valmetric_run", "run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"))
    name: Mapped[str] = mapped_column(String(60))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample: Mapped[str] = mapped_column(String(16), default="IS")  # IS|OOS|WFA|MC|SHADOW|LIVE


class ValidationArtifact(Base):
    """Artifact integrity (mission §75): no provenance → no evidence."""

    __tablename__ = "validation_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"))
    strategy_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class LifecycleEvent(Base):
    """Append-only state changes (mission §20)."""

    __tablename__ = "lifecycle_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    from_state: Mapped[str] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(16))   # promote|fail|recover|retire
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text, default="")
    gate_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class PromotionDecision(Base):
    """Who/what/when/why for every promotion (mission §20/§51)."""

    __tablename__ = "promotion_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    from_state: Mapped[str] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24))
    decision: Mapped[str] = mapped_column(String(16))  # APPROVED|DENIED
    actor: Mapped[str] = mapped_column(String(120))
    human_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    evidence_hash: Mapped[str] = mapped_column(String(64), default="")
    policy_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class ShadowObservation(Base):
    """Shadow evidence (mission §33): signals + hypothetical PnL, no
    orders — ever."""

    __tablename__ = "shadow_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                            default=utcnow)
    symbol: Mapped[str] = mapped_column(String(30), default="")
    signal: Mapped[int] = mapped_column(Integer)        # -1/0/+1
    executed_would_be: Mapped[bool] = mapped_column(Boolean, default=False)
    hypothetical_pnl: Mapped[float | None] = mapped_column(
        Float, nullable=True)
    spread_assumed: Mapped[float | None] = mapped_column(Float,
                                                         nullable=True)
    slippage_assumed: Mapped[float | None] = mapped_column(Float,
                                                           nullable=True)
    regime: Mapped[str | None] = mapped_column(String(24), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LiveObservation(Base):
    """Live/demo evidence from the EA roundtrip (read-only mirror)."""

    __tablename__ = "live_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.strategy_id"))
    version: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                            default=utcnow)
    mode: Mapped[str] = mapped_column(String(12))       # demo|live_small|live
    metric: Mapped[str] = mapped_column(String(60))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Alert(Base):
    """Failures and degradation (mission §57)."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str | None] = mapped_column(String(64),
                                                    nullable=True)
    severity: Mapped[str] = mapped_column(String(16))   # INFO|WARN|CRITICAL
    code: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)



class DiscoveryCampaign(Base):
    __tablename__ = "discovery_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    parent_campaign_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True)
    stage: Mapped[str] = mapped_column(String(32))          # current stage
    status: Mapped[str] = mapped_column(String(24))  # RUNNING|PAUSED|DONE|ABORTED
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    manifest_hash: Mapped[str] = mapped_column(String(64), default="")
    policy_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")
    dataset_hash: Mapped[str] = mapped_column(String(128), default="")
