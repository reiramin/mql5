# Docs index

Every file under `docs/`, one line each. **Status:** *current* means it
describes the code and the gate as they are now (gate_run59 certified;
master after `50cdb71`); *historical* means a dated, point-in-time record
that is kept, not edited with later knowledge, and names the file that
supersedes it. The root-level files are listed at the end.


## Start here

| File | What it is | Status |
|---|---|---|
| [SHOWCASE.md](SHOWCASE.md) | What AEGIS is, how it was built and verified, bugs found, numbers, limits; links the certificate | current |
| [OWNER_GATE.md](OWNER_GATE.md) | The certification gate: stages 0–10, runner tags, runner rules, exit codes, evidence layout | current |
| [BLOCKED.md](BLOCKED.md) | What is open or not yet run live | current |
| [INSTALLATION.md](INSTALLATION.md) | Python environment, optional extras, what runs on Linux/macOS vs Windows+MT5 | current |
| [USER_GUIDE.md](USER_GUIDE.md) | How the system works bar by bar: strategies, Risk, Kill Switch, Meta, positions, restarts | current |
| [MT5_SETUP_AND_OPERATION.md](MT5_SETUP_AND_OPERATION.md) | Owner-side runbook: compile, install, presets, Strategy Tester, safety, evidence | current |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Failure classes and known gate failure modes, each with its decision ID and remedy | current |

## Certification and evidence

| File | What it is | Status |
|---|---|---|
| [CERTIFICATION.md](CERTIFICATION.md) | The certification contract: scope surfaces, lanes, evidence layers, what a certificate claims | current |
| [CERTIFICATION_GUIDE.md](CERTIFICATION_GUIDE.md) | How-to for the validation ladder: Gold / MT5 runtime / empirical / demo / live | current |
| [SECURITY.md](SECURITY.md) | Strategy secrets (git-crypt), encrypted outputs (age), secret scan, account hardening checklist | current |
| [DECISIONS.md](DECISIONS.md) | Binding decisions log (entries to 2026-10-03 newest on top; from 2026-10-04 appended at the end) | current |
| [SAFETY_8A_8D_PLAN.md](SAFETY_8A_8D_PLAN.md) | The five Strategy Tester safety legs (kill_switch, risk_veto, lost_response, meta_reduce, sl_verify) | current |
| [SAFETY_DEMO_PLAN.md](SAFETY_DEMO_PLAN.md) | The three live-demo safety tests (restart, netting, hedging) and the demo harness in stage 7 | current |
| [BROKER_SYMBOL_PARITY.md](BROKER_SYMBOL_PARITY.md) | Broker SymbolSpec handling and the stage-3 parity contract | current |
| [AEGIS_EMPIRICAL_LANE_PACKAGE.md](AEGIS_EMPIRICAL_LANE_PACKAGE.md) | Definition of the empirical lane (prepared, never executed) | current |
| [analysis/gate_run25_divergences.md](analysis/gate_run25_divergences.md) | gate_run25 gold2 divergence analysis | historical (2026-10-03); superseded by DECISIONS.md and the gate_run59 certificate |
| [analysis/gate_run28_divergences.md](analysis/gate_run28_divergences.md) | gate_run28 divergence analysis | historical (2026-10-03); superseded by DECISIONS.md and the gate_run59 certificate |
| [analysis/gate_run29_missing_0808.md](analysis/gate_run29_missing_0808.md) | gate_run29 single MISSING_IN_MT5 analysis | historical (2026-10-04); superseded by DECISIONS.md and the gate_run59 certificate |
| [OWNER_DELIVERY.md](OWNER_DELIVERY.md) | Account of the first full gate run (2026-09-20, stopped at stage 5) | historical (2026-09-20 run); superseded by OWNER_GATE.md and README "Certification status" |
| [MT5_ROUNDTRIP.md](MT5_ROUNDTRIP.md) | The manual ten-step owner protocol used before the automated gate | historical (2026-09-20); superseded by OWNER_GATE.md |
| [WINDOWS_OWNER_HANDOFF.md](WINDOWS_OWNER_HANDOFF.md) | Windows owner handoff for the pre-gate compile and re-anchor | historical (2026-09-20); superseded by OWNER_GATE.md and MT5_SETUP_AND_OPERATION.md |

## Architecture and contracts

