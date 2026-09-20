# Changelog

All notable changes to mql5bot are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased — Feature Wave 3 + first full owner gate run (2026-09-20)

The MQL5 sources under `mql5/` are unchanged (frozen anchor `a85cba3`); the
2026-09-20 compile-of-record for HEAD `81520e6` stays valid. Everything below
is Python / tools / docs / tests. No profit claim is made anywhere.

- **First full owner certification gate run (2026-09-20, MT5 build 6184,
  Windows 10).** Stages 0–4 PASS, stage 5 FAIL (`GATE_RESULT=tester_legs`),
  stages 6–10 never ran. Nothing is VERIFIED. Recorded verbatim, with the
  per-stage hashes and per-leg verdicts, in `docs/OWNER_DELIVERY.md`; a
  BLOCKED leg is not presented as a pass.
- **STAGE 4 fixture-import hardening, R7–R10** (custom-symbol import into MT5):
  - R7 (`63f2faa`): custom-symbol currency inference fixed by naming the
    symbol `XXXYYY`+suffix so `verify_properties` reads the intended
    base/profit currencies.
  - R8 (`b439f97`): a bars-only Forex custom symbol reads its CALCULATED
    tick values (`SYMBOL_TRADE_TICK_VALUE_PROFIT/_LOSS`) back as 0; recorded
    as a NAMED, scoped limitation (available/authoritative:false) — stage 4
    PASSES, economics certified by stage 3, never a silent pass.
  - R9 (`96125a0`): survive a symbol left SELECTED by a prior successful run
    (adopt in place, never a blind refusal).
  - R10 (`2c94996`): verify-first adoption — a re-run needs nothing from
    Market Watch; the async ChartClose is polled, never assumed.
- **STAGE 5 tester-legs hardening, R1–R6** (the Strategy Tester stage that
  FAILED on the 2026-09-20 run):
  - R1 (`10ec10a`): quote every path handed to an external process; each leg
    attaches evidence and records the ACTUAL model/coverage.
  - R2 (`cc70fd7`): make a failed tester leg diagnosable; stop guessing the
    report path.
  - R3 (`c7aec19`): the tester ran nothing — the EA path was doubled; fixed.
  - R4 (`aac9fb9`): the gate was grading a DIFFERENT `mql5bot` than the repo
    shipped; stage 0 now requires the package to resolve IN-REPO.
  - R5 (`c9fef7d`): config-file Model enum, populated `[TesterInputs]`, and
    an honest BLOCKED_OWNER_ENVIRONMENT when the report file is absent.
  - R6 (`81520e6`): scope the BLOCKED classifier to ONE leg — a day-wide log
    dump was laundering a neighbour's evidence into a leg that proved nothing.
- **Interpreter restatement fix** (`5a946b3`): the operator-facing restatement
  is derived FROM the scrubbed draft (defects A + B) — never from the
  provider's own words, and a number appears only if it is in the draft.
- **LlmInterpreter** (`73df61a`): provider-agnostic natural-language intake
  with the deterministic template's discipline — grounds every number in the
  source text, refuses invented structural numbers, falls back to the template
  with a visible note on any error, keeps market §6 no-guess. Python only.
  **Built and unit-tested; never run against a live provider in production.**
- **Telegram alert channel** (`d22a783`): env-only credentials, token
  scrubbed by value, bounded timeout, min-send interval that SKIPS rather
  than sleeps; wired to the Watchdog; transport and clock injectable for
  tests. Extended in this wave with trade open/close notifications, a daily
  digest, and read-only status/positions/report/stop commands under
  asymmetric friction (stop is immediate; no Telegram path can resume a
  stopped system). **Built and unit-tested; never run against a live bot.**
- **Persian / RTL console presentation layer** (`4752140`): opt-in
  (`MQL5BOT_LANG=fa` or `--lang fa`); English output stays byte-identical.
  Certification terms are shown verbatim and explained alongside, never
  translated away; Latin identifiers/hashes are bidi-isolated, never
  reordered or digit-substituted. **Built and unit-tested; never run live.**
- **Owner delivery note refreshed** (`b3f9d3c`) from the 2026-09-20 gate run.
- Roadmap `docs/ROADMAP_UX.md`, split-deployment guide `docs/DEPLOYMENT.md`,
  and a guided Persian strategy-conversation flow added this wave (docs +
  Python/tests). The conversation flow ENDS at SCHEMA VALIDATION: the only
  Python check it runs is the DSL schema/parse gate (the draft is well-formed);
  it is NOT a test of the strategy — no backtest, robustness, out-of-sample or
  market data. It cannot promote a strategy toward MT5 or a live account, and
  it surfaces the two not-yet-done steps explicitly: the Python research
  validation (needs a dataset) and the owner-run 11-stage MT5 gate.

## Unreleased — Wave 2.2 (final pre-certification: owner-gate verifier hardening)

- Certification integrity (P0/P1): the owner-evidence verifier now COMPUTES
  reconciliation divergence from the recorded python/mt5 values instead of
  trusting the owner's `status` label (`owner_gate.first_divergence`); the
  reconciliation must bind `expected_execution_sha256` (anchoring the python
  column to the frozen truth engine) and `tester_models` covering every model
  — both are now required bindings; and `certify_strategy._reconciliation_ok`
  rejects a PENDING_OWNER reconciliation (non-null MT5 evidence required) so
  a work-in-progress artifact can no longer satisfy step 8. +8 regression
  tests. No contract weakened — every change makes the gate stricter.
- Doc-truth: corrected an overclaimed "0/0 owner EA compile" in PROGRESS.md
  (the EA compiled 0 errors / 2 warnings, closed source-only, never
  recompiled — strict 0/0 EA compile-of-record is owner-pending; the 0/0 was
  the exporter script); README "no owner artifacts exist yet" → "not committed
  to this repo"; HANDOFF weekly-check compile line softened to a target.
- Provenance (P2, documented): Gold #2 reproducibility pin is
  `frozen_inputs.json gold_2.git_commit_recorded = 6b172dac92a6` (regeneration
  must pass `--git-commit`); `gold_1.config_hash` empty anchor noted.
- Tests: 1593 passed / 1 skipped / 0 failed; `ruff check python/ tests/`
  clean; `git diff --check` clean. MQL5 anchor `227bf66` unchanged.

## Unreleased — Wave 2 + Wave 2.1 (research/ML/governance hardening + Mac freeze)

- Correctness (Wave 2): CPCV block-partition leakage fixed
  (`robustness.combinatorial_purged_cv` now `np.array_split`, two-sided
  embargo); allocation governor no longer resurrects a failed-gate strategy
  via the symmetric delta cap and clamps caller-supplied decay/ramp
  multipliers to `[0,1]`; drift execution-window aligned to the pnl windows
  (`drift_feed`); meta-OOS one-look now enforced BEFORE the OOS slice is
  consumed and `policy_weights` `as_of` is deterministic; `cost_stress_gate`
  guards `float(None)`; the ML risk seam tolerates non-unique `order_key`.
  Each fix has a pinned regression test (5 added).
- Security (Wave 2): telemetry collector caps the POST body at 1 MiB
  (defense in depth atop the loopback bind). Source audit: no
  high/critical reachable vulnerabilities.
- Provenance/status (Wave 2.1): broker-evidence model stated as three
  distinct facts — CAPTURED (owner, Windows) ≠ NOT COMMITTED / NOT
  repo-reproducible ≠ NOT VERIFIED (verdict). `probe.ok=true` is a
  precondition, not a parity PASS. `TASKS.md` marked archival (Phase 2.5
  checklist is not a current backlog); `PROGRESS.md` gained an authoritative
  CURRENT STATE header; `docs/WINDOWS_OWNER_HANDOFF.md` added. Denomination
  decision stays owner-gated (PENDING); no runtime semantics changed.
- Freeze: final Mac engineering freeze. Compile anchor `227bf66` unchanged
  (`git diff 227bf66 HEAD -- mql5/` empty); golds untouched. Wave 2.1 also
  closed three green-on-green gaps by adding real regression tests for the
  meta-OOS check-before-look ordering, the cost-stress `None` guard and the
  telemetry 413 cap (4 tests). Tests: 1585 passed / 1 skipped / 0 failed;
  `ruff check python/ tests/` clean; `git diff --check` clean.

