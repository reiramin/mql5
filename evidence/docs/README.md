# Documentation Map

Two levels: **human onboarding/operations** (these guides) and
**canonical engineering documents** (authoritative contracts — the
guides link to them instead of duplicating them).

## Start Here

| Document | Purpose |
|---|---|
| [INSTALLATION.md](INSTALLATION.md) | Python environment, optional extras, what works on Linux/macOS vs Windows+MT5 |
| [USER_GUIDE.md](USER_GUIDE.md) | How the system works bar-by-bar: strategies, Risk, Kill Switch, Meta, positions, restarts |
| [MT5_SETUP_AND_OPERATION.md](MT5_SETUP_AND_OPERATION.md) | Complete owner-side runbook: compile, install, presets, Strategy Tester, safety, evidence |
| [FACTORY_GUIDE.md](FACTORY_GUIDE.md) | The AEGIS Factory workflow from idea to retirement |
| [CERTIFICATION_GUIDE.md](CERTIFICATION_GUIDE.md) | The validation ladder: Gold / MT5 runtime / empirical / demo / live |

## Architecture / Contracts

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layered model for humans; authority boundaries |
| [SPEC.md](SPEC.md) | Canonical technical specification (authoritative) |
| [SYSTEM_INVARIANTS.md](SYSTEM_INVARIANTS.md) | Safety/correctness invariants that never weaken |
| [STATE_MODEL.md](STATE_MODEL.md) | Strategy lifecycle state machine |
| [DECISIONS.md](DECISIONS.md) | Binding decisions log (change it deliberately) |

## Risk / Execution

| Document | Purpose |
|---|---|
| [KILL_SWITCH.md](KILL_SWITCH.md) | Emergency veto contract |
| [SAFETY_GOVERNANCE.md](SAFETY_GOVERNANCE.md) | Safety governance model |
| [MQL5_EXECUTION_AUDIT.md](MQL5_EXECUTION_AUDIT.md) | MQL5 execution-path audit |
| [BROKER_SYMBOL_PARITY.md](BROKER_SYMBOL_PARITY.md) | Broker SymbolSpec handling + parity contract |
| [EXECUTION_STRESS_OBSERVED.md](EXECUTION_STRESS_OBSERVED.md) | Observed execution stress behavior |

## Research / Meta

| Document | Purpose |
|---|---|
| [META_LAYER_CONTRACT.md](META_LAYER_CONTRACT.md) | Meta layer contract (reduce-only allocation) |
| [META_LAYER_IMPLEMENTATION_SPEC.md](META_LAYER_IMPLEMENTATION_SPEC.md) | Meta implementation spec |
| [AUTONOMOUS_STRATEGY_DISCOVERY.md](AUTONOMOUS_STRATEGY_DISCOVERY.md) | Discovery system overview |
| [DISCOVERY_SCORE.md](DISCOVERY_SCORE.md) | 16-component Discovery Score |
| [INDICATOR_UNIVERSE.md](INDICATOR_UNIVERSE.md) | 71-kind research indicator universe |
| [WFA_CONTRACT.md](WFA_CONTRACT.md) / [WFA_CPCV_REVIEW.md](WFA_CPCV_REVIEW.md) | Walk-forward / CPCV validation contracts |
| [STAGED_PIPELINE.md](STAGED_PIPELINE.md) | Staged research pipeline |
| [STRATEGY_DECAY.md](STRATEGY_DECAY.md) | Decay/recovery policy |
| [ML_VS_LLM_BOUNDARY.md](ML_VS_LLM_BOUNDARY.md) | ML vs LLM responsibility boundary |

## Certification / Evidence

| Document | Purpose |
|---|---|
| [CERTIFICATION.md](CERTIFICATION.md) | Binding scope model + two certification lanes + evidence layers |
| [MT5_ROUNDTRIP.md](MT5_ROUNDTRIP.md) | Canonical TEN-step owner protocol (single source of truth) |
| [CERTIFICATION_GUIDE.md](CERTIFICATION_GUIDE.md) | Human-facing validation-ladder guide |
| [AEGIS_REALITY_GATE_AUDIT.md](AEGIS_REALITY_GATE_AUDIT.md) | Reality-gate audit record (§85–§90 incl. attack matrices) |
| [AEGIS_REALITY_GATE_CONTINUATION.md](AEGIS_REALITY_GATE_CONTINUATION.md) | Gate continuation log (§17a–§17g) |
| [AEGIS_EXIT_GATE.md](AEGIS_EXIT_GATE.md) | Exit-gate record |
| [AEGIS_EMPIRICAL_LANE_PACKAGE.md](AEGIS_EMPIRICAL_LANE_PACKAGE.md) | Empirical lane owner package definition (prepared, not executed) |
| `../artifacts/owner_mt5_gate/README.md` | Owner execution package manual + evidence directory contract |

## Operations

| Document | Purpose |
|---|---|
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Failure classes: symptom, cause, inspection, safe resolution |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | Final pre-release sequence + owner-side gate |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Contributor guide: layout, standards, canonical files |

## Historical / audit records

The `PHASE3_*`, `MASTER_PRODUCTION_CONVERGENCE_AUDIT.md`,
`AEGIS_FINAL_CONVERGENCE_AUDIT.md`, `IMPLEMENTATION_AUDIT.md`,
`STRATEGY_FACTORY_*`, `META_*` validation/audit files are engineering
evidence of past gates. They remain for attribution but are not
required reading for operating the project. Where an old document
describes a state superseded by a later gate, the later document is
authoritative (see `DECISIONS.md`).

## Root-level continuity files

| File | Role |
|---|---|
| `README.md` | Public front door |
| `CHANGELOG.md` | Version history |
| `HANDOFF.md` | Agent/engineering continuity |
| `PROGRESS.md` | Execution history/status |
| `TASKS.md` | Active work queue |

**Rule:** documentation must never become more optimistic than the
implementation and the evidence.