| File | What it is | Status |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layered model and authority boundaries | current |
| [SPEC.md](SPEC.md) | SPEC v4: the original design specification (aspirational; the tree differs in places, see its note) | current |
| [SYSTEM_INVARIANTS.md](SYSTEM_INVARIANTS.md) | Safety and correctness invariants that never weaken | current |
| [STATE_MODEL.md](STATE_MODEL.md) | Strategy lifecycle state machine | current |
| [KILL_SWITCH.md](KILL_SWITCH.md) | Emergency veto contract (Python and EA) | current |
| [SAFETY_GOVERNANCE.md](SAFETY_GOVERNANCE.md) | Safety governance of the discovery layer | current |
| [ALLOCATION_CIRCUIT_BREAKER.md](ALLOCATION_CIRCUIT_BREAKER.md) | Allocation circuit breaker in the discovery safety layer | current |
| [EXTERNAL_WATCHDOG.md](EXTERNAL_WATCHDOG.md) | External watchdog component | current |
| [EXECUTION_STRESS_OBSERVED.md](EXECUTION_STRESS_OBSERVED.md) | Measured execution-stress degradation (Phase 10) | current |

## Operator experience (built, unit-tested, never run live)

| File | What it is | Status |
|---|---|---|
| [ROADMAP_UX.md](ROADMAP_UX.md) | The operator-experience plan: Telegram-first, Persian status page, split deployment, guided conversation | current |
| [TELEGRAM.md](TELEGRAM.md) | Telegram alerts, daily digest and the four commands | current |
| [CONSOLE.md](CONSOLE.md) | The operator console (CONSOLE v2): pages, auth, live updates, the certification rail | current |
| [PERSIAN_CONSOLE.md](PERSIAN_CONSOLE.md) | The opt-in Persian/RTL presentation layer | current |
| [DEPLOYMENT.md](DEPLOYMENT.md) | The split always-on deployment (a procedure, never deployed or drilled) | current |

## Research and meta layer

| File | What it is | Status |
|---|---|---|
| [META_LAYER_CONTRACT.md](META_LAYER_CONTRACT.md) | Meta layer contract v1.1.1 (reduce-only allocation) | current |
| [META_LAYER_IMPLEMENTATION_SPEC.md](META_LAYER_IMPLEMENTATION_SPEC.md) | Contract-to-code spec for meta_layer.py | current |
| [META_LAYER_VALIDATION.md](META_LAYER_VALIDATION.md) | Measured meta validation / red team | current |
| [META_PRODUCTION_VALIDATION.md](META_PRODUCTION_VALIDATION.md) | MetaPortfolioEngine validation record | current |
| [META_OOS_CANONICAL.md](META_OOS_CANONICAL.md) | Canonical meta out-of-sample protocol | current |
| [META_PORTFOLIO_EVENT_ORDER.md](META_PORTFOLIO_EVENT_ORDER.md) | Canonical meta portfolio event order | current |
| [META_REPLAY_CONVENTIONS.md](META_REPLAY_CONVENTIONS.md) | Replay identity conventions | current |
| [META_PERF_BENCHMARK.json](META_PERF_BENCHMARK.json) | Meta performance benchmark output (measurement) | current |
| [CORRELATION_CONVENTIONS.md](CORRELATION_CONVENTIONS.md) | Meta-layer correlation conventions | current |
| [REGIME_MATRIX.md](REGIME_MATRIX.md) | Frozen regime matrix measurement (with REGIME_MATRIX.json) | current |
| [REGIME_MATRIX.json](REGIME_MATRIX.json) | Regime matrix data | current |
| [VERSION_CONSISTENCY.md](VERSION_CONSISTENCY.md) | Version carriers (meta contract 1.1.1) | current |
| [AUTONOMOUS_STRATEGY_DISCOVERY.md](AUTONOMOUS_STRATEGY_DISCOVERY.md) | Discovery platform overview and status | current |
| [DISCOVERY_SCORE.md](DISCOVERY_SCORE.md) | 16-component Discovery Score | current |
| [INDICATOR_UNIVERSE.md](INDICATOR_UNIVERSE.md) | 71-kind research indicator universe | current |
| [WFA_CONTRACT.md](WFA_CONTRACT.md) | Walk-forward contract | current |
| [WFA_CPCV_REVIEW.md](WFA_CPCV_REVIEW.md) | WFA / CPCV cross-audit | current |
| [CV_STATE_CONTRACT.md](CV_STATE_CONTRACT.md) | CV/WFA state-crossing contract | current |
| [STAGED_PIPELINE.md](STAGED_PIPELINE.md) | Staged research pipeline and manifests | current |
| [STRATEGY_DECAY.md](STRATEGY_DECAY.md) | Decay / recovery controller | current |
| [ML_VS_LLM_BOUNDARY.md](ML_VS_LLM_BOUNDARY.md) | ML vs LLM authority boundary | current |
| [BENCHMARK_FAST.md](BENCHMARK_FAST.md) | FAST engine scope and measured benchmark | current |
| [FACTORY_GUIDE.md](FACTORY_GUIDE.md) | The Strategy Factory workflow from idea to retirement | current |

## Development and operations

| File | What it is | Status |
|---|---|---|
| [DEVELOPMENT.md](DEVELOPMENT.md) | Contributor guide: layout, quality gates, canonical files | current |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | Pre-release sequence and the owner-side gate | current |
| [AUTONOMOUS_WORKER.md](AUTONOMOUS_WORKER.md) | The daily autonomous-worker task prompt | current |
| [README.md](README.md) | This index | current |

