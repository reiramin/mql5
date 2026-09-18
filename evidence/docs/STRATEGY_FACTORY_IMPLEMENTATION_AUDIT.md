# AEGIS STRATEGY FACTORY — IMPLEMENTATION AUDIT

Integration-gate §1 deliverable. Statuses: IMPLEMENTED (executable
evidence exists and runs green), PARTIAL (core exists, named gaps),
NOT_IMPLEMENTED, BLOCKED.

Evidence convention: every row cites the test file(s) that prove it.
Baseline at audit time: commit `deec2cb`, full suite
**1001 tests — 1000 passed / 1 skipped / 0 failed**, `ruff` clean.
The 1 skip is the real-data benchmark fixture (sandbox egress), not a
Factory capability.

## Capability map

| Capability | Status | Evidence | Remaining risk |
| --- | --- | --- | --- |
| Strategy DSL (deterministic, versioned) | IMPLEMENTED | `schemas/strategy.schema.json`; `tests/test_dsl_core.py` (28): validation, rejection-whole, limits (256 KiB doc, depth 32, 512 nodes, 32 indicators, 64 params), `spec_hash`/`semantic_hash`/`dedup_hash`; idempotent canonicalization re-pinned in `tests/test_factory_redteam.py` | Custom indicators remain out of scope by design (no codegen) |
| Parser / normalizer | IMPLEMENTED | `test_dsl_core.py` + red-team idempotency checks; 55 ≡ 55.0 hash stability | — |
| Deterministic runtime (no lookahead) | IMPLEMENTED | `tests/test_dsl_runtime.py` (17): next-bar-open action, shifted indicators; prior mission's leakage suites (`test_cv_state_leakage.py`, `test_leakage_features.py`, `test_metamorphic.py`) | — |
| Reference-strategy parity (DSL vs legacy) | IMPLEMENTED | `tests/test_dsl_parity.py` (13); trade parity 179 trades (ema_crossover, days=200 seed=40) | MT5 Tester parity is owner-only (documented PENDING, never faked) |
| NL interpreter (EN/FA) | IMPLEMENTED | `tests/test_factory_intake.py` (17): EN/FA dedup equality, Persian digits, ambiguity handling (thresholds never invented), determinism | Template patterns only; LLM plugs into `IStrategyInterpreter` with identical draft-only authority |
| Provenance / source intake | IMPLEMENTED | `factory/providers.py` (paste-first; URL providers UNAVAILABLE, never fabricate); `store.original_text()`; red-team tests (`tests/test_factory_redteam.py` 11) | TradingView connector intentionally NOT built (§19) |
| Claims (AUTHOR_CLAIM vs measured) | IMPLEMENTED | `factory/claims.py`; `tests/test_factory_intake.py`; store keeps `strategy_claims` separate from `validation_metrics` (`test_factory_store.py`, test-enforced) | UI display of CLAIMED vs MEASURED pending (§26) |
| Research campaigns / budget / selection-bias | IMPLEMENTED | `factory/research.py`: pre-declared budget (ValueError on excess), `research_selection_bias_warning` + `n_trials_for_dsr` in manifest, manifest hash; `test_factory_intake.py` campaign block | Campaign persistence as first-class row (manifest currently embeds in detail) — PARTIAL |
| Mutation engine (research-only) | IMPLEMENTED | `parameter_mutations` — new child documents, parent immutable, honest no-op on unknown params; tested in `test_factory_intake.py` | Grid search over OOS is structurally prevented at gate level, not here (see OOS isolation row) |
| Persistence (SQLAlchemy, 12 tables) | IMPLEMENTED | `factory/models.py`; `tests/test_factory_store.py` (11): idempotency by spec_hash, version immutability, append-only runs, claims separation, restart equivalence | — |
| Migrations (Alembic-only) | IMPLEMENTED | `migrations/0001_factory_baseline`; `tests/test_factory_migrations.py` (2): round-trip + ORM==migration schema | — |
| Lifecycle machine | IMPLEMENTED | `factory/lifecycle.py`; `tests/test_factory_lifecycle.py` (10): full ladder, failure branches, retire/terminal, actor mandatory, evidence mandatory | — |
| Validation gates 0–12 | IMPLEMENTED | `factory/gates.py` + `factory/gates.yaml` (spec-10.4 defaults, policy_hash); `tests/test_factory_gates.py` (6): missing ⇒ SKIP never pass; thresholds only from policy | Gate-6 DSR/PBO need trial counts fed from campaign manifests (wiring PARTIAL) |
| Shadow mode | IMPLEMENTED | `factory/oversight.py::run_shadow` (cost-adjusted, order-free, refuses ambiguous drafts); `tests/test_factory_oversight.py` (11); `store.record_shadow` rows | Shadow→DEMO evidence criteria wired via gate policy §10.4 (gates 10/11) — IMPLEMENTED at policy level |
| Evidence score (transparent) | IMPLEMENTED | `evidence_score` — 11 named components, explicit weights+version, missing listed; `test_factory_oversight.py` | Weights ladder review cadence is a policy decision, not code |
| Anti-churn hysteresis | IMPLEMENTED | `Hysteresis`/`should_promote`/`should_demote` + `test_factory_oversight.py` oscillation tests | Simulation-scale soak (weeks of synthetic scores) added in governance suite |
| Challenger / incumbent | IMPLEMENTED | `challenger_decision` (NO_DECISION unless same footing + OOS-only); `test_factory_oversight.py` | — |
| Registry (runtime loading) | PARTIAL | DSL runtime + engine seam load specs directly; registry KeyError for `dsl:*` names documents the seam (prior mission) | EA-side dynamic loading is deliberately deferred (§61: only after Python parity stable) |
| Meta integration | IMPLEMENTED | `factory/adapter.py`; `tests/test_factory_adapter.py` (5): UNCERTIFIED block pre-shadow, 0.5/1.0 ladder untouched, Factory-absent strategies pass through | — |
| API (FastAPI) | NOT_IMPLEMENTED | — (CLI covers §56; §55 API planned next) | No trading authority missing with it — boundary unaffected |
| UI (Kanban) | NOT_IMPLEMENTED | — (§26) | — |
| CLI | IMPLEMENTED | `factory/cli.py`; `tests/test_factory_cli.py` (4): interpret→register→advance→status→meta-feed; refusals exit 2; no MT5/sockets (test-enforced) | — |
| Security (intake) | IMPLEMENTED | `factory/security.py`; `tests/test_factory_security.py` (19) + red-team `tests/test_factory_redteam.py` (11): injection-as-data, size/depth limits, traversal refusal, SQL/shell/template inertness | LLM-backed interpreter does not exist yet (template only) — the contract is already enforced |
| Observability (lifecycle events) | PARTIAL | `lifecycle_events` + `promotion_decisions` rows written on every transition (`store.history`); gate verdicts in run details | Named event taxonomy (strategy_parsed, gate_passed…) is implicit in transition kinds — mapping documented in governance suite |
| Restart / crash recovery | IMPLEMENTED | `test_factory_store.py` restart equivalence; migrations round-trip; append-only runs | Concurrent-transition guard added in governance suite (SQLite busy/optimistic checks) |
| Queue / job model | PARTIAL | Transitions are single-transaction (SQLite serialize); duplicate submissions idempotent by spec_hash | Dedicated concurrency test added in governance suite; multi-writer Postgres out of local-first scope |