## Unreleased — Wave 1 code-side pass (audit + security hardening)

- Security (Wave 1F): the telemetry collector (`telemetry_bridge.py`) and the
  status dashboard (`dashboard.py`) no longer bind `0.0.0.0` unconditionally.
  Both default to `127.0.0.1`; wider exposure is an explicit `--host` opt-in
  (behind a firewall/tunnel). Fail-safe default; no capability removed.
- Stage-B tick-value denomination (Wave 1A) remains **owner-gated**: with no
  owner export in `data/broker_exports/` (`n_exports: 0`), the suspected
  cross-currency double-conversion in `SpecLossPerLot`/`loss_per_lot` is
  neither confirmed nor patched. Runtime risk semantics unchanged. See
  `docs/DECISIONS.md` (2026-09-16 Wave 1 entry). Broker parity STILL NOT
  VERIFIED.

## Unreleased — Stage A: independent tick-value denomination measurement

- Rebuilt the lost Stage-A content on top of `58ce3ad`: the MQL5 owner
  exporter now optionally records an independent `OrderCalcProfit` witness per
  symbol, including the probe inputs, signs, values and failure diagnostics.
- Replaced the old PENDING-only derived/global-FX mechanism with conservative
  per-symbol `ACCOUNT_CURRENCY`, `PROFIT_CURRENCY`, or `UNVERIFIED` assessment.
  Circular FX derivation from tick value is forbidden; missing, failed or
  ambiguous evidence remains PENDING.
- Preserved old four-field export compatibility by keeping
  `denomination_probe` outside `FIELD_MAP`. The parity-only sizer replay uses
  the actual exported account currency only when the independent witness
  supports an account-currency verdict; it never manufactures a conversion.
- Observability only: runtime risk semantics, the real Python sizer, and
  broker parity status were not changed. Broker parity is STILL NOT VERIFIED;
  BTC remains an owner-side open measurement. MT5 validation and demo
  validation remain unclaimed.
## [1.0.0] — Final Repository Convergence (release candidate)

### Fixed — 2026-09-10: asset-class coverage counted a METAL export as FX
- `tools/broker_symbol_parity.py::asset_classes_covered()` classified with one
  `if`/`elif` chain, so the first matching rule consumed the symbol. The FX
  branch's bare shape test (`len(name) == 6 and name.isalpha()`) matched the
  owner's `XAUEUR` export (`SYMBOL_PATH` = `Metals\XAUEUR`) and the METAL branch
  was never reached: coverage reported `FX: exported: XAUEUR` with
  `METAL: PENDING (no owner export)` although the METAL export existed. The
  unconditional `out[cls] = ...` then let enumeration order decide which symbol
  represented a class.
- Coverage is now per-class and independent: the class rules (the harness's own
  existing markers — `forex/fx/major/minor`, `metal/xau/xag`,
  `index/indices/cfd`, `crypto/btc/eth` on the path, plus the `XAU`/`XAG` and
  `BTC`/`ETH` name witnesses) are evaluated as independent checks, a symbol may
  evidence more than one class, and each class keeps its first valid
  representative in an explicit order (name, then path) instead of last-write-
  wins. No broker taxonomy was invented and no equally broad rule replaced the
  shape test: `len(name) == 6 and name.isalpha()` survives only as a fallback
  for exports that carry no class evidence at all, and never applies to a name
  a specific class claims — so `XAUEUR` is METAL with or without a path, while
  a path-less `EURUSD` still counts as FX.
- Result on the four audited export identities: `FX: exported: EURUSD`,
  `METAL: exported: XAUEUR`, `INDEX_CFD: exported: US30`,
  `CRYPTO: exported: BTC`. This corrects **asset-class coverage only**; the
  owner-export-only path still reports `python_spec=None` per row, so broker
  parity remains NOT VERIFIED and the derived FX conversion rows stay PENDING.
- 7 regression tests added (nothing removed or weakened), including an `ast`
  structural pin against class-stealing `if`/`elif` chains, order-independence
  through `build_report()` on real files, and the deterministic
  sorted-first-representative policy. Restoring the old chain fails 7 tests,
  re-broadening the FX shape test fails 2, deleting the fallback fails 1,
  restoring last-write-wins fails 1, and a format-only reformat stays green.
- No MQL5, exporter, encoding, schema, field-name, numeric-formatting,
  tolerance, engine, risk, meta, gold or frozen-artifact change; no owner export
  was edited or fabricated.

### Fixed — 2026-09-10: broker export file encoding pinned to UTF-8 (`CP_UTF8`)
- `Mql5BotExportSymbolSpec.mq5` opened the export with
  `FILE_WRITE | FILE_TXT | FILE_ANSI` and no code page — i.e. `CP_ACP`, the
  terminal host's Windows ANSI code page — while `tools/broker_symbol_parity.py`
  loads it with `read_text(encoding="utf-8")` (no BOM tolerance anywhere in the
  owner readers). Pure-ASCII broker text is byte-identical in both encodings,
  which is why the owner's EURUSD run looked fine; any non-ASCII value the
  escaper deliberately passes through (a symbol path or server name with `Ø`,
  `«`, `±`) would land as non-UTF-8 bytes and be skipped as a malformed
  export. The call now states the encoding explicitly:
  `FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_ANSI, 0, CP_UTF8)` — the
  documented UTF-8 text mode, BOM-less. `FILE_ANSI` is kept on purpose: it is
  the flag that makes MQL5 honour a code page at all (without it a text file
  is written as UTF-16 with a BOM, which the reader cannot decode), and `0` is
  the delimiter argument that `FILE_TXT` ignores.
- Nothing else moved: `JsonEscape()` and its rules, `FILE_TXT` mode itself,
  `FileWriteString()`, the schema `mql5bot.broker_export/1`, field names,
  numeric formatting, the parity tolerances and the fail-closed
  "skip, never repair" rule are unchanged, and other MQL5 text lanes
  (logger/allocation/state/magic files, the CSV download read as `utf-8-sig`)
  were left alone because no owner reader holds a byte-exact UTF-8 contract on
  them. For the ASCII content observed so far the file bytes are identical, so
  no committed evidence or recorded hash is invalidated; `data/broker_exports/`
  was again neither created nor edited here.
- Regression-pinned in a fourth layer of `tests/test_broker_symbol_parity.py`:
  the repository reader is executed against candidate bytes (only BOM-less
  UTF-8 loads; CP1252, UTF-16 and BOM-prefixed UTF-8 are rejected, and a
  wrong-code-page export is skipped rather than transcoded), the exporter's
  `FileOpen` arguments are parsed rather than string-matched (flag order, line
  breaks, naming and the equivalent `FILE_BIN` +
  `StringToCharArray(..., CP_UTF8)` byte-write route all stay green), and the
  settings read from the source are modelled into bytes and piped through
  `load_owner_export()`. A revert to the code-page-less `FILE_ANSI` form, a
  `FILE_UNICODE`/no-`FILE_ANSI` variant or an explicit `CP_ACP` therefore fail
  the suite; escaping behaviour, layout-agnostic semantics and the
  malformed-export tests from the previous fix stay in place.
- STRICT RE-COMPILE + RE-EXPORT BY THE OWNER IS STILL REQUIRED — no MetaEditor
  in this sandbox, source validation only. Broker parity remains NOT VERIFIED
  until valid exports for FX, METAL, INDEX CFD and CRYPTO are committed.

### Fixed — 2026-09-09: owner broker export emitted invalid JSON (runtime defect)
- `Mql5BotExportSymbolSpec.mq5`: `JsonQuote()` wrapped string values in
  quotes without escaping them, so a `SYMBOL_PATH` of `Forex\EURUSD` was
  written as `"path": "Forex\EURUSD"` — a raw backslash is an invalid JSON
  escape — and `tools/broker_symbol_parity.py` skipped the owner export with
  `WARNING: skipping malformed export: Invalid \escape: line 11 column 19`.
  A generic `JsonEscape()` now escapes at the string-VALUE level for every
  string in the document: backslash first (it introduces every sequence
  produced afterwards), then `"`, `\n`, `\r`, `\t`, `\b`, `\f`, and any
  remaining U+0000..U+001F as `\u00xx`. MQL5 documents no `\b`/`\f` string
  escapes, so those two controls are matched by hex value; ordinary
  characters (non-ASCII included) pass through untouched, and the finished
  document is never post-processed.