## Historical audit and phase records (point-in-time; not edited with later knowledge)

| File | What it is | Status |
|---|---|---|
| [AEGIS_CONVERGENCE_AUDIT_2026-09.md](AEGIS_CONVERGENCE_AUDIT_2026-09.md) | Mac code-lane convergence audit / gap table | historical (2026-09); superseded by CERTIFICATION.md and ARCHITECTURE.md |
| [AEGIS_FINAL_CONVERGENCE_AUDIT.md](AEGIS_FINAL_CONVERGENCE_AUDIT.md) | Pre-coding convergence audit (§1–86) | historical (2026-09-20); superseded by ARCHITECTURE.md |
| [AEGIS_REALITY_GATE_AUDIT.md](AEGIS_REALITY_GATE_AUDIT.md) | Python→DSL→MQL5→MT5 reality-gate audit (§85–§90) | historical (2026-09-20); superseded by OWNER_GATE.md and CERTIFICATION.md |
| [AEGIS_REALITY_GATE_CONTINUATION.md](AEGIS_REALITY_GATE_CONTINUATION.md) | Reality-gate continuation log (§17a–§17g) | historical (2026-09-07); superseded by OWNER_GATE.md |
| [AEGIS_EXIT_GATE.md](AEGIS_EXIT_GATE.md) | Phase-32 exit report: meta realism, multi-asset, regime, drift | historical (2026-09-20); superseded by META_PRODUCTION_VALIDATION.md |
| [PHASE3_FINAL_REPORT.md](PHASE3_FINAL_REPORT.md) | Phase 3 acceptance report | historical (2026-09-04); superseded by SHOWCASE.md |
| [PHASE3_GATE.md](PHASE3_GATE.md) | Phase 3 integrity gate record | historical (2026-09-05); superseded by OWNER_GATE.md |
| [MASTER_PRODUCTION_CONVERGENCE_AUDIT.md](MASTER_PRODUCTION_CONVERGENCE_AUDIT.md) | Existence-vs-integration audit | historical (2026-09-20); superseded by ARCHITECTURE.md |
| [IMPLEMENTATION_AUDIT.md](IMPLEMENTATION_AUDIT.md) | SPEC v4 implementation audit | historical (2026-09-20); superseded by ARCHITECTURE.md and BLOCKED.md |
| [MQL5_EXECUTION_AUDIT.md](MQL5_EXECUTION_AUDIT.md) | Source-level audit of the EA's trade paths | historical (2026-09-20); superseded by ARCHITECTURE.md and CERTIFICATION.md |
| [META_LAYER_SEMANTICS_REVIEW.md](META_LAYER_SEMANTICS_REVIEW.md) | Review of meta contract v1.1.1 against the code | historical (2026-09-20); superseded by META_LAYER_CONTRACT.md |
| [META_REALISM_AUDIT.md](META_REALISM_AUDIT.md) | Trace of meta_portfolio at 61d55ab | historical (2026-09-20); superseded by META_PRODUCTION_VALIDATION.md |
| [AUTONOMOUS_STRATEGY_DISCOVERY_GAP.md](AUTONOMOUS_STRATEGY_DISCOVERY_GAP.md) | Discovery gap matrix at baseline 81d6d1d | historical (2026-09-20); superseded by AUTONOMOUS_STRATEGY_DISCOVERY.md |
| [STRATEGY_FACTORY_GAP_ANALYSIS.md](STRATEGY_FACTORY_GAP_ANALYSIS.md) | Factory gap analysis at baseline ba672ff | historical (2026-09-06); superseded by FACTORY_GUIDE.md |
| [STRATEGY_FACTORY_IMPLEMENTATION_AUDIT.md](STRATEGY_FACTORY_IMPLEMENTATION_AUDIT.md) | Factory integration-gate audit | historical (2026-09-20); superseded by FACTORY_GUIDE.md |

## Root-level files

| File | Role |
|---|---|
| `README.md` | Front door: certification status, repository map, quick start |
| `CLAUDE.md` | Rules for any agent working in this repository, and the owner-scoped exceptions with their status |
| `CHANGELOG.md` | Changes per decision ID with PR numbers |
| `HANDOFF.md` | Agent/engineering continuity; its CURRENT STATE POINTER is authoritative |
| `PROGRESS.md` | Execution history; its CURRENT STATE block is authoritative |
| `TASKS.md` | Open items only (older backlogs kept below as history) |
| `AUTONOMOUS_LOG.md` | Dated per-session log of agent work (branch, commits, exit codes, what was not done) |

**Rule:** documentation must never become more optimistic than the
implementation and the evidence. Gate status is reported exactly as the
latest run on branch `gate-reports` shows it.