## The boundary (unchanged, test-pinned)

`COMMUNITY/USER/AI → RESEARCH → DSL → DETERMINISTIC FACTORY →
VALIDATION → LIFECYCLE → REGISTRY → META → RISK → MQL5 → MT5`.
The Factory NEVER places orders, never touches MT5, never widens
allocation: pre-shadow lifecycle states produce NO Meta certification
(`test_factory_adapter.py`), shadow rows are observations only
(`test_factory_oversight.py`), and no CLI subcommand can reach a
broker (`test_factory_cli.py`).

## Honest gaps summary

1. FastAPI API + Kanban UI (§55/§26) — NOT_IMPLEMENTED, no safety impact.
2. Campaign rows as first-class table + gate-6 trial-count wiring — PARTIAL.
3. Registry EA loading — deferred by mission order (§61).
4. MT5 execution parity — owner-only cells remain PENDING (never faked).

## System boundary (integration gate §36 — binding statement)

The **Factory is a RESEARCH and LIFECYCLE system. It is NOT an
autonomous trader.** Its function is exactly:

```text
idea generation
+ strategy interpretation (drafts only, ambiguities surfaced)
+ validation (deterministic gates from policy files)
+ selection (budgeted, multiple-testing-accounted)
+ monitoring (shadow rows, lifecycle events)
```

Execution authority remains, unbypassed and in order:

```text
Meta (relative allocation) → Risk (real-risk veto) → MQL5 → MT5
```

No Factory component places orders, talks to a broker, imports MT5,
or widens allocation. A strategy NEVER gains direct trading authority:
pre-shadow lifecycle states translate to NO Meta certification, and
DEMO/LIVE transitions demand audited human approval. No wording in
this repository implies an LLM can trade; LLM/interpreter output is a
DRAFT consumed by the deterministic Factory, nothing more.

Final-gate evidence (integration gate §35): commit `82605a7`,
full suite **1023 tests — 1022 passed / 1 skipped / 0 failed**
(the skip = real-data benchmark, sandbox egress), `ruff check` clean.
Area counts: DSL 67, factory lifecycle/store/gates/migrations 29,
intake 17, security 19, red team 11, oversight 11, adapter 5, CLI 4,
E2E fixture 8, research proofs 4, governance 10 (prior-suite 838 + DSL 67 + factory 118 = 1023).