- No contract moved: schema `mql5bot.broker_export/1`, field names,
  tolerances, the parity verifier and its fail-closed "skip, never repair"
  rule are unchanged, and no owner value is hard-coded in the exporter.
- Owner evidence untouched: nothing under `data/broker_exports/` was
  created, edited or replaced in this repository — no corrected owner
  artifact was fabricated here (`data/` is gitignored, and this checkout
  carries no `data/broker_exports/` at all). The owner regenerates the
  export by re-running the recompiled exporter on the live account.
- Regression-pinned in `tests/test_broker_symbol_parity.py` in three layers:
  the canonical JSON string contract asserted independently of any MQL5
  source text; a lightweight source contract that reads the helper's escape
  rules layout-agnostically (a `StringReplace()` table or a per-character
  switch both work) and replays them; and the harness behaviour on escaped vs
  malformed exports. A layout-only reformat of the helper and a rewrite into
  per-character style both stay green, while dropping any single rule,
  removing the control-character range, or escaping the finished document
  instead of the string values fails — as does the pre-fix source.
- STRICT RE-COMPILE + RE-EXPORT BY THE OWNER IS REQUIRED — source fix only.
  Broker parity remains NOT VERIFIED until valid exports for FX, METAL,
  INDEX CFD and CRYPTO are committed.

### Fixed — 2026-09-08 (2): strict-compile warnings closed (owner run: 0 errors / 2 warnings)
- RiskManager.mqh: the margin step-down loop now checks the
  OrderCalcMargin return value and vetoes on calculation failure
  (margin unknown -> risk veto, never guess) — warning 83 closed
  without weakening or silencing the check (DECISIONS.md 2026-09-08).
- Mql5BotDownloadData.mq5: #property version moved to the MetaEditor
  market metadata format "1.00" (same plane as the EA; release version
  1.0.0 elsewhere untouched) — warning 68 closed.
- tools/compile.ps1 + tools/run_mt5_backtest.ps1 converted to pure
  ASCII so Windows PowerShell 5.1 parses them deterministically from a
  clean clone (no manual UTF-8 BOM conversion). Regression-pinned in
  tests/test_mql5_sources.py.
- Owner-gate freeze anchor migrated 54613aa -> the warnings-closure
  commit (strict 0/0 is only satisfiable there); gold hashes unchanged.
- STRICT RE-COMPILE BY THE OWNER IS REQUIRED — source fixes only.


### Fixed — 2026-09-08: first real MetaEditor compile (50 errors / 2 warnings -> corrected source)
- MQL5: removed two fabricated trade retcodes (TRADE_RETCODE_RETRY /
  TRADE_RETCODE_NO_QUOTES do not exist in MQL5); retryable set is now
  exactly the four real transient codes REQUOTE/PRICE_CHANGED/
  PRICE_OFF/TIMEOUT (DECISIONS.md 2026-09-08).
- MQL5: POSITION_TYPE_LONG/SHORT mapped explicitly onto the real
  POSITION_TYPE_BUY/SELL enum; Ask()/Bid() made const; Allocation
  ParseStrategies terminal return; QueueCancelByTicket promoted to the
  labeled public restart-recovery boundary; EA metadata version moved
  to the MetaEditor market format "1.00" (separate plane from release
  version 1.0.0). Regression-pinned in tests/test_mql5_sources.py.
- Owner package: freeze anchor migrated forward 781bea4 -> the
  compile-correctness commit (old anchor contains non-compilable
  MQL5); gold fixture/config/dataset hashes unchanged.
- STRICT RE-COMPILE BY THE OWNER IS REQUIRED — this entry records the
  source fix, not a compile pass.


### Status (unchanged, honest)
- SOFTWARE/DOCUMENTATION RELEASE: READY.
- MT5 RUNTIME CERTIFICATION: BLOCKED_OWNER_ENVIRONMENT (no owner
  artifacts exist; nothing in this release claims MT5 validation).
- LIVE/PRODUCTION: NOT_READY.

### Added
- Owner-evidence verifier `python/mql5bot/owner_gate.py` +
  `tools/verify_owner_mt5_gate.py`: one command consumes an owner
  directory, verifies identity bindings (EX5/SymbolSpec/raw/parsed
  reports/environment/archive manifest), tester-model triads,
  file-bound real-tick and safety evidence (path+SHA-256, root
  containment, no prose/screenshots), first-divergence engine with the
  closed 14-class taxonomy; fail-closed verdicts, exit 0 only positive.
- Evidence binding tool `tools/owner_evidence_bind.py` (bind/manifest)
  — owners never hand-type hashes.
- Owner execution package `artifacts/owner_mt5_gate/` (frozen inputs,
  manifest template, checklist, report template, owner manual with the
  ten-step flow and the 29-file/19-group evidence contract).
- Human-facing documentation set: docs/README.md map, INSTALLATION,
  USER_GUIDE, MT5_SETUP_AND_OPERATION, FACTORY_GUIDE,
  CERTIFICATION_GUIDE, TROUBLESHOOTING, ARCHITECTURE, DEVELOPMENT,
  RELEASE_CHECKLIST; README rebuilt as the project front door.
- Empirical lane package definition (prepared, not executed):
  docs/AEGIS_EMPIRICAL_LANE_PACKAGE.md.
- Adversarial audit records: AEGIS_REALITY_GATE_AUDIT.md §85–§90 and
  AEGIS_REALITY_GATE_CONTINUATION.md §17a–§17g.

### Fixed
- CLI: escaped literal '%' in argparse help strings — `mql5bot
  {backtest,compare,optimize,walkforward,dashboard} --help` crashed
  with TypeError before; regression-pinned in tests/test_cli_help.py.
- Dependency drift: `httpx` (FastAPI TestClient) added to the `dev`
  extra of pyproject.toml; requirements.txt role documented.
- Owner README artifact table contradicted the verifier LAYOUT
  (stale 16-slot draft) — replaced with the exact 29-file contract
  and pinned by tests/test_docs_contract.py.

### Convergence
- `main` fast-forwarded to the canonical AEGIS implementation from
  arena/01a07c73-mql5bot (main was a strict ancestor; zero main-only
  commits; no history rewritten).

## [Unreleased] — AEGIS Final Convergence

### Added (reality gate)
- Gold Standard execution-parity artifacts (`artifacts/gold/`): frozen
  manifest (ema_crossover_ref, spec/dataset hashes, timing contract,
  §5 scenario map), deterministic fixture + both-touch micro, Python
  and DSL per-bar traces (byte-equal), expected execution (sizer lots +
  Meta seam DROP table), reconciliation state (MT5 = PENDING_OWNER).
- `tests/test_reality_gate.py` (14): determinism/frozen identity,
  Python↔DSL exact agreement, causality, stop-first both-touch,
  EMA/ATR parity vs MT5 transcriptions, sizing parity vs GetLots
  formula, below-min drop, Meta seam only-reduces, kill-switch first
  gate, allocation round-trip, no-order-path, reconciliation honesty.
- `docs/AEGIS_REALITY_GATE_AUDIT.md`: cross-runtime contract map (19
  seams), deterministic 9-step owner MT5 protocol, §72 status model,
  §83 evidence-backed Q&A. PRODUCTION = NOT_READY preserved.

### Added (master production convergence)
- `discovery/research_service.py`: deterministic idea→campaign→OOS→
  evidence→score application service; console one-click (injected
  runner) and CLI `research` drive the same chain. IS-only selection,
  ONE OOS look after selection, self-hashed §59 evidence chain.
- `discovery/journal.py`: structured event journal (closed §72
  vocabulary, fail-safe sink); `FactoryStore.reconstruct` (§73) +
  GET /strategies/{sid}/trail.
- Data-quality firewall (§52: NaN/Inf/out-of-order OHLCV rejected) and
  research cache identity (§54: engine/cost/feature/DSL versions in
  every stage cache key).
- Console lifecycle ops (pause/resume/retire, reason-required,
  store-bound), campaign detail, read-only allocation view; global
  research caps (§82: grid ≤ 24, ≤ 3 RUNNING campaigns, campaign time
  budget).
