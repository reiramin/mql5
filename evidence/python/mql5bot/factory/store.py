"""mql5bot.factory.store — the Factory persistence facade.

Enforces the persistence contract on every path:

- **Idempotent registration** (§40): the same normalized spec (same
  spec_hash) registers once; re-submission returns the existing
  version.  The same (strategy_id, version) with a DIFFERENT spec is
  REFUSED — logic changes must create version+1 (§19).
- **Append-only evidence**: validation runs insert; nothing updates.
- **Evidence-gated lifecycle**: state changes go through
  ``lifecycle.check_transition`` and every referenced evidence id must
  exist — an arbitrary status update cannot promote (§20).
- **Human approval boundary** (§51): promotions into DEMO and beyond
  require ``human_approval=True`` with an actor — the store refuses
  otherwise, regardless of the state machine's verdict.
- **Restart-safe** (§39): everything is rows; ``FactoryStore(path)``
  reopens the same file with identical behavior.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ..dsl import StrategySpec
from . import lifecycle as lc
from .models import (
    Alert,
    Base,
    LifecycleEvent,
    LiveObservation,
    PromotionDecision,
    ShadowObservation,
    Strategy,
    StrategyClaim,
    StrategySource,
    StrategyVersion,
    ValidationMetric,
    ValidationRun,
    utcnow,
)

FACTORY_SCHEMA_VERSION = "1.0.0"
HUMAN_APPROVAL_STATES = frozenset({"DEMO", "LIVE_SMALL", "LIVE"})


def _provenance_hash(source: dict) -> str:
    payload = json.dumps(source, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Roles that may carry human_approval=True.  Anything else (llm:,
# factory:, ml:, optimizer:, interpreter:, gate:) is a MACHINE and can
# never self-approve a human-gated transition (convergence §32/§65#21).
_HUMAN_ACTOR_PREFIXES = ("owner", "ui:", "human:")


def _evidence_digest(sess, refs: tuple) -> str:
    """§32: the approval record binds a hash of the ACTUAL evidence
    rows (type+status+spec_hash), not just their ids."""
    import hashlib
    if not refs:
        return ""
    parts = []
    for rid in refs:
        row = sess.get(ValidationRun, int(rid))
        if row is not None:
            parts.append(f"{row.id}|{row.run_type}|{row.status}|"
                         f"{row.spec_hash}")
    return hashlib.sha256(";".join(parts).encode()).hexdigest() if parts \
        else ""


class StoreError(Exception):
    """Refusal with a human-readable reason (never silent)."""


class FactoryStore:
    def __init__(self, path: str | Path = "factory.db"):
        self.path = Path(path)
        self.engine = create_engine(f"sqlite:///{self.path}",
                                    future=True)
        Base.metadata.create_all(self.engine)
        self._session_maker = sessionmaker(self.engine, future=True)

    # ------------------------------------------------------------ helpers

    def session(self) -> Session:
        return self._session_maker()

    # ------------------------------------------------------------ registration

    def register_strategy(self, spec: StrategySpec, *, created_by: str,
                          source: dict | None = None,
                          original_text: str | None = None,
                          claims: list[dict] | None = None,
                          family: str = "",
                          parent: tuple[str, int] | None = None,
                          ) -> tuple[int, bool]:
        """Register one immutable version.  Returns (version_row_id,
        created).  Idempotent by spec_hash; refuses to overwrite.

        A DRAFT (non-executable) spec may be registered for the intake
        flow but can never leave DRAFT (the lifecycle refuses without
        parse/schema evidence; the runtime refuses to run it).
        """
        if not spec.executable and spec.version != 0:
            # drafts are stored at version 0 until ambiguities resolve;
            # a numbered version must be executable
            raise StoreError(
                "non-executable (ambiguous) spec must be registered at "
                "version 0 (draft); resolve ambiguities, then register "
                "an executable version")
        with self.session() as sess:
            existing_version = sess.scalar(
                select(StrategyVersion).where(
                    StrategyVersion.spec_hash == spec.spec_hash))
            if existing_version is not None:
                return existing_version.id, False

            id_conflict = sess.scalar(
                select(StrategyVersion).where(
                    StrategyVersion.strategy_id == spec.strategy_id,
                    StrategyVersion.version == spec.version))
            if id_conflict is not None:
                raise StoreError(
                    f"{spec.strategy_id} v{spec.version} exists with a "
                    "DIFFERENT spec — strategy versions are immutable; "
                    "create version "
                    f"{spec.version + 1} (mission §19)")

            strat = sess.scalar(select(Strategy).where(
                Strategy.strategy_id == spec.strategy_id))
            if strat is None:
                strat = Strategy(strategy_id=spec.strategy_id,
                                 created_by=created_by, family=family,
                                 current_state=lc.DRAFT)
                sess.add(strat)
                sess.flush()
            else:
                if spec.version <= strat.current_version and \
                        strat.current_version > 0:
                    raise StoreError(
                        f"version {spec.version} does not exceed "
                        f"current {strat.current_version} — versions "
                        "are append-only")
                if strat.current_state not in (lc.DRAFT, lc.REJECTED) \
                        and parent is None:
                    # §25 lineage: budgeted research mutation registers
                    # CHILD versions with an explicit parent link — the
                    # active line is never overwritten, so a research
                    # branch may open even while an observed state runs
                    raise StoreError(
                        f"{spec.strategy_id} is {strat.current_state}; "
                        "new versions enter at DRAFT via a parent "
                        "linkage, not by overwriting the active line")

            ver = StrategyVersion(
                strategy_id=spec.strategy_id, version=spec.version,
                spec_hash=spec.spec_hash,
                semantic_hash=spec.semantic_hash,
                dedup_hash=spec.dedup_hash,
                spec_json=json.dumps(spec.document, sort_keys=True,
                                     separators=(",", ":"),
                                     ensure_ascii=False),
                parent_strategy_id=parent[0] if parent else None,
                parent_version=parent[1] if parent else None,
                dsl_version="1.0")
            sess.add(ver)
            # a NEW version is a NEW lifecycle line: it starts at DRAFT
            # (its own evidence-gated ladder; the previous version's
            # history stays bound to that version, gate §6)
            strat.current_state = lc.DRAFT
            sess.flush()

            if source or original_text:
                # provenance §5/§20: the raw source text is persisted
                # verbatim as DATA even when no structured metadata
                # accompanies it
                sess.add(StrategySource(
                    strategy_id=spec.strategy_id, version=spec.version,
                    source_type=source.get("type", "HUMAN") if source
                    else "HUMAN",
                    url=(source or {}).get("url"),
                    author=(source or {}).get("author"),
                    platform=(source or {}).get("platform"),
                    retrieved_at=(source or {}).get("retrieved_at"),
                    license_note=(source or {}).get("license_note"),
                    original_text=original_text,
                    extracted_claims=list(claims or []) or None,
                    provenance_hash=_provenance_hash(source or {})))
            for c in claims or []:
                sess.add(StrategyClaim(
                    strategy_id=spec.strategy_id, version=spec.version,
                    metric=str(c.get("metric", "unknown")),
                    claimed_value=str(c.get("value")),
                    unit=c.get("unit"),
                    note=c.get("note"),
                    source_url=c.get("source_url")))
            sess.commit()
            return ver.id, True

    # ------------------------------------------------------------ validation evidence

    def record_run(self, strategy_id: str, version: int, *,
                   run_type: str, status: str, spec_hash: str,
                   metrics: dict[str, float] | None = None,
                   metric_samples: dict[str, str] | None = None,
                   dataset_hash: str = "", config_hash: str = "",
                   gate_version: str = "", code_commit: str = "",
                   detail: dict | None = None) -> int:
        """Insert a NEW validation run (append-only) + its metrics."""
        if status not in {"PASS", "FAIL", "ERROR"}:
            raise StoreError(f"invalid run status {status!r}")
        with self.session() as sess:
            run = ValidationRun(
                strategy_id=strategy_id, version=version,
                run_type=run_type, status=status,
                spec_hash=spec_hash, dataset_hash=dataset_hash,
                config_hash=config_hash, gate_version=gate_version,
                code_commit=code_commit, detail=detail,
                finished_at=utcnow())
            sess.add(run)
            sess.flush()
            samples = metric_samples or {}
            for name, value in (metrics or {}).items():
                sess.add(ValidationMetric(
                    run_id=run.id, name=name, value=float(value),
                    sample=samples.get(name, "IS")))
            sess.commit()
            return run.id

    def run_evidence_ok(self, run_id: int, run_type: str,
                        must_pass: bool = True) -> bool:
        """``run_type="*"`` is the existence wildcard used by the
        transition pre-check; specific types are for the gate engine."""
        with self.session() as sess:
            run = sess.get(ValidationRun, int(run_id))
            if run is None:
                return False
            if run_type != "*" and run.run_type != run_type:
                return False
            return run.status == "PASS" if must_pass else True

    def evidence_binds_to(self, run_id: int, strategy_id: str,
                          version: int,
                          run_types: tuple = ()) -> bool:
        """RED-TEAM §28.14/§28.15 + gate §15: an evidence ref may only
        serve the EXACT (strategy, version, spec_hash) it was produced
        for, must be a PASS run, and (when ``run_types`` given) must be
        of an adequate kind — cross-version, cross-strategy, stale-
        campaign, failed, or wrong-type artifacts are not evidence."""
        with self.session() as sess:
            run = sess.get(ValidationRun, int(run_id))
            if run is None or run.status != "PASS" or \
                    run.strategy_id != strategy_id or \
                    int(run.version) != int(version):
                return False
            if run_types and run.run_type not in run_types:
                return False
            ver = sess.scalar(select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy_id,
                StrategyVersion.version == int(version)))
            return (ver is not None
                    and run.spec_hash == ver.spec_hash)

    # ------------------------------------------------------------ lifecycle

    def current_state(self, strategy_id: str) -> str:
        with self.session() as sess:
            strat = sess.scalar(select(Strategy).where(
                Strategy.strategy_id == strategy_id))
            if strat is None:
                raise StoreError(f"unknown strategy {strategy_id!r}")
            return strat.current_state

    def transition(self, strategy_id: str, version: int, target: str,
                   *, evidence_refs: tuple = (), actor: str,
                   reason: str = "", human_approval: bool = False,
                   gate_version: str = "",
                   policy_version: str = "") -> str:
        """Attempt a lifecycle transition; returns the new state.

        Refusals (never silent):
        - the state machine forbids the move;
        - a promotion's evidence refs do not exist / are not PASS;
        - a promotion into DEMO/LIVE_SMALL/LIVE lacks human approval.
        """
        cur = self.current_state(strategy_id)
        try:
            event = lc.check_transition(cur, target,
                                        evidence_refs=evidence_refs,
                                        actor=actor)
        except lc.IllegalTransition as e:
            # the store is the boundary: every refusal is StoreError
            raise StoreError(str(e)) from e
        if event.kind == "promote" and \
                event.to_state in HUMAN_APPROVAL_STATES and \
                not human_approval:
            raise StoreError(
                f"{cur} → {target} requires explicit human approval "
                "(mission §51: first activation / live allocation "
                "changes are owner decisions)")
        if event.kind == "promote" and human_approval and \
                event.to_state in HUMAN_APPROVAL_STATES and \
                not str(actor).lower().startswith(_HUMAN_ACTOR_PREFIXES):
            # convergence §65 attack 21: a machine role (llm/factory/
            # ml/optimizer) can never forge the human-approval flag
            raise StoreError(
                f"actor {actor!r} is not a human role; human approval "
                f"for {cur} → {target} must come from owner/ui "
                "(machines never self-approve)")
        if event.kind == "promote":
            required = lc.required_evidence(cur, target)
            adequate = any(
                self.evidence_binds_to(ref, strategy_id, version,
                                       run_types=required)
                for ref in evidence_refs)
            if not adequate:
                raise StoreError(
                    f"{cur} → {target} requires PASS {', '.join(required)}"
                    f" evidence bound to {strategy_id} v{version} — "
                    "cross-version/cross-strategy/failed/wrong-type "
                    "artifacts are not evidence (red-team §28.15; "
                    "gates §15; mission §41)")

        with self.session() as sess:
            strat = sess.scalar(select(Strategy).where(
                Strategy.strategy_id == strategy_id))
            strat.current_state = event.to_state
            if event.to_state not in (lc.RETIRED,):
                strat.current_version = max(strat.current_version,
                                            int(version))
            sess.add(LifecycleEvent(
                strategy_id=strategy_id, version=version,
                from_state=event.from_state, to_state=event.to_state,
                kind=event.kind, evidence_refs=list(evidence_refs),
                actor=actor, reason=reason, gate_version=gate_version))
            if event.kind == "promote":
                sess.add(PromotionDecision(
                    strategy_id=strategy_id, version=version,
                    from_state=event.from_state,
                    to_state=event.to_state, decision="APPROVED",
                    actor=actor, human_approval=human_approval,
                    reason=reason, evidence_refs=list(evidence_refs),
                    evidence_hash=_evidence_digest(sess, evidence_refs),
                    policy_version=policy_version))
            sess.commit()
        return event.to_state

    def original_text(self, strategy_id: str) -> str | None:
        """Latest stored source text (provenance §5/§20: always DATA,
        never instructions)."""
        with self.session() as sess:
            row = sess.scalar(select(StrategySource).where(
                StrategySource.strategy_id == strategy_id)
                .order_by(StrategySource.id.desc()))
            return row.original_text if row else None

    def reconstruct(self, strategy_id: str, version: int | None = None
                    ) -> dict:
        """§73 audit trail: given a strategy (and optional version),
        return the full reconstructable chain — source, claims, spec
        versions, evidence runs, lifecycle events, promotion decisions,
        shadow/live observations.  Read-only; nothing here mutates."""
        with self.session() as sess:
            strat = sess.scalar(select(Strategy).where(
                Strategy.strategy_id == strategy_id))
            if strat is None:
                raise StoreError(f"unknown strategy {strategy_id!r}")
            vq = select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy_id)
            if version is not None:
                vq = vq.where(StrategyVersion.version == version)
            versions = [{
                "version": v.version, "spec_hash": v.spec_hash,
                "dsl_version": v.dsl_version,
                "parent": ({"strategy_id": v.parent_strategy_id,
                            "version": v.parent_version}
                           if v.parent_strategy_id else None),
            } for v in sess.scalars(vq)]
            rq = select(ValidationRun).where(
                ValidationRun.strategy_id == strategy_id)
            if version is not None:
                rq = rq.where(ValidationRun.version == version)
            runs = [{"id": r.id, "version": r.version,
                     "run_type": r.run_type, "status": r.status,
                     "spec_hash": r.spec_hash, "dataset_hash":
                     r.dataset_hash, "gate_version": r.gate_version}
                    for r in sess.scalars(rq)]
            events = [{"kind": e.kind, "from": e.from_state,
                       "to": e.to_state, "actor": e.actor,
                       "reason": e.reason, "version": e.version,
                       "evidence_refs": e.evidence_refs}
                      for e in sess.scalars(
                          select(LifecycleEvent).where(
                              LifecycleEvent.strategy_id
                              == strategy_id))]
            promos = [{"from": p.from_state, "to": p.to_state,
                       "decision": p.decision, "actor": p.actor,
                       "human_approval": p.human_approval,
                       "evidence_hash": p.evidence_hash,
                       "policy_version": p.policy_version}
                      for p in sess.scalars(
                          select(PromotionDecision).where(
                              PromotionDecision.strategy_id
                              == strategy_id))]
            sources = [{"version": src.version,
                        "source_type": src.source_type,
                        "url": src.url, "author": src.author,
                        "platform": src.platform}
                       for src in sess.scalars(
                           select(StrategySource).where(
                               StrategySource.strategy_id
                               == strategy_id))]
            claims = [{"metric": c.metric, "claimed_value":
                       c.claimed_value, "unit": c.unit}
                      for c in sess.scalars(select(StrategyClaim).where(
                          StrategyClaim.strategy_id == strategy_id))]
        return {
            "strategy_id": strategy_id,
            "current_state": strat.current_state,
            "created_by": strat.created_by,
            "sources": sources,
            "claims": claims,
            "versions": versions,
            "evidence_runs": runs,
            "lifecycle_events": events,
            "promotion_decisions": promos,
        }

    def history(self, strategy_id: str) -> list[LifecycleEvent]:
        with self.session() as sess:
            return list(sess.scalars(
                select(LifecycleEvent)
                .where(LifecycleEvent.strategy_id == strategy_id)
                .order_by(LifecycleEvent.id)).all())

    # ------------------------------------------------------------ shadow / live observations

    def record_shadow(self, strategy_id: str, version: int, *,
                      symbol: str, signal: int, as_of: datetime | None = None,
                      executed_would_be: bool = False,
                      hypothetical_pnl: float | None = None,
                      spread_assumed: float | None = None,
                      slippage_assumed: float | None = None,
                      regime: str | None = None,
                      detail: dict | None = None) -> int:
        with self.session() as sess:
            row = ShadowObservation(
                strategy_id=strategy_id, version=version,
                symbol=symbol, signal=int(signal),
                as_of=as_of or utcnow(),
                executed_would_be=executed_would_be,
                hypothetical_pnl=hypothetical_pnl,
                spread_assumed=spread_assumed,
                slippage_assumed=slippage_assumed, regime=regime,
                detail=detail)
            sess.add(row)
            sess.commit()
            return row.id

    def record_live_observation(self, strategy_id: str, version: int, *,
                                mode: str, metric: str,
                                value: float | None = None,
                                detail: dict | None = None) -> int:
        if mode not in {"demo", "live_small", "live"}:
            raise StoreError(f"invalid observation mode {mode!r}")
        with self.session() as sess:
            row = LiveObservation(strategy_id=strategy_id,
                                  version=version, mode=mode,
                                  metric=metric, value=value,
                                  detail=detail)
            sess.add(row)
            sess.commit()
            return row.id

    # ------------------------------------------------------------ alerts

    def alert(self, code: str, *, severity: str = "WARN",
              message: str = "", strategy_id: str | None = None,
              detail: dict | None = None) -> int:
        if severity not in {"INFO", "WARN", "CRITICAL"}:
            raise StoreError(f"invalid severity {severity!r}")
        with self.session() as sess:
            row = Alert(strategy_id=strategy_id, severity=severity,
                        code=code, message=message, detail=detail)
            sess.add(row)
            sess.commit()
            return row.id

    # ------------------------------------------------------------ listing

    def list_strategies(self, state: str | None = None) -> list[dict]:
        with self.session() as sess:
            q = select(Strategy).order_by(Strategy.strategy_id)
            if state:
                q = q.where(Strategy.current_state ==
                            lc.normalize_state(state))
            return [{"strategy_id": s.strategy_id,
                     "state": s.current_state,
                     "version": s.current_version,
                     "family": s.family,
                     "created_at": s.created_at}
                    for s in sess.scalars(q).all()]
