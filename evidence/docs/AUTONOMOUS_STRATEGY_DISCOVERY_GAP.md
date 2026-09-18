# AEGIS — AUTONOMOUS STRATEGY DISCOVERY: GAP MATRIX

Mission §2 deliverable. Maps the target autonomous-discovery platform
(§0–§104) against what already exists at baseline commit `81d6d1d`
(integration gate passed: 1023 tests green).

Columns: capability · current implementation · tests/evidence ·
target behavior · missing work · safety impact · dependency · phase.

Phases: P1 = domain/boundaries, P2 = indicator universe,
P3 = discovery/campaigns, P4 = score/selection, P5 = lifecycle/ops,
P6 = portfolio/allocation governance, P7 = safety, P8 = API/UI,
P9 = research hardening, P10 = MQL5 boundary, P11 = acceptance.

| Capability | Current implementation | Tests/evidence | Target behavior | Missing work | Safety impact | Dependency | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Strategy DSL (deterministic, versioned) | `python/mql5bot/dsl/` full schema/parser/normalizer/runtime; strict rejection; limits (256 KiB/depth 32/512 nodes/32 ind/64 params) | `test_dsl_core/runtime/parity/security.py` (67) | Same, plus registry-driven indicator kinds | Registry-driven param validation; new kinds | HIGH (semantic authority) | — | P2 |
| Indicator set | 9 kinds (EMA/SMA/RSI/ATR/BBANDS/MACD/DONCHIAN/HIGHEST/LOWEST) in `indicators.py` | parity tests; trade parity 179 | Broad extensible universe (§8) with contracts (§9), multi-output first-class | Catalog module + ~40 kinds + compute + docs; MQL5 port pending owner compile | HIGH (no silent approximation) | DSL schema/runtime | P2 |
| Multi-output indicators | BBANDS mid/upper/lower, MACD line/signal, DONCHIAN upper/lower via `id__out` | `test_dsl_core.py` | First-class declared outputs incl. bandwidth/%b/histogram/ADX etc. | Declared outputs in catalog; extra outputs emitted | MED | catalog | P2 |
| Pivot/structural semantics | not implemented | — | Pivot vs confirmation vs signal timestamps; `signal_time >= confirmation_time` (§77) | SWING/PIVOT kinds with right-bar confirmation + tests | HIGH (lookahead risk) | catalog | P2 |
| MTF (closed-bar) | not in DSL | — | Higher-TF trend/vol/osc from CLOSED bars only | MTF parameter + resample in runtime | HIGH (lookahead) | catalog | P2 |
| NL/FA intake | TemplateInterpreter (EN/FA, ambiguity, digits); `IStrategyInterpreter` contract | `test_factory_intake.py` (17) | Same + LLM provider plug-in | LLM provider adapter (interface exists) | MED | security layer | P3 |
| Providers | paste-first; URL providers UNAVAILABLE | `test_factory_security.py` (19) | `IResearchSourceProvider` abstraction (§11/§12) | Rename/formalize protocol | LOW | — | P3 |
| Claims vs measured | AUTHOR_CLAIM stored separately from ValidationMetric | `test_factory_store.py` | Same, shown side-by-side in UI | UI display | MED | API/UI | P8 |
| Candidate generation | `research.py::parameter_mutations` (single-axis, budgeted, lineage) | `test_factory_intake.py`, `test_factory_research_proof.py` | Staged search (§63), redundancy filter (§64), structural variants (§17) | Staged generator + redundancy detector + structural combos | MED (budget safety) | catalog | P3 |
| Campaigns | `research.Campaign` (manifest, budget, selection warning, hash) | research-proof tests | Persistent resumable orchestrator (§7/§18) | Stage-state persistence + resume + idempotency | MED | store | P3 |
| Backtest pipeline | deterministic engine; costs/slippage/commission; next-open; stops | parity + e2e suites | Same (no shortcut) | — | — | — | — |
| Robustness | gates 3–7 (cost stress, sensitivity, WFA, PBO/DSR, MC) from policy | `test_factory_gates.py` | + data perturbation, regime split, outlier sensitivity (§23) | Additional robustness probes | MED | gates | P4/P9 |
| Realism score | cost-adjusted shadow; turnover/holding metrics exist | oversight tests | Explicit realism evidence component (§24) | Realism component in score + slippage-sensitivity probe | MED | score | P4 |
| Discovery score | `evidence_score` (11 components, explicit weights) | `test_factory_oversight.py` | 16-component transparent score incl. drift/realism/portfolio; persisted policy hash; SCORE ≠ PERMISSION (§27/§28) | discovery_score domain module + policy file | HIGH (must stay explainable) | decay/portfolio | P4 |
| Evidence level | lifecycle states only | lifecycle tests | E0–E7 explicit levels separate from score (§30) | EvidenceLevel value object + mapping | MED | domain | P1 |
| Lifecycle | full ladder + failures + recovery; store-enforced type-adequate evidence; human approval DEMO+ | `test_factory_lifecycle/store.py`, red team (11) | Same + approval records w/ evidence hash (§32); no auto-inheritance of parent status (§0.12 — already enforced) | ApprovalRecord enrichment | HIGH | store | P5 |
| Live-small ramp | Activation.LIVE_SMALL exists (Meta ladder) | meta tests | Config-driven ramp 0.25→1.0 with evidence-gated steps (§33/§34) | ramp policy + controller | HIGH | decay | P5 |
| Decay controller | drift_feed (performance/regime drift snapshots) | prior-mission suites | Multi-signal decay bands → allocation multiplier (§35), recovery via requalification (§36) | decay domain + bands policy | HIGH | drift_feed | P5 |
| Anti-churn | Hysteresis + challenger/incumbent | oversight tests | Same (§37 satisfied) | — | — | — | — |
| Concentration | correlation conventions + meta portfolio heat (prior mission) | meta_portfolio suites | Explicit measures: strategy/symbol/direction/currency/asset-class/correlation/factor (§38) | concentration module | HIGH | portfolio | P6 |
| Portfolio-aware ranking | none (standalone gates only) | — | standalone vs incremental score, correlation penalty, marginal heat (§39/§52/§65) | ranking module | MED | concentration | P4/P6 |
| Capital utilization | n/a (Meta never forces exposure) | meta tests | 0% allowed; target 10–20% never mandatory (§40) | policy + governor tests | HIGH | governor | P6 |
| Allocation governance | Meta weight ladder (clamped, ±15%/day) | meta suites | Separation: score/eligibility/recommendation/approved/effective (§66/§78); delta bounds (§79) | AllocationGovernor + bounds policy | HIGH | meta | P6 |
| Allocation circuit breaker | none | — | Independent anomaly guard: freeze + keep last safe + alert (§41/§79/§80) | circuit breaker module | CRITICAL | kill switch | P7 |
| Kill switch | failsafe ENGINE states (daily-loss pause) + EA-side switches | prior-mission suites | Independent SafetyState layer NORMAL/NO_NEW_TRADES/EMERGENCY_HALT; overrides everything; persisted; explicit reset (§42/§43) | kill switch module + authority tests | CRITICAL | — | P7 |
| External watchdog | none | — | Minimal out-of-process monitor + alert channel, rate-limited, fail-safe (§44/§45/§81) | watchdog module + runner | HIGH (ops survivability) | kill switch | P7 |
| Decision order | documented + adapter | adapter tests | Explicit chain incl. circuit breaker + kill switch (§48) | docs + composition test | HIGH | P7 | P7 |
| Regime awareness | regime_feed + Meta regimes_allowed/preferred/forbidden | meta tests | Strategy-declared regime profile + compatibility (§25) | regime profile in spec metadata + compat function | MED | regime_feed | P9 |
| Drift | drift_feed (perf/regime/feature) | prior suites | Drift as score component + decay input (§26) | wiring | MED | decay | P5 |
| Dataset identity | DatasetStore RAW/CLEAN/DERIVED + digests | `test_data_store.py` | dataset_id/hash/quality metadata on every run (§60) | DatasetIdentity value object + run binding | MED | data_layer | P9 |
| Data quality firewall | NaN fixes + validation pins exist | cv_state/leakage suites | Quarantine invalid bars (§61) | explicit validation gate module + tests | HIGH | data_layer | P9 |
| Resource budget | DSL limits (32 ind/64 params/512 nodes) | dsl security tests | + campaign-level budgets (§62/§63) | staged budgets in generator | MED | orchestrator | P3 |
| Cache safety | run-level hashes (spec/dataset/config/code) | store tests | + gate-policy hash keying (§70) | policy_hash in keys (already bound) | LOW | — | P9 |
| Observability | lifecycle_events + promotion_decisions rows | governance tests | Event taxonomy §71 incl. allocation/safety events | event names + emission points | MED | store | P7 |
| API | CLI only | `test_factory_cli.py` | FastAPI research/lifecycle API (§57), no trading | API module + tests | MED | store | P8 |
| UI | none | — | Kanban + strategy/safety/approval pages, Jinja2 (§58/§59), no React | templates + views | LOW | API | P8 |
| ML boundary | no ML (by rule) | — | LLM/ML/rules boundary documented (§46/§47); extension points only (§95) | `ML_VS_LLM_BOUNDARY.md` | MED | docs | P9/P10 |
| EA-side dynamic loading | codegen escape hatch; allocation digest verification | `test_mql5_sources.py` | Spec-loader eligibility gates in EA (§75/§76) | loader manifest (Py) + MQL5 include (owner compile) | CRITICAL | P10 |
| MT5 compile/test/live | NOT executed (honest) | — | owner-only | — | — | — | P10 |

Honesty note: rows marked "pending owner compile" cannot be validated
in this environment (no MetaTrader). They are never reported as PASS.