- Indicators T3, ICHIMOKU (unshifted), BETA (requires_columns
  contract field) — §7 coverage list complete, 71 kinds.

### Added
- Discovery governance package: E0–E7 evidence ladder, autonomy ladder
  (default RESEARCH_AUTOMATION), 16-component transparent Discovery
  Score (policy-hash bound, SCORE ≠ PERMISSION), staged resumable
  campaigns with hashed manifests + trial accounting, allocation
  governor (eligibility→weight→Meta→Risk; never score→lots), decay
  bands + requalification-only recovery, live-small ramp, portfolio
  assembly with concentration caps + UNKNOWN-honest correlation.
- Safety triad: independent kill switch (NORMAL/NO_NEW_TRADES/
  EMERGENCY_HALT, explicit audited reset), allocation circuit breaker
  (freeze + keep-last-safe + human review), external watchdog
  (rate-limited, fail-safe).
- Entry-decision chain (`discovery/entry_chain.py`): §57 event order;
  non-strategy origins (LLM/ML/community/factory) refused before any
  gate; approved risk = min(risk, Meta×budget).
- Operator console: kanban board (incl. DEGRADED/PAUSED), strategy
  detail with score rows + lifecycle history, explicit approval
  buttons, safety page, research intake + one-click campaign
  registration. UI cannot mark LIVE (source-scan tested).
- Indicator universe: 68 contract-declared kinds, multi-output refs,
  MTF/pivot closed-bar semantics, registry-wide causality property.
- Approval records bind evidence_hash + policy_version; machines can
  never self-approve human-gated transitions.
- Migration 0003 (approval enrichment); campaigns table (0002).
- Final acceptance fixtures §75–§82 (full chain, negative, safety,
  capital, scale, retirement) + property suite + static architecture
  scans + red-team attacks 12–25.

### Fixed
- Governor decay×ramp scaling (was renormalized away).
- Optuna/PyYAML made explicit dependencies for CI reproducibility.

## [Unreleased] — Aegis Release A foundation (audit + canonical risk models + Phase-1 MQL5 hardening)

### AEGIS research — Phase 3 Final Hardening (research-integrity blockers)
- `pipeline.purged_cv_stage` rewritten fold-isolated (BLOCKER 1): every
  scored span is its own cold-start engine run; engine `warmup_bars`
  primitive (TRUTH + FAST); purge = boundary censoring; warmup prices
  never reach a test-block interior; adversarial state-leak test suite
  (drawdown / equity-sizing / daily-loss / position-carry / position-cap
  triggers).
- `docs/CV_STATE_CONTRACT.md` (BLOCKER 2): data vs state leakage, span
  state table, crossing rules, WFA contrast, reuse prohibitions.
- `pipeline.optuna_optimize` hardened (BLOCKER 3): HyperbandPruner +
  trial.report/should_prune/TrialPruned on training-side dev prefixes,
  oos_guard_df, content-addressed cache, deterministic study name,
  n_jobs; 7 acceptance tests.
- `mql5bot.status` (BLOCKER 7) + zero-survivor blocking (BLOCKER 5):
  explicit SOFTWARE_PASS / EMPIRICAL_VALIDATION_PENDING / VERIFIED /
  FAILED / NOT_ELIGIBLE; MT5 NOT VERIFIED separate; S5 blocked with
  NO_VALID_SURVIVOR (screen leader diagnostics-only).
- `OosRegistry` schema 2 (BLOCKER 6): content-digest identity with
  strategy/engine/cost/feature/protocol versions; version bumps cannot
  mint second looks; v1 migration.
- FAST benchmark harness + docs/BENCHMARK_FAST.md (BLOCKER 4): honest
  scope (no Numba), measured profile, engine-level A/B = 1.001x (no
  speedup claimed), component measurements kept.
- `docs/MT5_ROUNDTRIP.md` (BLOCKER 8): owner workflow + checklist +
  anti-fabrication rules.
- Scenario matrix tests (trend, OU mean-reversion, slippage spike,
  commission x2, WFA carry, restart equivalence, cache miss).
### AEGIS research — Phase 1–2 (headless compile + tester tooling)
- `tools/compile.ps1` — MetaEditor compile round-trip: locates
  `metaeditor64.exe` (explicit/env/registry/`origin.txt` portable roots/
  Program Files/Start-menu/PATH), installs repo `mql5/` sources into the
  resolved MT5 data folder, compiles every EA/script under
  `Experts\Mql5Bot` + `Scripts\Mql5Bot`, gates on real compiler output
  (fresh `.ex5` + verbatim log), fails on errors and on warnings with
  `-Strict`; one reproducible combined log (`logs/compile-<stamp>.log`,
  SHA-256 of produced `.ex5` files).  Owner round-trip required: no
  MetaEditor in this sandbox.
- `python/mql5bot/mt5tester.py` — headless Strategy Tester core: `.set`
  parse/render with optimization ranges (`||start||step||stop||Y/N`)
  preserved verbatim; deterministic `[Tester]`+`[TesterInputs]` ini
  generation; locale-tolerant MT5 HTML tester-report parser → canonical
  typed metrics (`settings`/`fields`/`metrics`; raw pairs never lost);
  Windows-guarded sequential run/batch with timeout, raw-report
  preservation and JSON artifacts.
- `tests/test_mt5tester.py` — 23 tests: preset round-trips, ini golden
  lines, config determinism/rejection matrix, report parsing incl.
  composite drawdown/won-% rows and old-style labels (no terminal needed).
- `tools/run_mt5_backtest.py` — CLI: `generate-set` / `generate-ini` /
  `matrix` (strategy × symbol × timeframe jobs) / `parse` / `run` /
  `batch`; exit codes 0/1/2/3 documented.  `tools/run_mt5_backtest.ps1` —
  strict logged PowerShell wrapper for the owner/Windows runner.
- `tools/README.md` — usage docs: compile round-trip, determinism
  contract, report parsing, owner round-trip protocol, troubleshooting.
- Suite now 143 tests (`pytest tests/` green in this environment).

### Added
- `docs/IMPLEMENTATION_AUDIT.md` — full evidence-based audit of the repository
  against `docs/SPEC.md` (v4): architecture, implemented features, release
  readiness (A ≈ 25–30 %, B–E 0 %), missing/broken requirements, safety-critical
  gaps (ranked S1–S11), and the exact recommended implementation order.
- `docs/DECISIONS.md` — decisions log (SPEC §24): layout-preservation decision,
  Python-first canonical model decision, SPEC §19 reconciliation, version
  naming; carries the earlier decisions from HANDOFF §4.
- `python/mql5bot/symbolspec.py` — canonical broker `SymbolSpec` + pure
  normalisers (tick rounding, stops-level enforcement, volume min/max/step/
  limit, profit-currency loss-per-lot) + FNV-1a 32-bit magic derivation with a
  persistent, collision-safe `MagicRegistry` (SPEC §3.3/§3.9/§3.10 seed).
- `python/mql5bot/sizer.py` — canonical risk sizer on injected specs: fixed
  lot, risk % equity/balance, fixed money, Kelly capped at 0.25 (off by
  default); floor-to-step volume (never over-risk), below-min rejection,
  max/limit clamping, injected margin-calc reduce/reject (SPEC §8.C).
- `tests/test_symbolspec.py`, `tests/test_sizer.py` — 41 new tests incl. the
  five synthetic broker specs (EURUSD 5-digit, USDJPY, XAUUSD, US30-like,
  BTCUSD-like), FNV-1a vectors, registry stability across removal/reload,
  margin rejection, risk-budget invariant sweep.
- Suite now 80 tests (`pytest tests/` green in this environment).

### MQL5 hardening — Phase-1 DoD (S4 SymbolSpec)
- `mql5/Include/Mql5Bot/SymbolSpec.mqh` — MQL5 port of the canonical broker
  `SymbolSpec`: runtime `BuildSymbolSpec` querying every broker fact
  (SPEC §3.3), tick-grid/volume/stop normalisers and loss-per-lot math
  (SPEC §3.10) byte-parallel to `python/mql5bot/symbolspec.py`; the pure
  helpers are verified by the existing synthetic-spec test vectors
  (`tests/test_symbolspec.py`) on the Python side, which the port mirrors.

### MQL5 hardening — Phase-1 DoD (S5 MagicMap)
- `mql5/Include/Mql5Bot/MagicMap.mqh` — stable per-strategy identity: FNV-1a
  32-bit hash of `strategy_id` into the reserved magic range
  [16777216, 17825791] (SPEC §3.9, DoD #21) with a persistent, strict-format
  `MAGICMAP v1` registry (`mql5bot/State/magicmap.txt`) so reloads, removals
  and re-adds never reassign magics; collisions probe to the next free slot.
  FNV vectors are pinned on the Python side in `tests/test_symbolspec.py`.

### MQL5 hardening — Phase-1 DoD (S1 SL remediation)
- `mql5/Include/Mql5Bot/SlGuard.mqh` — post-fill stop-loss enforcement
  (SPEC §3.2): pure `SlVerdict` (present, correct side, outside broker
  stops level) drives a sleep-free verify → one modify → re-verify → close
  pump from OnTimer; a position the guard can neither protect nor close
  escalates to the caller (CRITICAL + alert + `ENGINE_HALT`).
- `python/mql5bot/slguard.py` + `tests/test_slguard.py` — mirror of
  `SlVerdict` with a verdict matrix on the five synthetic broker specs and
  pinned pump-threshold invariants (the MQL port's acceptance tests).
- Trade operations go through the Sleep-free `CTradeManager` API
  (`ClosePosition(ticket, vol)` / `ModifySLTP(ticket, sl, tp)`) that lands
  with the RetryQueue commit; until then the guard is not wired into the EA.

### MQL5 hardening — Phase-1 DoD (S2 kill-switch persistence)
- `mql5/Include/Mql5Bot/StateStore.mqh` — crash-safe persistence of the
  fail-safe state: GlobalVariables carry the hot kill-switch state, reason,
  day key, day-start equity and equity peak; a strict `AEGIS_STATE v1`
  file carries the ticket registry with per-`POSITION_IDENTIFIER`
  management flags (`partialDone`, `beDone`). Restart NEVER resets the
  daily loss or forgets the drawdown peak (SPEC DoD #13/#14).
- `mql5/Include/Mql5Bot/RiskManager.mqh` — risk engine rewritten on the
  injected `SSymbolSpec`: mode-aware sizing over the enforced stop
  distance (FixedLot / RiskPercentOfEquity / RiskPercentOfBalance /
  FixedMoney / capped Kelly ≤ 0.25), runtime profit→deposit conversion,
  broker min/max/limit volume normalisation (never round up), margin check
  via `OrderCalcMargin` with bounded scale/walk-down, and the persisted
  state machine: `AdoptState` on startup, `SetState` hot-saves immediately,
  daily-loss pause expires only at the day rollover, drawdown breach trips
  `ENGINE_HALT` (explicit reset only).
- `mql5/Include/Mql5Bot/Config.mqh` — shared `ENUM_ENGINE_STATE` and
  success/retryable/fatal retcode classifiers for the execution rewrite.
- `mql5/Include/Mql5Bot/PositionGuard.mqh` — partial scale-out is now
  once-per-position across restarts via the persisted `partialAlreadyDone`
  flag (the in-process disarm already existed).
- `python/mql5bot/failsafe.py` + `tests/test_failsafe.py` — mirror of the
  state machine (rollover/guard/reset transition rules) and the strict
  `AEGIS_STATE v1` row codec (quarantine/malformed-row semantics).

### MQL5 hardening — Phase-1 DoD (S3 RetryQueue / Sleep removal)
- `mql5/Include/Mql5Bot/RetryQueue.mqh` — bounded sleep-free retry engine:
  32 slots, exponential backoff 500 ms × 2^n capped at 10 s, hard attempt
  cap, same-operation dedupe (action+symbol+ticket+comment) that refreshes
  the schedule without resetting the cap.
- `mql5/Include/Mql5Bot/TradeManager.mqh` — execution rewritten without a
  single `Sleep`: one attempt per call, a single REQUOTE re-send with a
  refreshed price, the bounded FOK→IOC→RETURN filling chain, verify-before-
  resend against deal history on TIMEOUT/RETRY, latency/slippage capture
  and one structured `[mql5bot] EXEC|…` audit line per action; close and
  SL/TP modify go through the same queue. Pending placement/cancel expire
  by bars with queued cancellation.
- `mql5/Experts/Mql5Bot/Mql5Bot.mq5` — EA wired to the hardened engine:
  OnTimer scheduler (queue pump, orphan-pending cancellation, ticket-
  registry sync + adoption, SL-protection pass, equity-limit checks, guard
  pump, state flush, heartbeat), 10 s kill-switch close cadence, entry
  gate chain on new bars, `ENUM_ENGINE_STATE` start-up adoption with the
  explicit one-shot kill-switch reset, FNV-1a magic allocation, input
  validation on `OnInit` (INIT_PARAMETERS_INCORRECT).
- `python/mql5bot/retryqueue.py` + `tests/test_retryqueue.py` — mirror of
  the backoff schedule and queue semantics (dedupe-without-reset, earliest-
  due pop, bounded slots).

### AEGIS research — Phase 1/4/5 canonical portfolio engine (python)
- `python/mql5bot/engine.py` — deterministic multi-position portfolio
  engine (netting and hedging): one book per symbol in netting (same-side
  merges keep per-leg attribution with a lots-weighted book SL/TP;
  opposite-side desires offset legs FIFO at the open and any remainder
  opens fresh), independent per-(symbol, strategy) books in hedging;
  `allow_signal_exit` flips, per-strategy risk overrides and explicit
  exposure caps (total / per-strategy positions, per-symbol / corr-group /
  currency notional shares, portfolio heat) evaluated on the post-action
  portfolio with rejection events.  Tick-valued PnL with profit-side tick
  values and profit→deposit conversion; sizing exclusively through
  `mql5bot.sizer` (no direct risk/stop/contract formula — guarded by a
  source test); server-time day rollovers with swap at boundaries,
  day-start daily-loss snapshot and drawdown kill switch (checks act at
  the bar open on prior-close equity); walk-forward `schedule` freezes
  params per segment; valuation/bar-order contract documented in the
  module docstring.
- `python/mql5bot/symbolspec.py` — `SymbolSpec` gains the optional
  profit-side tick value (`tick_value_profit`, default `None` = symmetric)
  and `tick_value(side, move)` (gains on the profit side, losses on the
  loss side).
- `tests/test_engine.py` — 29 tests: canonical-path source guard, tick
  value profit side, netting merge/partial-FIFO/full-offset/flip
  semantics, hedging simultaneous books, Phase-4 exposure caps,
  multisymbol notional with conversions, server-day daily-loss reset,
  permanent drawdown kill switch, variable spread / reject mask / gap /
  swap / round-trip commission / margin rejection, fixed-lot and
  below-min rejection, max-bars and trailing ratchet, walk-forward
  schedule freeze, engine validation.
- Suite: **198 tests** green in this environment (`pytest tests/`
  --collect-only = 198; 169 at the pre-engine tree + these 29).

### AEGIS research — Phase 6 continuous walk-forward (python)
- `python/mql5bot/optimizer.py` — `walk_forward` rewritten on the engine's
  scheduled-parameter run: ONE continuous backtest over the full sample
  (capital/portfolio/costs/risk carried forward — the legacy concatenating
  per-window runs with capital resets are gone).  Rolling-origin IS
  windows feed per-window best params, frozen per OOS segment via
  `schedule=(oos_start - 1, params)`; geometry is documented
  (`warmup_bars`, `is_bars`, equal `segment_bars`, remainder absorbed by
  the last OOS segment); bars before the first OOS start warm the account
  with the registry defaults and are excluded from the OOS aggregates.
- Per-window reporting: IS dates, OOS dates, selected params, IS metrics,
  OOS metrics (continuous equity slice of the OOS span; trades attributed
  to the window of their ENTRY bar), WFE, OOS trade count, OOS max
  drawdown, cost and a price-regime breakdown (drift, annualised
  volatility, efficiency ratio, up-fraction, direction).
- `python/mql5bot/backtest.py` — `run_backtest` accepts the engine
  `schedule` passthrough (walk-forward freeze on the single-symbol path)
  and its trade rows now surface the engine's ledger columns.
- `python/mql5bot/engine.py` — trade rows gain two ledger columns: `fees`
  (entry + exit commission shares + allocated swap) and `costs` (`fees` +
  the tick-valued spread/slippage drag of both executions against the raw
  quote levels), so per-window/per-strategy cost accounting needs no fill
  replay.  Row PnL stays net.
- `tests/` — 203 tests green: engine ledger decomposition pinned exactly
  (7-tick surcharge x 2 legs on a flat round trip), walk-forward windows
  tile the OOS region contiguously, aggregate OOS equity is the unique
  continuous run over the OOS bars (no 10k resets), per-window reporting
  fields, too-little-data ValueError.

### AEGIS research — Phase 7 WFA leakage controls (python)
- `python/mql5bot/optimizer.py` — `walk_forward` gains two SELECTION-only
  leakage controls (signals in the continuous run always use everything
  already released):
  * `embargo_bars`: the IS selection window ends that many bars before the
    OOS start, so parameter choice never scores the bars adjacent to the
    test boundary (their trades would be force-closed at the boundary in
    an isolated run); geometry exposes `embargo_bars`/`purge_bars` and
    `train_end` moves with the embargo.
  * `purge_bars`: boundary-censored trades (those exiting within the last
    `purge_bars` of the embargoed IS window) are dropped from the IS
    metrics together with the equity tail carrying them; the number
    dropped is reported per window as `is_trades_purged`
    (`_selection_metrics` is unit-tested directly).
- `tests/test_strategies_optimizer.py` — automated leakage tests: per-window
  embargo geometry exactness; selection IS bars strictly before each OOS
  start; purge unit scenario (an isolated run force-closes its open
  position at the slice boundary with `end_of_data` and the purge drops
  exactly that trade); validation raises; and a signal-level causality
  test for every registered strategy (signal prefixes must be unchanged
  when the frame is truncated at a probe bar — no lookahead, which is what
  frozen OOS signals rely on).
- Suite: **207 tests** green in this environment (`pytest tests/` exit 0).

### AEGIS research — Phase 8 metrics upgrade (python)
- `python/mql5bot/metrics.py` — `compute_metrics` now returns the Phase-8
  statistics on top of every legacy key (nothing removed, empty report
  schema extended to match):
  * drawdown/return quality: `recovery_factor` (net return / |max DD|),
    `ulcer_index_pct` (rms of the drawdown series), `downside_deviation_pct`
    (semi-deviation, annualised, of intraday-return proxy).
  * tail risk: `var_95_pct`/`cvar_95_pct` and `var_99_pct`/`cvar_99_pct`
    from the empirical (unannualised) return distribution.
  * stability: `rolling_sharpe_median`/`rolling_sharpe_worst` on a
    half-period (50% of periods-per-year) rolling window; monthly
    consistency via `monthly_win_rate_pct`, `monthly_avg_pct`,
    `monthly_std_pct` over the existing `monthly_returns` resample.
  * trade-profile: `avg_trade`/`median_trade` (pnl per round trip) and
    `avg_trade_bars`/`median_trade_bars` (bars in market), `avg_win`/
    `avg_loss` unchanged.
  * capital efficiency: `exposure_pct` (union of in-market bars) and
    `turnover_pct` (closed-lot bars / total in-market bars), both as
    best-effort approximations tolerant of malformed log rows.
  * robustness/concentration: `max_consecutive_losses`,
    `return_concentration_hhi` (Herfindahl on |pnl| shares),
    `top5_trades_pct` (share of net pnl from the 5 best trades),
    `expectancy_last20`/`win_rate_last20_pct` (trailing-20 per-trade
    stats).  A `window = max(20, round(periods_per_year * 0.5))` helper is
    shared with the rolling calculation and regression is guarded by the
    `_r` value formatter staying on 4 dp.
- `tests/test_metrics.py` — 9 new hand-pinned tests (new dedicated file;
  every statistic checked against a directly recomputed fixture on small
  deterministic inputs; empty/short-series schema completeness included).
  Total suite: **216 tests** green (`pytest tests/` exit 0), ruff clean on
  changed files.

### AEGIS research — plan 0–8 gate closure (python)
- Owner pasted the canonical 0–20 execution plan; this section closes the
  exit-criteria gaps the gate audit found in the already-built research
  stack (plan phases 1–8 otherwise PASS with evidence).
- `python/mql5bot/costs.py` — four deterministic cost profiles via
  `cost_profile()`: `ZERO` (cost-free), `BASE`, `STRESSED`, `SEVERE`,
  escalating field-by-field (spread, slippage, commission + minimum, swap
  long/short, gap limit); profiles never inject a reject mask.  Tests pin
  preset values, determinism and validation; an engine integration test
  runs one identical round trip under all four and asserts ZERO costs
  zero and the ledger outcome is strictly monotone BASE < STRESSED <
  SEVERE at equal volume.
- `python/mql5bot/optimizer.py` + `strategies.py` — every walk-forward
  window now records `param_hash` (deterministic sha-1 of the selected
  params), `strategy_version` (declared in `STRATEGY_VERSIONS`,
  "undeclared" for ad-hoc registry entries; `list_strategies()` exposes
  it) and `dataset_version` (sha-1 content digest of the frame unless the
  caller passes an explicit tag); both tags repeat at the top level.
  `strategies.py` legacy ruff findings cleaned while touched.
- `tests/test_leakage_features.py` — adversarial future-data pins (plan
  Phase 8): extreme values injected into bars >= PROBE must not move any
  earlier output — parametrised over EMA/SMA/rolling std/RSI/ATR/
  Bollinger/Donchian/MACD/highest/lowest/crossover, every registered
  strategy signal, and per-span regime features (out-of-span mutation
  leaves the report identical; in-span mutation moves it — guard against
  vacuous tests).
- `docs/STATE_MODEL.md` (plan 4) — A market/account, B strategy, C
  research/training state classes mapped to engine objects, with carry
  rules and python lifecycle/restart semantics documented.
- `docs/WFA_CONTRACT.md` (plan 6) — mathematical contract of the
  implemented continuous walk-forward: exact interval geometry,
  freeze timing, CARRY_ALLOWED default / FORCE_FLAT never silently
  enabled, knowledge non-transfer, causal warmup, entry-bar attribution
  and continuous-ledger aggregation.
- Suite: **239 tests** green (`pytest tests/` exit 0), ruff clean on all
  changed files.

### AEGIS research — plan Phase 10: fast research engine benchmark (python)
- `python/mql5bot/perf.py` — deterministic measurement instruments:
  `ema_grid_axes` (factorises a requested parameter-set count into a valid
  fast/slow EMA grid), `single_run_metrics` (untimed wall/throughput
  measurement), `grid_metrics` (end-to-end grid_search timing at any
  `n_jobs` with parent-retention memory estimate via a capped 300-set
  tracemalloc probe scaled linearly) and `grid_signature` (top-N
  params+metric records for equivalence checks).  First cut timed under
  tracemalloc (~4x inflation) — fixed: timing runs clean.
- `tools/benchmark_research.py` — data-load + single-run + 100/1,000/
  10,000-set grid ladder at `n_jobs = 1` vs `n_jobs = cores`, reporting
  speedup, runs/sec, bars/sec, trades/sec, peak memory and a PASS/FAIL
  numerical-equivalence line; JSON export.
- `tests/test_perf.py` — axes factorisation, report shapes, and the
  parallel path reproducing the sequential ordering and values exactly.
- Measured evidence (480-bar synthetic hourly frame, seed 42, 2 cores,
  ema_crossover defaults): single run 22.6 ms (~21.3k bars/s, ~665
  trades/s); grid 100 sets seq 2.21 s / par 1.85 s, 1,000 sets seq
  22.2 s / par 18.6 s, 10,000 sets seq 296 s / par 250 s — parallel
  speedup 1.20x/1.19x/1.18x at 2 cores (~40 runs/s at 10k); parent
  retention ~90 MB estimated at 10k; equivalence PASS at every size.
  Further FAST-engine optimisations (indicator caching, pruning,
  vectorisation passes) are Phase-18 items to be measured the same way.
- Suite: **245 tests** green in this environment (`pytest tests/` exit 0),
  ruff clean on changed files.

### AEGIS research — plan Phase 11: statistical robustness gates (python)
- `python/mql5bot/robustness.py` — deterministic, seeded validation gates
  (research gates, not cosmetic report fields), each pinned by synthetic
  known-good/known-bad tests in `tests/test_robustness.py` (13 tests):
  * `psr` / `deflated_sharpe` — probabilistic and deflated Sharpe; DSR
    discounts honest trial multiplicity (n_trials=1 -> no discount).
  * `monte_carlo_pnl` — trade resampling: net-profit distribution,
    probability of a profitable path, percentile bands.
  * `perturbation_report` — parameter perturbation / systematic parameter
    permutation with a location-free flatness ratio (median-worst)/
    (best-worst) that exposes curve-fit spikes.
  * `combinatorial_purged_cv` + `probability_of_backtest_overshoot` —
    CPCV over configurations with an embargo control and the PBO
    estimate; calibrated edge-vs-noise separation across seeds.
  * `white_reality_check` / `hansen_spa` — multiple-testing reality
    checks via a seeded stationary bootstrap (fresh uniform origin per
    block; an early chained-origin version had zero bootstrap variance
    and was fixed); SPA is a documented studentised simplification.
  * `stamp_report` — every robustness report carries method, strategy,
    strategy_version and dataset_version (plan exit gate).
- Purge/embargo/WFA validation methods were already delivered in Phases
  6-8 with their leakage tests; Phase 11 therefore passes its gate.
- Suite: **258 tests** green (`pytest tests/` exit 0), ruff clean on all
  changed files.

### AEGIS research — plan Phase 12: portfolio research (python)
- `python/mql5bot/portfolio.py` — deterministic strategy-portfolio tools
  with 7 pinned tests in `tests/test_portfolio.py`:
  * `returns_frame` (aligned per-period returns), `correlation_matrix` /
    `covariance_matrix` (valid: symmetric, unit diagonal, finite),
    `portfolio_volatility` (pinned against direct numpy), `equal_weight`,
    `concentration_hhi`.
  * `currency_exposure` (per-profit-currency notional shares via the
    canonical specs) and `portfolio_heat` (gross notional / equity).
  * `strategy_overlap` — pairwise Jaccard overlap of in-market bars per
    symbol over engine trade ledgers (full/none/partial scenarios pinned,
    inclusive exit bars).
  * `apply_limits` — allocation veto against max_weight / currency caps:
    rejected proposals return the input untouched (zero accounting
    impact).  Execution-time caps remain enforced by the engine
    (per-symbol/currency/corr-group notionals, heat, position counts —
    test_engine.py), so portfolio limits cannot be exceeded.
- Suite: **265 tests** green (`pytest tests/` exit 0), ruff clean on all
  changed files.

### Performance & selection hardening — Phase A: repair verifiability (python)
- `pyproject.toml` — `pythonpath = ["python"]` under `[tool.pytest.ini_options]`
  so plain `pytest` from the repo ROOT works without installing the package
  (verified in a venv with mql5bot uninstalled); `bench` marker registered.
- `ruff check python tests` — fully clean (31 findings fixed: dead imports
  removed, `dict()` literals, unused `noqa` directives, quoted-annotation
  cleanup, unused locals, one RUF059 unpack; the two `BLE001` blind
  `except Exception` sites in dashboard.py are HTTP/refresh boundary
  handlers, narrowed to explicit exception types first with a documented
  guarded fallback that always surfaces the error).
- `tests/test_benchmark.py` (marked `bench`) — measurement harness:
  run_backtest wall + bars/sec + trades/sec, walk-forward s/window, peak
  memory; BEFORE table recorded in PROGRESS.md.
- Consumer audit of `exit_reason` / `max_drawdown_pct` documented in
  PROGRESS.md: cli/dashboard/report treat both as display-only; the
  Phase-4 re-pin (final reason `stop_loss`, DD band -9.0..-4.9) needs no
  consumer change.
- Suite: **268 tests** green from the repo root; ruff clean on `python/`
  and `tests/`.

### Performance & selection hardening — Phase B: robust fitness composite (python)
- `python/mql5bot/metrics.py` — `RobustFitnessConfig` (explicit validated
  weights, sum ~= 1.0; eight documented components: expectancy vs start
  equity, recovery/calmar, rolling-Sharpe median, cost-stress resilience,
  minus drawdown, HHI concentration, turnover, rolling-Sharpe-worst
  instability — each with an explicit reference point) and
  `composite_score(metrics, config, stressed_metrics=None)` returning a
  [0,1] score with per-component breakdown; missing metrics are neutral
  (weight/2), resilience is neutral unless stressed metrics are supplied
  (`resilience_measured` flag).  Pinned on hand-computed fixtures in
  tests/test_metrics.py (all-at-ref -> 0.70, all-half -> 0.5 + resilience
  0.4 case, degenerate -> neutral 0.5, config validation).
- `python/mql5bot/optimizer.py` — `metric="composite"` is an OPT-IN
  ranking for grid_search and walk_forward (`composite_config` explicit,
  default selection metric stays "sharpe", verified by test); the OOS
  one-look research policy ("never optimise on the same OOS certification
  slice more than once per dataset/strategy version") is documented in the
  walk_forward docstring and WFA_CONTRACT.
- Suite: **273 tests** green from the repo root; ruff clean on `python/`
  and `tests/`.

### Performance & selection hardening — Phase C: FAST/TRUTH screening split (python)
- `python/mql5bot/fast_engine.py` — FAST engine: NumPy-array
  orchestration for the single-(symbol, strategy) netting screening case
  with the same signature and result shape as the canonical
  `mql5bot.backtest.run_backtest` (drop-in for grid/walk-forward
  sweeps).  Reuses the canonical pure math (sizer, costs, symbolspec
  rounding, engine `leg_cash`) so no accounting/sizing formula is
  duplicated; no per-bar pandas; scope gates raise NotImplementedError
  (schedules/swaps/caps/margin calculators are TRUTH-path).  FAST is
  screening-only — never final, never a profit claim; the TRUTH engine
  and MT5 tester remain the only certification path.
- `tests/test_fast_engine.py` (38 tests) — equivalence pinned on random
  fixtures: 5 strategies x cost/exit/halt/trail/breakeven/long-only
  knob sets vs run_backtest, plus engine-style signal exits
  (allow_signal_exit=True, partial scale-outs) vs PortfolioEngine:
  identical trade rows, equity within 1e-8, metrics approx-equal;
  loud scope gates; determinism; input purity.
- `tests/test_benchmark.py` — new `bench` comparison test
  (FAST vs TRUTH on 3120 hourly bars, direction asserted, magnitude
  reported): ~1.6x on this sandbox (TRUTH 61-73 ms/run ~48k bars/s,
  FAST 38-42 ms/run ~78k bars/s).
- Suite: **312 tests** green from the repo root; ruff clean on `python/`
  and `tests/`.

### Performance & selection hardening — Phase D: staged pipeline + run manifests (python)
- `python/mql5bot/pipeline.py` — the staged funnel with reproducible
  `RunManifest`s (deterministic manifest_id over params/data-digest/cost
  config/seed/stage/status/metrics):
  * S1 screen (FAST engine default, explicit rank metric, top_k);
  * S2 x2-cost robustness stress (spread+commission doubled, survival
    gate documented: end equity, min trades, drawdown bound);
  * S3 own trade-level purge + embargo combinatorial CV (mlfinlab idea
    referenced, not copied): leaky trades excluded from IS per fold,
    pnl attributed to the entry bar, per-fold selection log;
  * S4 headless MT5 tester stage — records an honest `skipped` manifest
    without a terminal host (certification is never faked);
  * S5 OOS certification gated by `OosRegistry` one-look policy
    (second look on the same dataset version raises
    `OosOneLookViolation`; registry checked before the run).
  Deterministic content-digest cache; `optuna_optimize` under the
  optional `optimize` extra only (TPE seeded + deterministic, guarded
  ImportError otherwise).  docs/STAGED_PIPELINE.md documents the gates.
- `tests/test_pipeline.py` (16 tests) — manifest id determinism (created
  excluded), screen ranking/gates, cost-stress doubling + gate, block/
  pnl helpers, purge+embargo semantics proven by fold selection on
  crafted leak/clean configs, MT5 skip honesty, one-look registry
  persistence + refusal, cache replay, Optuna guard, full-path run with
  survivors and the no-survivors loud-skip branch.
- pyproject: `optimize` optional extra.
- Suite: **328 tests** green from the repo root; ruff clean on `python/`
  and `tests/`.

### Performance & selection hardening — Phase E: ML interfaces only (python)
- `python/mql5bot/ml_interfaces.py` — interface-only ML contracts:
  TripleBarrierLabeler / MetaLabeler / ProbabilityCalibrator /
  FeatureStore stub every method with NotImplementedError (no ML
  implementations, no training, no neural networks — per brief);
  `RiskContext` (frozen hard limits) + `MLAdvice` (schema that CANNOT
  express stops, risk values or limits — only confidence, side veto and
  a lots CAP); `apply_ml_advice` seam (drops/shrinks engine orders,
  re-checks all invariants on its output, refuses caps above the hard
  limit); `check_ml_invariants` + `ML_INVARIANTS` registry.  The
  canonical engine still has no ML hooks — invariants hold by
  construction and are pinned for any future insertion.
- `tests/test_ml_interfaces.py` (18 tests) — every stub raises,
  package scan bans tensorflow/keras/torch/sklearn/transformers/
  lightgbm/xgboost imports, schema cannot carry risk controls, frozen
  context, seam veto/direction/cap semantics, each of the four
  invariant violations detected, identity pass-through.
- Suite: **346 tests** green from the repo root; ruff clean on `python/`
  and `tests/`.

### Performance & selection hardening — Phase F: real-tick certification protocol (python + docs)
- `python/mql5bot/certify.py` — certification protocol: per-regime data
  ladder (M1 OHLC -> every tick -> every tick on real ticks -> real
  ticks), 100-trade minimum gate, spread-floor report (missing average
  fails loudly), 0.5-3.0 pip slippage surcharge tiers applied
  analytically to the canonical TRUTH M1 leg, OHLC-vs-tick degradation
  per leg vs its own baseline with explicit 30-50% band flags, python
  TRUTH cross-check leg (never gates the verdict), markdown report
  rendering, and a verdict that is VERIFIED only when every required
  leg ran and passed — otherwise NOT VERIFIED with all reasons (no MT5
  terminal -> not run, never guessed).
- `tools/certify_strategy.py` — CLI (config JSON -> markdown report;
  exit 0 only for VERIFIED); binds the mt5tester runner only on
  Windows terminal hosts.
- `docs/CERTIFICATION.md` + README "Research evidence, not promises"
  section (backtests are not a promise of live profit).
- `tests/test_certify.py` (11 tests) — plan/ladder, surcharge math,
  degradation band + synonyms + undefined baselines, trade/spread
  gates, verdict honesty (no legs / failed leg / min-trades /
  cross-check never gates), orchestration with fake runner incl. the
  failed-leg row exclusions, rendering.
- Suite: **357 tests** green from the repo root; ruff clean on
  `python/`, `tests/` and `tools/`.

### Performance & selection hardening — Phase G: acceptance (python + docs)
- Final ten-section report `docs/PHASE3_FINAL_REPORT.md` (CURRENT
  COMMIT | FILES CHANGED | FILES ADDED | TEST COUNT | TEST RESULT |
  RUFF RESULT | BENCHMARK BEFORE/AFTER TABLE | KNOWN LIMITATIONS |
  SAFETY GAPS | NEXT 3 TASKS); acceptance gates re-run: 357 tests
  green, ruff clean on python/tests/tools, zero MQL5 files touched,
  MetaEditor compile status honestly NOT VERIFIED (never guessed).
- Suite: **357 tests** green; ruff clean.

### Notes












- Phase-1 DoD for this branch is complete (S4 SymbolSpec, S5 MagicMap, S1
  SL remediation, S2 kill-switch/day-loss/DD persistence, S3 RetryQueue /
  no-Sleep execution); status board + residual gaps in
  `docs/IMPLEMENTATION_AUDIT.md` §18.
- AEGIS research Phases 1–2 tooling is committed but **NOT verified on a
  Windows terminal** (no MetaEditor / terminal64.exe in this sandbox):
  `tools/compile.ps1 -Strict` and `tools/run_mt5_backtest.ps1 run|batch`
  require the owner round-trip before any compile/backtest claim.
- "MQL5 COMPILE RESULT: COMPILE NOT VERIFIED — MetaEditor unavailable in
  this environment." Owner-side compile + zero-warning pass and a strategy-
  tester run are still required (HANDOFF §10, audit §18).

## [1.0.0] — 2026-09-04

### Added

**MQL5 Expert Advisor** (`mql5/`)
- `Mql5Bot.mq5` main EA with 5 strategies: EMA crossover, RSI reversal,
  Donchian breakout, Bollinger reversal, MACD momentum
- `RiskManager.mqh` — risk-based position sizing, daily loss limit,
  drawdown kill-switch, spread guard
- `TradeManager.mqh` — market & pending stop-order execution with retry
  logic, fill verification via deal history, hedging/netting safe
- `PositionGuard.mqh` — ATR trailing stop, breakeven, partial scale-out
- `SignalEngine.mqh` — completed-bar-only strategy evaluation (no repaint)
- `Session.mqh` — days-of-week bitmask + intraday trading window
- `Logger.mqh` — leveled file + terminal logging
- `Telemetry.mqh` — HTTP heartbeat/trade/alert reporting (WebRequest)
- `Mql5BotDownloadData.mq5` script — export bar history to CSV for the
  Python toolkit
- Presets for all 5 strategies (`mql5/Presets/Mql5Bot/`)

**Python quant toolkit** (`python/mql5bot/`)
- Vectorized strategy twins with an identical evaluation contract
- Event-driven backtest engine: lookahead-proof entries, intrabar stop
  simulation, spread/slippage/commission cost model, risk-based sizing,
  trailing/breakeven/partial exits, daily-loss & drawdown kill switches
- Performance metrics: CAGR, Sharpe, Sortino, max drawdown & duration,
  Calmar, win rate, profit factor, payoff, expectancy
- Grid-search optimiser (multiprocessed) and walk-forward validation
- Self-contained interactive HTML reports
- Live web dashboard with simulated or MT5-bridged bar feed
- Telemetry bridge — HTTP collector for EA events (JSONL + SSE stream)
- CLI (`mql5bot`) with data / backtest / compare / optimize / walkforward /
  dashboard subcommands
- Reproducible synthetic OHLC generator, CSV loader, live MT5 bridge

**Tooling & QA**
- 36-test pytest suite, including a hard no-lookahead oracle test and an
  exact commission-accounting test
- GitHub Actions CI: test matrix (Python 3.10–3.12) + CLI smoke test
- `scripts/install_mql5.py` — one-command deployment into the MT5 data
  folder (auto-detection on Windows/macOS/Linux-Wine)

[1.0.0]: https://github.com/raminhdev/mql5bot/releases/tag/v1.0.0

## 2026-09-06 — AEGIS Strategy Factory integration gate
- Security red team: evidence refs bound to (strategy, version,
  spec_hash, PASS, required type); intake sanitization enforced in the
  interpreter with injection warnings surfaced; policy-override and
  state-forgery detectors; canonicalization idempotency fixed
  (integer identity fields; integral-float tolerance in schema).
- Lifecycle hardening: type-adequate, identity-bound promotion
  evidence store-enforced; new versions open a fresh DRAFT line;
  research children register via explicit parent linkage (§25).
- End-to-end fixture: EN/FA canonical texts → identical signals;
  full DRAFT→SHADOW ladder on real deterministic backtests with a
  fixture gate policy (production policy untouched); negative path
  (OOS fail ⇒ REJECTED ⇒ no eligibility); AST-proven MT5 isolation.
- Proofs: version immutability (8 modification classes), exact
  reproducibility, manifest completeness, multiple-testing accounting,
  t0-invariance, OOS-horizon isolation, causal regime labels,
  shadow/backtest signal equivalence, anti-churn oscillation
  simulation, duplicate/race safety, audit-tuple events.
- Factory totals: 118 factory tests + 67 DSL tests; full suite 1023.
