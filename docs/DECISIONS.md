# Aegis — Decisions Log

Every meaningful architectural deviation from `docs/SPEC.md` and every
significant trade-off is recorded here with its rationale. When uncertain
about a financial rule, the more conservative option wins and is documented.

Format: newest on top. `[SPEC]` entries record SPEC-mandated decisions that
were already made and must not be silently reverted.

---

## 2026-09-19 — A re-run must not need Market Watch at all: verify-first adoption, and the asynchronous ChartClose is never assumed done (STAGE 4 R10)

**Trigger.** gate_run13 (on 96125a0): stage 4 refused at `symbol_state` with
last_error **4305** — "cannot adopt the surviving custom symbol EURUSD.G1:
SymbolSelect(false) failed (last_error=4305) after 0 delete attempt(s)".
4305 is **ERR_MARKET_SELECT_ERROR** — "error adding or deleting a symbol in
Market Watch". The failing call was the DESELECT itself, with zero delete
attempts made: the R9 chart-close loop found nothing left to block on, and
the deselect still failed.

**Root cause 1 — ChartClose is asynchronous.** `ChartClose` queues a close
command and returns; the chart is NOT gone when the call returns. The R9
drop closed charts and then immediately called `SymbolSelect(sym,false)`
while MT5 still considered the symbol in use. R9 had added a bounded retry
around the DELETE but none around the DESELECT, so the very first deselect
failure was fatal — the same async class of defect as the delete retry R9
already fixed.

**Root cause 2 — the design wrote properties it did not need to write.** On
a re-run the surviving symbol was configured by the previous run from the
SAME manifest, so every property already holds the correct value. Property
WRITES are the ONLY thing that requires a deselected symbol (the 5306 rule).
Rewriting values that are already correct is what MANUFACTURED the deselect
requirement — and the deselect is what failed. Bars never need it:
`CustomRatesDelete`/`CustomRatesUpdate` work on a SELECTED custom symbol
(the normal live-feed path for custom symbols).

**Decision (verify-first symbol-state contract; supersedes the R9 drop-first
three-outcome contract).**

1. **Verify-first adoption.** Before touching anything, every settable
   property of a custom survivor is read back and compared to the manifest
   spec with the exact semantics of the final `verify_properties` stage
   (doubles at the pipeline's own `%.10f` precision; the R8 CALCULATED tick
   values excluded — not settable (5307), they must never force a rewrite).
   An empty difference list means **`adopted_verified`**: ZERO property
   writes, NO deselect, Market Watch untouched — the steady-state re-run
   needs nothing from Market Watch, and the design principle is that it must
   not: the properties are already correct, **verified, not assumed**. A
   non-empty list means a deselect is genuinely required; only then does the
   hardened release run, and the re-apply goes through the SAME shared
   `ApplySymbolProperties` sequence a fresh create uses (never a second
   partial writer) — **`adopted_reapplied`** with
   `adopt_properties_rewritten: N` (the count that differed).
2. **Bars are replaced and re-proven on every adopt.**
   `CustomRatesDelete(sym, 0, LONG_MAX)`, zero-bar VERIFY, rewrite from the
   fixture, then the UNCHANGED round-trip dataset-hash check against the
   manifest `dataset_hash` — that hash is what earns the PASS.
3. **The release sequence never assumes the close happened.** When a
   deselect IS required: close any OTHER chart on the symbol, then POLL
   until no chart displays it (bounded ≤10 iterations, `Sleep(300)`
   between — ChartClose is asynchronous), then retry
   `SymbolSelect(sym,false)` in its OWN bounded retry (≤5, `Sleep(300)`
   between), return value and `_LastError` checked each time, the LAST
   failure reported.
4. **The script's own chart is never touched.** `ChartSetSymbolPeriod` on
   the chart a script is running on TERMINATES that script — it would kill
   the importer mid-run and produce no JSON at all, which is worse than a
   clean refusal. It is never attempted (stated in-source). If the own chart
   displays the symbol, the verify-first path usually needs no release at
   all; if a release is required and impossible, the refusal is honest and
   names the operator remediation ("close any chart on <sym> in the
   terminal, then re-run the gate").
5. **symbol_state is earned, never aspired to.** gate_run13's refused record
   carried `"symbol_state":"adopted_existing"` although no adoption had
   occurred — the state was set before the path was proven. The field is now
   set ONLY when the named path actually completed:
   `"created_fresh"` (after `CustomSymbolCreate` succeeded) /
   `"adopted_verified"` (survivor reused, zero property writes) /
   `"adopted_reapplied"` (survivor reused, N properties rewritten), plus
   `adopt_properties_rewritten` on the adopt paths; until a path completes
   the record says `"unresolved"`. A refusal reports the state it was in
   when it refused.

`DropCustomSymbolChecked` remains (hardened through the same release helper)
but is CLEANUP-ONLY after a post-create refusal; the pre-create path never
drops a survivor any more. No gate inputs changed — the .set presets are
untouched; every exit path still writes the JSON.

Regression tests: `tests/test_owner_gate_ps1.py` (R10 section: release
closes only foreign charts and never issues ChartSetSymbolPeriod, bounded
chart-close poll, bounded deselect retry reporting the last failure,
cleanup-only drop, three bounded `Sleep(300)` calls only in release+drop,
verify-first precheck mirroring `ApplySymbolProperties` with the CALCULATED
tick values excluded, unchanged round-trip check, 4305 named in the
undeselectable refusal, earned symbol_state ordering, header contract) and
`tests/test_mql5_sources.py` S3 (Sleep stays banned in Experts/+Include/;
the importer's three bounded `Sleep(300)` calls are the only script
exception).

## 2026-09-19 — A symbol left SELECTED by a prior SUCCESSFUL run survives deletion; stage 4 adopts it in place instead of refusing (STAGE 4 R9)

**Trigger.** gate_run12 (on 10ec10a): stage 4 refused at `symbol_state` with
last_error **5306** — "a stale custom symbol named EURUSD.G1 from a prior run
could not be removed (CustomSymbolDelete failed)". This was NOT a regression
from the stage-5 quoting fix; gate_run11 had PASSED stage 4.

**Root cause.** On a SUCCESSFUL import the script deliberately ends with
`SymbolSelect(sym, true)` so the Strategy Tester can see the symbol — and that
final selection is exactly what strands the symbol for the NEXT run.
`DropCustomSymbolChecked()` then (a) called `SymbolSelect(sym,false)` but
DISCARDED its return value and _LastError, and (b) called `CustomSymbolDelete`
immediately, once, with no retry. MT5 releases a symbol ASYNCHRONOUSLY after
deselection, and will not release it at all while a chart is open on it —
hence 5306. The R2 requirement (running the gate twice in a row must produce
identical stage-4 results) was therefore not met: PASS on run N guaranteed a
refusal on run N+1.

**Decision (three-outcome symbol-state contract).**

1. **Deleted-and-recreated.** The drop is hardened: close any OTHER chart
   displaying the symbol (never the script's own chart — closing it would
   kill the script mid-run; an own-chart-on-symbol case is recorded and goes
   straight to adoption, since the symbol can never be deleted in that state
   and refusing would be wrong); deselect with the return value and
   _LastError CHECKED; then a bounded retry — at most 5 attempts with
   `Sleep(300)` between (Sleep is legal in scripts; the event-driven
   EA/include sources remain Sleep-free, and the source test now pins exactly
   that split) — of `CustomRatesDelete` → `ResetLastError` →
   `CustomSymbolDelete` → `SymbolExist` verify. Only a VERIFIED-gone name
   proceeds to `CustomSymbolCreate`. `symbol_state="created_fresh"`.
2. **Adopted-in-place.** When the drop still fails and the survivor IS custom,
   do NOT refuse. Deselect it (must succeed — properties cannot be changed on
   a selected symbol, which is what 5306 means), `CustomRatesDelete(sym, 0,
   LONG_MAX)` and VERIFY zero bars remain (no bar from a prior fixture can
   survive into this dataset), then re-apply EVERY property through the SAME
   one-at-a-time `ApplySymbolProperties` sequence the fresh-create path uses
   (extracted into ONE function called by both paths, so the volume
   MAX→STEP→MIN→LIMIT ordering of R6 cannot drift), and then run the
   UNCHANGED full read-back verification and round-trip dataset-hash check.
   **Why adopt-in-place is as safe as create-fresh:** the gate's guarantee
   never came from the symbol being new — it comes from the evidence the
   symbol must produce: every settable property read back equal to the value
   set, and the round-trip dataset hash equal to the manifest pin. An adopted
   symbol passes only by producing exactly that same evidence; a symbol that
   could not be brought to the certified state still refuses through the
   existing verify/roundtrip stages. `symbol_state="adopted_existing"`, with
   the delete attempts made and the _LastError that forced adoption.
3. **Refused-because-undeselectable.** The one remaining honest refusal: the
   survivor cannot even be DESELECTED, so its properties can never be set.
   The record names the failing call, its _LastError, and the operator
   remediation ("close any chart on <sym> in the terminal, then re-run the
   gate"). Every exit path still writes the JSON.

**Honesty.** Every record (refusal and success) now carries
`symbol_state: "created_fresh" | "adopted_existing"` plus, when adopted,
`adopt_delete_attempts` and `adopt_last_error`; the terminal log prints the
same at adoption time and in the result line. An adopted import is a PASS,
but its evidence can never masquerade as a fresh create.

Regression tests: `tests/test_owner_gate_ps1.py` (R9 section: chart walk
closes only foreign charts, checked deselect, bounded Sleep(300) retry order,
single shared property sequence with the R6 ordering pinned on the call
sites, adoption wipe-and-verify, the undeselectable refusal's remediation,
symbol_state on both writers, three-outcome header) and
`tests/test_mql5_sources.py` S3 (Sleep stays banned in Experts/+Include/; the
importer's single bounded `Sleep(300)` is the only script exception).

## 2026-09-19 — Custom-symbol CALCULATED tick values may read back 0; stage 4 records them as a NAMED limitation and PASSES, never blocks (STAGE 4 R8)

**Trigger.** gate_run10 (on 63f2faa): currencies now correct (USD/EUR/EUR all
read back OK) and all 16 SETTABLE properties verified. The remaining blocker
was `verify_properties`: `SYMBOL_TRADE_TICK_VALUE_PROFIT` read back
`0.0000000000` (manifest `1.0`) while the SETTABLE `SYMBOL_TRADE_TICK_VALUE`
read back `1.0` correctly; `trade_calc_mode = 0` (Forex). The importer was
refusing on that derived divergence (the R5 rule).

**What the MQL5 docs say (looked up, not assumed).** `ENUM_SYMBOL_INFO_DOUBLE`
documents `SYMBOL_TRADE_TICK_VALUE_PROFIT`/`_LOSS` as the **"Calculated** tick
price for a profitable/losing position" and `SYMBOL_TRADE_TICK_VALUE` as the
settable "Value of SYMBOL_TRADE_TICK_VALUE_PROFIT". The calculated pair is
derived lazily from a pricing/quote context and the account-currency
conversion for the calc mode. A freshly built **Forex** custom symbol that
carries only OHLC bars (no ticks, no cross-rate feed to the account currency)
has nothing to derive from, so it legitimately reads back 0 — even after
`SymbolSelect(true)` and `CustomRatesUpdate`. (The public docs do not promise
these populate for a bars-only custom symbol; the importer now reads them
after selection + bars with a bounded, Sleep-free retry that nudges a
recompute, and takes the value the moment it becomes non-zero.)

**Decision.** The derived tick values are **NON-AUTHORITATIVE for stage 4**.
Applying the scope decision already recorded for R5: the Gold legs certify
STRATEGY LOGIC and EXECUTION PATH on the fixture, NOT broker tick-value
economics — those are certified separately by stage-3 broker parity + the
independent OrderCalcProfit witness in RiskManager. So:

- `Mql5BotImportFixture.mq5` reads the calculated `_PROFIT`/`_LOSS` back (after
  selection + bars, bounded retry) and RECORDS them in `derived_tick_values`
  with `available` + `ok` per property and an `authoritative:false` +
  named-limitation block — but NEVER refuses on them (the R5 economics
  refusal is removed). The SETTABLE read-back (16 properties) stays STRICT
  and still fails closed on any divergence.
- `gate_selfcheck.properties_verified` requires both calculated enums to be
  PRESENT (transparency, never silently skipped) but does NOT gate on their
  `ok`; when they are unavailable/divergent it PASSES with `limited:true` and
  a reason that NAMES the limitation, surfaced in the stage-4 message. Never a
  silent pass; never an over-strict block that refuses a symbol whose
  economics a stronger gate already certifies.

Recorded in `docs/OWNER_DELIVERY.md` (custom-symbol row + the tick-value
limitation line). See the R5 tick-value entry below for the origin of the
scope decision.

## 2026-09-19 — Custom-symbol currencies are inferred from the NAME; a SetString can report success without taking effect; name the symbol XXXYYY+suffix (STAGE 4 R7)

**Trigger.** gate_run9: 13 properties (incl. the whole volume family, R6)
set OK, then `verify_properties` refused. The read-back named the cause:
`SYMBOL_CURRENCY_PROFIT` expected `USD` read back `D1_`; `SYMBOL_CURRENCY_BASE`
expected `EUR` read back `GOL`. `GOL` and `D1_` are the first and second
three-character chunks of the symbol name `GOLD1_EURUSD`. The
`CustomSymbolSetString` calls had returned `ok=true`, `last_error=0` but did
not take effect. (`SYMBOL_CURRENCY_MARGIN` was NOT in the divergence list —
verify records every divergence without short-circuit — so margin stuck
correctly at `EUR`; only base/profit were overridden.)

**What the MQL5 documentation says (looked up, not assumed).**

- MQL5 book, "Custom symbol properties"
  (`book/advanced/custom_symbols/custom_symbols_properties`): "Immediately
  after the creation of an 'empty' symbol, it is by default considered a
  Forex symbol, and therefore these [currency] properties cannot be set for
  it without first changing the market." "If you do not change
  `SYMBOL_TRADE_CALC_MODE` to another required mode in advance, substrings of
  the specified symbol name (the first and second triple of symbols) will
  automatically fall into the properties of the base currency
  (`SYMBOL_CURRENCY_BASE`) and profit currency (`SYMBOL_CURRENCY_PROFIT`).
  For example, if you specify the name 'Dummy', it will be split into 2
  pseudo-currencies 'Dum' and 'my'." Forex symbols follow "the form XXXYYY
  (where XXX and YYY are currency codes) plus an optional suffix."
- `CustomSymbolSetString` (`docs/customsymbols/customsymbolsetstring`) does
  not warn about this and the call returns `true` — matching gate_run9,
  where the set reported success while the value was silently overridden.

Conclusion: **MT5 infers a custom symbol's base/profit currencies from the
name in the default Forex calc mode, and `CustomSymbolSetString` for those
properties can return success without taking effect.**

**Decision.** Take the simplest fix that survives the docs and keeps the
symbol a genuine Forex instrument: NAME each gold in the documented
XXXYYY+suffix Forex form so MT5's own inference is correct by construction.
`GOLD1_EURUSD`/`GOLD2_EURUSD` → `EURUSD.G1`/`EURUSD.G2` (first six chars
`EURUSD` → base `EUR`, profit `USD`; the `.G1`/`.G2` suffix keeps each unique
and non-colliding with the broker's own `EURUSD`, and is valid per MT5's
name rule of Latin letters/digits and only `. _ & #`, ≤31 chars). Changing
`SYMBOL_TRADE_CALC_MODE` to a non-Forex mode WOULD let SetString stick, but
EURUSD genuinely IS Forex, so that would corrupt the margin/profit
calculation — rejected.

The importer keeps the currency `CustomSymbolSetString` calls (harmless for a
Forex symbol, honoured on a non-Forex one) but treats them as non-
authoritative: correctness for base/profit comes from the NAME and is PROVEN
by the existing `verify_properties` read-back, never assumed. The read-back
was NOT weakened — it is what caught this. Every prior guarantee holds:
per-property success check, named failure, full read-back, fail-closed.

**Threaded consistently.** `tools/owner_gate.ps1` (`$golds`, `$symbolByGold`),
the importer default `InpSymbolName`, the `*.set` preset value, the
`InpOutFile`/result/evidence filenames (all derived from `$g.name`), and a
new regression test (`test_r7_symbol_names_are_forex_xxxyyy_form_for_currency_inference`).
Manifest `broker_spec.name` was already `EURUSD` (metadata; the importer
takes the symbol only from `InpSymbolName`). See the R5 tick-value entry
below for the sibling "set-call rejected/ignored" pattern.

## 2026-09-19 — Custom-symbol tick values: MT5 will not store them; certify by derived-equality read-back, refuse on divergence (STAGE 4 R5)

**Trigger.** gate_run7: `CustomSymbolSetDouble(SYMBOL_TRADE_TICK_VALUE_PROFIT
= 1.0 from manifest.broker_spec.tick_value_profit)` failed with
`last_error 5307`, after `SYMBOL_DIGITS`, `SYMBOL_POINT`,
`SYMBOL_TRADE_TICK_SIZE` and `SYMBOL_TRADE_TICK_VALUE` all succeeded.

**What the MQL5 documentation says (looked up, not assumed).**

- Runtime Errors table (`docs/constants/errorswarnings/errorcodes`):
  `5307 ERR_CUSTOM_SYMBOL_PROPERTY_WRONG` — "An invalid custom symbol
  property". (Distinct from `5308 ERR_CUSTOM_SYMBOL_PARAMETER_ERROR` — "A
  wrong parameter while setting the property" — so 5307 rejects the
  PROPERTY, not the value.)
- MQL5 book, "Custom symbol properties": "not all properties are allowed to
  change. When trying to set a read-only property, we get the error
  CUSTOM_SYMBOL_PROPERTY_WRONG (5307)."
- `ENUM_SYMBOL_INFO_DOUBLE` (`docs/constants/environment_state/
  marketinfoconstants`): `SYMBOL_TRADE_TICK_VALUE_PROFIT` — "**Calculated**
  tick price for a profitable position"; `SYMBOL_TRADE_TICK_VALUE_LOSS` —
  "**Calculated** tick price for a losing position";
  `SYMBOL_TRADE_TICK_VALUE` — "Value of SYMBOL_TRADE_TICK_VALUE_PROFIT".
- `CustomSymbolSetDouble` (`docs/customsymbols/customsymbolsetdouble`) names
  `SYMBOL_TRADE_TICK_VALUE` (with `SYMBOL_POINT`, `SYMBOL_TRADE_TICK_SIZE`)
  in its history-reset note, i.e. it IS a settable custom-symbol property —
  matching gate_run7, where setting it succeeded.

Conclusion: the two `_PROFIT`/`_LOSS` properties are terminal-DERIVED, not
settable storage. MT5 will not let a custom symbol *carry* the broker's
tick-value economics as stored fields.

**Decision (design, not suppression).** `tick_value_loss` underpins the
P0-1 sizing correction, so a tester leg on the imported symbol reproduces
broker sizing ONLY if the terminal's DERIVED tick values equal the broker's.
Therefore `Mql5BotImportFixture.mq5`:

1. never calls `CustomSymbolSet*` on `SYMBOL_TRADE_TICK_VALUE_PROFIT` /
   `SYMBOL_TRADE_TICK_VALUE_LOSS` (a call documented to fail must not be
   issued and its failure must not be swallowed);
2. still sets `SYMBOL_TRADE_TICK_VALUE` from `manifest.broker_spec.
   tick_value_profit` (settable; "Value of SYMBOL_TRADE_TICK_VALUE_PROFIT");
3. after all sets + bars, READS BACK every set property
   (`SymbolInfoInteger/Double/String`) and compares to the value set —
   ANY divergence refuses at the new `verify_properties` stage;
4. reads back the terminal-DERIVED `_PROFIT`/`_LOSS` (plus
   `SYMBOL_TRADE_CALC_MODE`, the derivation basis) and REFUSES unless both
   equal the manifest broker values. The result JSON records all of it:
   `verified_properties` + `derived_tick_values` (a NAMED, SCOPED
   limitation: proven by derived-equality at import time, never by storage).

The committed classifier (`gate_selfcheck.properties_verified`, new stage-4
case `properties_unverified`) fails a success record CLOSED unless the
read-back proof is present and clean — a skipped property can never again
pass silently as if it were set.

**Stage-8 reconciliation scope (what the Gold legs can and cannot
certify).** Recorded in `artifacts/owner_mt5_gate/README.md`: the Gold legs
certify tick-value economics ONLY via the import-time derived-equality
proof; they cannot certify the broker's *stored* `_PROFIT`/`_LOSS` fields
(MT5 has no such storage for custom symbols), and the derived values are a
function of calc mode/contract/tick size/account currency, re-derived by the
tester at run time. If the derived-equality proof is absent or diverged,
stage 4 refuses and no tick-value claim survives to stage 8.

## 2026-09-18 — Re-anchor frozen source to `a85cba3` + ancestry-based stage 0

**Trigger.** The owner gate stopped at stage 0 with
`SELF_PROTECT_HEAD_MISMATCH: HEAD a85cba3 != frozen source.commit 227bf66`.
The check was right to exist but wrong as written, and the anchor was stale:
`227bf66` predates the generic DSL runtime (`92b3102`), the reserved-word
compile fix and the P0-1 sizing fix (`4257f1e`), so it can never be the
commit the owner runs.

**1 — Re-anchor (provenance only).** `artifacts/owner_mt5_gate/frozen_inputs.json`
`source.commit` moves `227bf66` → `a85cba3`. The `source.note` keeps the full
anchor history (`781bea4 → 54613aa → 52cbaa5 → 227bf66 → a85cba3`) and appends
the reason: **superseded by newer work**, authorised by the owner-observed
strict compile 0 errors / 0 warnings on `4257f1e` plus 14/14 DSL parity
(EXACT + tampered refused), both recorded on branch `windows/evidence-4257f1e`.
Every fixture / config / dataset / manifest / spec hash below the anchor stays
pinned UNCHANGED — this re-anchors provenance only, never an artifact
(`git diff <anchor> HEAD -- artifacts/gold artifacts/gold_2` is empty).

**2 — Stage-0 semantics: relate HEAD to the anchor by ANCESTRY, not string
equality** (`gate_selfcheck.verify_head_matches_frozen`). What certification
rests on is that the frozen ARTIFACTS are byte-unchanged and the tree is
clean, not that `HEAD` equals one historical SHA. New rules:

- `HEAD == anchor` → PASS (exact).
- anchor is an ancestor of `HEAD` (a clean newer commit) → PASS with a
  recorded NOTE (`SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR`); the run records both
  `head` and `anchor` and prints the note, and does **not** abort.
- any frozen artifact hash mismatch → FAIL (`SELF_PROTECT_FROZEN_HASH_MISMATCH`,
  unchanged).
- dirty tree / `core.autocrlf=true|input` / missing binaries → FAIL (unchanged).
- `HEAD` older than the anchor, diverged from it, or an anchor absent from
  the clone → FAIL (`SELF_PROTECT_HEAD_MISMATCH`, with a precise `detail`).

Regressions (`tests/test_owner_gate_ps1.py`, all non-vacuous): a newer clean
commit passes with the note (`test_head_newer_than_anchor_passes_with_note`,
`test_run_self_protection_passes_when_head_descends_from_anchor`); an older
HEAD fails (`test_head_older_than_anchor_fails`); a diverged HEAD fails
(`test_head_diverged_from_anchor_fails`); an unknown anchor fails
(`test_head_unknown_anchor_fails`); a tampered frozen artifact still fails
closed even when HEAD descends cleanly
(`test_run_self_protection_still_aborts_on_tampered_frozen_artifact`); a dirty
tree still fails (`test_run_self_protection_still_aborts_on_dirty_tree`).

**3 — Fresh-clone target preflight** (`gate_selfcheck.clone_target_status`,
`owner_gate_decide.py clone-preflight`, `owner_gate.ps1 -CloneInto`). The
owner's real-world snag: the intended clean-room clone directory already
existed, so `git clone` failed deep in its own machinery and left the owner
to move directories by hand. `owner_gate.ps1 -CloneInto <dir>` now refuses by
name up front (`SELF_PROTECT_CLONE_TARGET_EXISTS`, naming the full path) when
the target exists non-empty, and treats an absent or empty directory as safe.
Regressions: `test_clone_target_missing_is_safe`, `_empty_dir_is_safe`,
`_nonempty_dir_refused_by_name`, `_existing_file_refused`.

No MT5 / tester / compile / broker / certification claim is made here — this
is verifier and provenance correctness only; the outcomes above are produced
only when the owner runs the gate on a real terminal.

## 2026-09-18 — Audit-and-close wave: sizing denomination + DSL hardening

**Supersedes** the 2026-09-16 "Wave 1 — tick-value denomination stays
owner-gated" DEFER decision below. That entry deferred the fix because
`data/broker_exports/` then held **no owner export** (`n_exports: 0`, every
asset class PENDING), so the ACCOUNT_CURRENCY vs PROFIT_CURRENCY question
could not be attested on this host. The trigger has now landed: the
committed owner evidence `artifacts/owner_mt5_gate/broker_parity.json`
renders `tick_value_denomination = ACCOUNT_CURRENCY` (status MATCH, against
an independent `OrderCalcProfit` witness) for EURUSD, US30 and XAUEUR (BTC
UNVERIFIED/PENDING). Acting on that committed artifact — not on numbers
quoted in a directive — resolves the owner-gated open item and authorises
the runtime-semantics change recorded here.

**HOTFIX — compile blocker (this commit).** The owner's strict compile of
the prior commit `92b3102` ("Integrate generic DSL runtime into `mql5/`…")
**FAILED** — 11 errors, the first being
`DslBundle.mqh(133,14): error 149: unexpected token`. Cause: `input` is an
MQL5 reserved keyword and was used as a local variable name in
`CDslBundleLoader::DeriveSpecHash`. Fix: rename the local to `payload` (at
its declaration and the `DslSha256Hex(...)` call). To keep this class of
break from returning, a source-structure guard
(`tests/test_mql5_dsl_runtime_source.py::
test_no_mql5_reserved_word_declared_as_identifier`) now fails if any MQL5
reserved word is declared as a variable/parameter name anywhere under
`mql5/`; it is proven non-vacuous by
`test_reserved_word_guard_is_not_vacuous` (it flags the exact original
pattern while leaving legitimate `const`/`new`/`delete`/`return` uses
alone). No MT5/tester/broker/parity claim is made — this is the commit the
owner should compile; `92b3102` must not be used as the compile-of-record.

**P0-1 — tick-value denomination.** Owner MT5 evidence
(`artifacts/owner_mt5_gate/broker_parity.json`) establishes that the
terminal denominates `SYMBOL_TRADE_TICK_VALUE_LOSS` in the ACCOUNT/DEPOSIT
currency (verdict `ACCOUNT_CURRENCY` for EURUSD, US30, XAUEUR — note XAUEUR
has profit currency EUR yet its tick value is account-denominated; BTC
UNVERIFIED/PENDING). The prior `profit_to_deposit` FX factor in the
loss-per-lot path was therefore a double-conversion bug. Decision:

1. **No FX factor in loss-per-lot, and no FX rate is ever derived from a
   tick value.** Removed the `profit_to_deposit` multiply from the
   loss-per-lot path in Python (`symbolspec.loss_per_lot`, `sizer.size_position`,
   `engine`) and MQL5 (`SymbolSpec.SpecLossPerLot`, `RiskManager.GetLots`
   and `RiskMoneyAt`). `RiskManager.ProfitToDeposit` (the FX-quote helper)
   is deleted. Loss per lot = `ticks × tick_value_loss`, account-denominated.
2. **Independent runtime witness (MQL5).** `RiskManager.GetLots` now
   reconciles the tick-value loss against an independent
   `OrderCalcProfit` witness (P/L of a 1.0-lot position closed at the
   min-stop-enforced stop, always in the account currency): it sizes on
   `max(tick-value loss, witness)`, and VETOES the trade ("denomination
   unverified") when the witness fails or the two disagree by > 1%. This is
   the runtime equivalent of the offline denomination gate; it never
   invents an FX rate.
3. **USDJPY synthetic fixture re-denominated (owner-pending).** The only
   multi-currency synthetic fixture, USDJPY (profit JPY), had a
   JPY-denominated tick value (`tick_value_loss=100`) plus a 1/150
   conversion. Under account denomination the fixture is corrected to
   `tick_value_loss=100/150` (account/deposit USD), which is
   output-preserving (old `100 × 1/150` == new value). USDJPY is OUTSIDE
   the owner's 3-symbol evidence, so this re-denomination is flagged
   owner-pending. The `profit→deposit` conversion is banished from both
   sizing and PnL accounting; `synthetic_profit_to_deposit` and the meta
   `conversion` telemetry are retained as descriptive metadata only.
4. **Parity tolerance.** `sizer.loss_per_lot` in the broker-parity harness
   compares the exported (rounded, printed-precision)
   `SYMBOL_TRADE_TICK_VALUE_LOSS` against the full-precision
   `OrderCalcProfit` witness inside the SAME 1% denomination band the
   runtime enforces (e.g. EURUSD 21.685 vs 21.665 = 0.09%); a tighter bound
   reported the broker's own tick-value rounding as a false MISMATCH.

**DSL hardening (same wave).** P0-3: the EA reads the bundle as raw bytes
(`FILE_BIN`) and refuses (`INIT_FAILED`) when the bundle's declared
market/timeframe does not match the chart (`DslBundle.MarketMatches` now
wired); `bundle_hash` remains SHA256-verified over the canonical envelope
(`DslCanon`) and refuses on mismatch. P1-1: warmup contract — refuse when
`InpDslBars < 10 × longest indicator period`. P1-4: SL/TP ATR uses the
canonical period-14 Wilder ATR (matching the Python engine's fixed exit
ATR in period AND seeding, never `iATR`), and the bundle's
`trail_atr`/`breakeven_atr`/`time_bars` drive `PositionGuard` when DSL mode
is on. P1-5: when the DSL desired position is 0 while a position is open the
EA CLOSES it, matching the Python canonical engine default
(`allow_signal_exit=True`); pinned by `tests/test_engine.py` (Python) and
`tests/test_mql5_sources.py` (MQL5 source structure). MQL5 sources are NEW
and require an owner recompile; parity/certification remain owner-pending.

---

## 2026-09-18 — Generic DSL runtime INTEGRATED into `mql5/` (anchor break)

**Purpose.** Promote the staged generic DSL runtime from
`mql5_dsl_runtime/` into the certified EA tree so a strategy runs as DATA
(not one of the five enums) on the compile-of-record path, and land the
Windows-observed integration on `master` as one commit.

**What changed (all in `mql5/`, so the frozen anchor `227bf66` no longer
equals HEAD — deliberate, see below).**
- New includes `mql5/Include/Mql5Bot/Dsl{Json,Canon,Bundle,Indicators,
  Runtime,Series,Execution}.mqh` and the batch parity runner
  `mql5/Scripts/Mql5Bot/DslParityRunner.mq5`. The old `mql5_dsl_runtime/`
  staging tree is reduced to a pointer README.
- `DslBundle` does REAL `bundle_hash`/`spec_hash`/`semantic_hash`
  re-derivation (canonical JSON + `CryptEncode` SHA-256) and refuses any
  mismatch; a committed `artifacts/dsl_parity/tampered_bundle/` negative
  fixture exercises the refusal on both engines.
- Supported indicator kinds are trimmed to exactly what the committed
  fixtures need — `EMA/RSI/ATR` + canonical `DONCHIAN/HIGHEST/LOWEST` —
  pinned by `MQL5_STAGED_RUNTIME_KINDS`; everything else fails closed.
  Filters implement `trading_days`/`session`/`cooldown`; `max_spread_points`
  / `max_atr_pct` / `regime.forbidden` refuse (no verified fixture yet).
- The parity runner consumes ONLY the committed `ohlc.csv` bytes (no
  CopyRates / live history) and computes indicators with the SAME canonical
  array ports the EA path uses (`DslSeries.mqh`), so seeding matches
  `python/mql5bot/indicators.py` — not `iMA/iRSI/iATR`.
- Tooling: `tools/compare_dsl_parity.py` (exact 14/14 comparator + tampered
  refusal) and `tools/run_dsl_parity.ps1` (stage → `terminal64.exe
  /config` startup-script → collect → sha256 manifest → comparator).
- The RiskManager `OrderCalcMargin` direction fix (`price > slPrice`) is now
  applied in-tree (was staged as an owner patch).
- Repo hygiene: `.gitattributes` pins byte-exact artifacts (`artifacts/**`,
  `*.csv`, `*.json` as `-text`; `*.mq5`/`*.mqh` as `eol=lf`) so manifests
  hash identically on every OS; `.gitignore` `data/` → `/data/` so the
  committed `tests/data/real/*` fixtures survive a fresh clone.

**Anchor / provenance.** This breaks `git diff 227bf66 HEAD -- mql5/`
(previously empty). The integration is **compile-observed on Windows, not
compile-of-record**: `frozen_inputs.json` `source.commit` stays `227bf66`
until the owner runs `tools/compile.ps1 -Strict` on this HEAD and
`tools/run_dsl_parity.ps1` reports 14/14 EXACT, then re-anchors per the
documented procedure (`docs/WINDOWS_OWNER_HANDOFF.md` §8, "Re-anchor
procedure"). No parity/tester/certification claim is made here; the golds,
manifests and five-engine semantics are unchanged by this integration.

---

## 2026-09-17 — Continuation: truthful gate-5 WFE + bundle-size fail-closed

**Purpose.** Close two residual gaps found in a second independent audit of
the closure wave. Mac-side only; frozen `mql5/` anchor `227bf66` untouched;
no gate weakened.

**G7 — gate-5 "walk-forward efficiency" was a misleading name.** The gate
`gate5_walk_forward` (literally "walk-forward efficiency", `factory/gates.py`
Gate-5) was fed `cv_pf − train_pf` from `discovery/research_service.py` — a
profit-factor DELTA between two in-sample sub-slices, with no out-of-sample
leg and no return ratio. The authoritative contract (`docs/WFA_CONTRACT.md`
§6) defines WFE = `OOS_return / IS_return`, implemented in
`optimizer.walk_forward` (`optimizer.py:291-295`). Per the mission's WFA-
semantics P0 ("implement the correct WFE OR rename; never keep a misleading
certification metric name") we chose to IMPLEMENT the correct metric rather
than rename — this both fixes the name and completes the chain's WFA stage
without weakening the gate.

*Design.* A new canonical helper `discovery/research_metrics.walk_forward_efficiency`
computes the contract ratio (`holdout_return / IS_return`) with the exact
formula `optimizer.walk_forward` uses, applied to ONE rolling-origin window
whose train and held-out slices are BOTH inside the research IS region — so
the final one-look OOS certification slice (§19) is never touched and the
measurement stays selection-safe. When the IS leg is non-positive the ratio
is undefined and the helper returns `None`; the service then leaves the gate
input UNSET so gate-5 SKIPs (blocks) rather than passing on an invented
value. `optimizer.walk_forward` itself is NOT reusable directly on the DSL
grid path (it drives registered engine strategies + param grids, not DSL
`desired_positions` signals), so the single-window contract formula is
applied in one place (`research_metrics`) to avoid a second WFA engine while
keeping the numeric definition identical to the authoritative one. The
mislabeled selection key `is_pf` (actually the CV-slice PF) is renamed
`sel_pf`. Regression: `tests/test_research_service_truthful.py` (+3, incl. a
source guard that `cv_pf - train_pf` never returns).

**G8 — bundle total-size limit was file-path-only.** `validate_document_size`
(256 KiB) was called only in `dsl/parse.py:load_document` (file reads); an
already-parsed dict reaching `dsl/bundle.py:load_bundle` (or `parse_spec(dict)`)
skipped it. A bundle is untrusted data, so `load_bundle` now validates
`canon_json(envelope)` size FIRST and fails closed (`BundleError`) before any
structural work. The staged MQL5 loader (`mql5_dsl_runtime/Include/DslBundle.mqh`,
OWNER-PENDING/uncompiled) now also matches the market **timeframe** (Python
compares symbol AND timeframe), and its header truthfully enumerates which
refusals are MIRRORED vs OWNER-PENDING (bundle_hash re-derivation needs the
canonical re-serializer — the one documented owner-completion point).
Regression: `tests/test_dsl_bundle.py::test_oversized_bundle_is_rejected_on_in_memory_path`.

---

## 2026-09-17 — Final closure wave: research-service truthfulness (no fabricated PASS)

**Purpose.** Close the mission's first P0 — the research service injected
FABRICATED gate inputs that forced passes regardless of the strategy. Fixed
Mac-side; frozen `mql5/` anchor `227bf66` untouched. New canonical module
`python/mql5bot/discovery/research_metrics.py`; regression
`tests/test_research_service_truthful.py`.

**Fabricated metrics removed — every gate input is now MEASURED.**
`discovery/research_service.py` used to hard-code `pbo=0.0`,
`positive_in_expected_regime=True`, `max_correlation_with_book=0.0`,
`marginal_heat_add=0.0`, and the score's `cpcv_pbo_evidence=0.1`. Because the
gate engine is fail-closed (a missing input SKIPs → blocks), those constants
were the ONLY thing manufacturing a pass on the searched grid. Now:
- **PBO** is measured across the searched grid via
  `robustness.combinatorial_purged_cv` (the service DOES select among variants,
  so the search's overfitting is real — a marginal-edge grid measures PBO≈1.0
  and is correctly rejected; the old `0.0` hid this). When the search is too
  small to estimate (fewer than 2 configs / 8 periods) PBO is left UNSET →
  gate-6 SKIPs, never a fake 0.0.
- **`positive_in_expected_regime`** is measured by `research_metrics.regime_pf`
  (profit factor of trades exiting inside a causal 200-SMA-rising regime),
  the SAME calculation the certified E2E (`tests/test_factory_e2e.py`) uses.
- **DSR leg** uses the canonical closed form `robustness.psr` on daily returns.
- **Portfolio interaction** (`max_correlation_with_book`, `marginal_heat_add`)
  is measured against the ACTUAL book; an empty book (a strategy researched in
  isolation) is the honest 0.0, a non-empty book yields real correlation/heat.
- **Score `cpcv_pbo_evidence`** is derived from the measured PBO (`1 − PBO`),
  never a constant.

**Candidate identity (§19).** The grid search is now a pre-registration
SELECTION step (IS/CV metrics only); evidence is bound to the SELECTED
variant's own `spec_hash` — never to a base spec that was not the one measured.
The old code recorded every variant's evidence against the base hash.

**One-look OOS / ACCEPT-REJECT.** Selection uses IS/CV only; the SELECTED
candidate then takes exactly ONE OOS look (after selection, never feeding it).
Promotion requires the full IS gate ladder to PASS *and* the OOS to confirm; a
candidate failing any gate is recorded truthfully and REJECTED — the chain
always renders an evidence-based verdict (the system discarding a weak strategy
is the design, not a bug). A FAILED robustness/backtest record can never
promote (store boundary §28.15, re-pinned).

**WFE naming.** The `wfe` gate input is a walk-forward *profit-factor* metric
(IS-internal CV_PF − train_PF in the service; OOS_PF − IS_PF in the E2E
fixture, documented in `factory/gates.fixture.yaml`). It is NOT the
return-ratio walk-forward efficiency of `optimizer.walk_forward`. The name is
retained (it IS a walk-forward efficiency measure and is used consistently as
the gate-5 key across the suite); the two conventions are recorded here rather
than renamed, so the certification vocabulary stays stable. No gate weakened.

**Anti-duplication.** The measured-metric helpers now live once in
`discovery/research_metrics.py` (delegating heavy stats to `robustness`),
instead of being copied between the service and the test fixtures.

---

## 2026-09-17 — Convergence pass: generic DSL execution, market truthfulness, indicator status

**Purpose.** Close the central DSL→MQL5 convergence gap (§8) and the
interpreter market-guess bug (§6), Mac-side, without touching the frozen
`mql5/` anchor `227bf66` (chosen: staged / anchor-preserving). Full report:
`docs/AEGIS_CONVERGENCE_AUDIT_2026-09.md`.

**§6 — interpreter never guesses the market.** `factory/interpreter.py` used
to hard-code `market={"symbol":"EURUSD","timeframe":"H1"}` while its own
`assumptions[]` said the market must be owner-chosen. Fixed: the market is an
explicit owner input or stays UNRESOLVED (empty) and is recorded as a blocking
ambiguity. Schema is now version-aware — a v0 draft may carry an unresolved
market, but an executable version (>0) MUST specify a real symbol + timeframe
(`schema.py`), so a guess can never reach a runtime. Threaded through
`normalize.py`/`parse.py`, `discovery/research_service.run_idea(market=…)`
(fail-closed), the factory CLI (`--symbol/--timeframe`) and the API
`/campaigns` (422 when a runner is attached and no market is given).
Regression: `tests/test_interpreter_market.py` (+ updates to intake/e2e/cli/
master_convergence/api tests to make the market explicit at the executable
boundary).

**§7.8 — indicator `mql5_status` truthfulness.** All 71 registry kinds
defaulted to `mql5_status="parity-tested"`, but by the registry's own
definition that requires an existing MQL5 port — false for 65+ kinds, and no
owner MT5 parity exists (REALITY_GATE_BLOCKED). Fixed the default to the
truthful `canonical-defined` (MQL5 pending owner compile; never parity-proven).
Regression: `tests/test_indicator_mql5_status_truthful.py`.

**§29.1 — normalized-document idempotency.** `normalize.py` floatifies numeric
leaves but the schema strictly required int for `rising/falling` `n` and
`filters.cooldown_bars`, so those normalized docs failed re-parse (breaking
bundle carry + DB reconstruct for such specs). Fixed both schema checks to use
`_as_int` (tolerant of integral floats, as `period`/`time_bars` already were).
Regression in `tests/test_dsl_bundle.py`.

**§8–§14 — generic execution, staged.** Added the immutable, hash-bound
**executable bundle** (`python/mql5bot/dsl/bundle.py`) both runtimes read, with
a fail-closed loader (unsupported version, hash mismatch, missing identity,
ambiguity, contract drift, unsupported kind → refuse). Added the cross-engine
**parity contract** (`python/mql5bot/dsl/parity.py`) + a 14-fixture golden set
(`artifacts/dsl_parity/`, generator `tools/build_dsl_parity_golden.py`) proving
the canonical `EMA20×EMA50 ∧ RSI14>55, SL 2ATR/TP 3ATR` runs generically —
never mapped to one of the five enums. The generic **MQL5 runtime is STAGED**
in `mql5_dsl_runtime/` (OWNER-PENDING/UNCOMPILED; JSON reader, loader,
evaluator, parity runner) — it lives OUTSIDE `mql5/` so the frozen anchor stays
byte-identical; the owner integrates + re-anchors.

**§26 — RiskManager:296.** The inverted `OrderCalcMargin` direction fix ships
as `owner_patches/RiskManager_296_direction.patch` (git-apply-clean, NOT
applied to the frozen tree). Regression: `tests/test_riskmanager_direction_patch.py`.

**Invariants preserved.** `git diff 227bf66 HEAD -- mql5/` still empty; five
legacy engines intact; authority model unchanged; no gate weakened; no frozen
gold/owner_mt5_gate artifact regenerated; no MT5/compile/parity evidence
fabricated (all such claims remain OWNER-PENDING).

---

## 2026-09-16 — Wave 2.3 final Mac release-candidate audit: determinism + fail-closed hardening

**Purpose.** Independent adversarial re-audit of the whole tree (security,
financial correctness, research/determinism, certification tooling, discovery/
authority boundaries) to reach a true Mac release-candidate state where the only
remaining work is owner Windows/MT5 execution + evidence. No features, no
weakened gate. Full detail of what was found vs. cleared below.

**P1 — nondeterministic one-look OOS config selection (`pipeline.py`).** The
purged-CV "most-selected" config used `max(set(selected_hashes),
key=...count)`; `set` iteration over hex strings is `PYTHONHASHSEED`-salted, so
on a tie in selection count the winner (and therefore the params handed to the
irreplaceable one-look OOS certification, AND `RunManifest.manifest_id`, which
hashes the artifacts) differed across processes for identical inputs. Fixed:
extracted `_most_selected()` — `max(sorted(set(...)), key=count)` — ties resolve
to the smallest hash (matching the existing IS argmax tie-break). Regression:
`test_most_selected_tie_break_is_deterministic`; verified by running the full
suite under two `PYTHONHASHSEED` values with identical results.

**P1 — owner-gate reconciliation accepted a python-only package
(`owner_gate.verify_reconciliation`).** `_field_divergent` treats a field with
no `mt5` key (or `mt5` null) as NON-divergent, so a reconciliation carrying a
`python` column but no MT5 side at all — one never actually run on MT5 —
reached `first_divergence==None` → MATCH → VALID → fed `MT5_VALIDATED`. (The
`certify_strategy` lane already required a real MT5 observation; the owner-gate
lane, which issues the verdict, did not.) Fixed: a completeness gate now
requires every reconciled field (a dict carrying `python`) to also carry a
non-null `mt5`, and at least one such field to exist; incompleteness → INVALID,
fail-closed. Regressions: `test_reconciliation_python_only_package_fails_closed`,
`test_reconciliation_null_mt5_side_fails_closed`.

**P2 — owner-gate frozen SYMBOL identity was never enforced
(`owner_gate.verify_symbolspec`).** The frozen broker_spec names the symbol
under `name`, the SymbolSpec doc under `symbol`, so `doc.get("name")` was always
None → `UNSUPPORTED_BROKER_DIFFERENCE` → silently ignored; a leg run on the
WRONG symbol whose decision numerics coincide would pass identity, and any
future owner-supplied `name` expectation would be a no-op. Fixed: `name`→`symbol`
field translation + symbol identity treated as decision-changing (STOP).
Regression: `test_symbolspec_frozen_symbol_name_is_enforced`. (Currently latent:
the committed `symbolspec_expectations` is `None` and the test set omits `name`,
so no in-repo verdict changes — this hardens the machinery for when the owner
populates it.)

**P2 — `broker_symbol_parity.py` machine gate failed OPEN when nothing was
verified.** `main()` returned 0 whenever no row was a MISMATCH, so "no export
present" and "every export malformed/skipped" both read as PASS to a CI/owner
gate keying on exit status (only the markdown said NOT VERIFIED). Fixed to fail
closed: exit 1 = real MISMATCH, exit 2 = nothing/incomplete verified (no
exports or a class still PENDING), 0 only when exports present + every class
covered + no mismatch. Regression:
`test_main_exit_code_fails_closed_when_nothing_verified`. Also: the
`sizer.round_to_tick` parity row hard-coded `"MATCH"` regardless of the computed
value (a check that could never fail) — replaced with a real on-grid
idempotency comparison that can report MISMATCH.

**P2 — Python sizer did not fail-closed on non-finite inputs (`sizer.py`).**
`size_position` validated `< 0` but not finiteness: NaN slipped every comparison
and crashed in `normalize_volume` (ValueError, not a clean veto), and +Inf
equity inflated the budget past the cap and returned a tradable clamped size
(fail-OPEN) — contradicting the SPEC §8.C invariant "NaN/Inf must VETO". Fixed:
explicit `isfinite` veto on all numeric inputs → `INVALID_ARGS`. (Engine callers
pre-validate finiteness, so this is a canonical-library contract hardening, not
a live-path breach.) Regression: `test_non_finite_inputs_fail_closed`.

**P3 — Python Kelly cap was caller-overridable above the ceiling (`sizer.py`).**
`kelly_cap` had no hard ceiling, so a caller passing `kelly_cap=1.0` got full
Kelly, diverging from MQL5's hard `#define KELLY_CAP 0.25` + `MathMin(k,
KELLY_CAP)`. Added `KELLY_HARD_CAP = 0.25` and `min(k, kelly_cap,
KELLY_HARD_CAP)` so the two ports cannot diverge on the risk ceiling. Regression:
`test_kelly_caller_cap_cannot_exceed_hard_ceiling`.

**Lint — `tools/` ruff debt cleared.** The two files documented as pre-existing
ruff debt (`tools/meta_real_basket.py` unused `sys` + import sort;
`tools/meta_regime_matrix.py` import sort, redundant `int()`, three
line-wrapped implicit string concatenations) are fixed. `ruff check python/
tests/ tools/ factory/` is now clean (was `python/ tests/` only). All ISC004
concatenations were confirmed intentional line-wraps, not missing-comma bugs.

**OWNER-COORDINATED finding (confirmed, NOT applied on Mac) — inverted
OrderCalcMargin direction (`RiskManager.mqh:296`).** `long dir = (price <
slPrice) ? POSITION_TYPE_LONG : POSITION_TYPE_SHORT;` is fully inverted: a LONG
(slPrice < price) maps to `POSITION_TYPE_SHORT` and thus sizes against SELL
margin, and vice-versa. `dir` only selects the ORDER_TYPE for `OrderCalcMargin`
(it does NOT set the order side), so impact is bounded — nil where buy/sell
margin are equal (typical FX), wrong required-margin only on instruments with
asymmetric long/short margin rates. Correct: `(price > slPrice) ? LONG : SHORT`.
**Deliberately NOT changed on Mac:** the mql5 tree is byte-anchored to the
frozen source commit `227bf66` (`frozen_inputs.json` `source.commit`: "the owner
must compile and execute THIS EXACT commit"), so editing it from Mac would break
the "compile exactly this commit" provenance contract and re-anchoring the
frozen source commit is an owner-authority action tied to the (already
owner-pending) strict EA compile. The fix is a one-line source edit requiring
MetaEditor to verify. **Owner action:** apply this one-liner at the next strict
compile and re-anchor `source.commit` accordingly.

**P3 defense-in-depth (documented, NOT changed) — currently unreachable.** Per
the P3 "do not spend time" rule, and because each is unreachable in the
intended deployment: (a) `api/main.py killswitch_reset` accepts any actor/reason
with no machine-vs-human role check (its sibling `store.transition` enforces
one) — the console is an unauthenticated owner-only local app; (b)
`discovery/research_service.advance` has a latent `actor="owner"` branch that is
never reached (only single legal steps for PARSED…SHADOW, `human` never True);
(c) `entry_chain.govern_entry` reports the first-failing gate, so the kill-switch
is not always the attributed `veto_owner` when an earlier gate also fails
(attribution nit only); (d) `owner_gate.verify_compile` freshness tolerates a
2-day mtime drift band — the real anchor is the EX5 SHA-256 equality, so this is
belt-and-suspenders. Recommend the owner tighten (a) and (d) if desired; none
blocks the Mac RC.

**Cleared with no defect (independent adversarial audits).** Security: no
deserialization/injection/traversal/zip-slip/SSRF/non-loopback-bind/evidence-
forgery/kill-switch-bypass reachable (all absent or correctly defended).
Research/determinism: CPCV two-sided purge+embargo, `np.array_split` block cuts,
seeded RNG everywhere, canonical `sort_keys` JSON into every hash, no
`inplace=True`, closed-bar signals (no lookahead) — clean apart from the
`_most_selected` tie-break above. Discovery/authority: SCORE≠PERMISSION, no
order authority outside `TradeManager`, fail-closed DSL/gates/adapter, human
approval real, meta reduce-only, ML bounded/conservative — invariants hold.

**Validation.** Full deterministic suite: **1602 passed, 1 skipped, 0 failed**
(was 1593/1; +9 regression tests this wave), verified under
`PYTHONHASHSEED=12345` AND cross-checked identical under seeds 1/777 on the
determinism-sensitive suites. `ruff check python/ tests/ tools/ factory/` clean;
`git diff --check` clean. The frozen mql5 tree is byte-unchanged
(`git diff -- mql5/` empty); golds/manifests untouched. Owner certification
remains REALITY_GATE_BLOCKED — nothing runtime-certified, nothing simulated.

## 2026-09-16 — Wave 2.2 final pre-certification audit: verifier hardening + doc-truth fixes

**Purpose.** Deepest pre-owner-certification audit. Fixed genuine
certification-integrity (P0/P1) and provenance/truthfulness defects; no new
features, no weakened gate. Independent audits of the owner-gate verifier
chain, gold/status lane separation, and a repo-wide doc-truth sweep.

**P0 — reconciliation divergence was owner-graded, not computed
(`owner_gate.first_divergence`).** A field diverged ONLY when the
owner-supplied string `status == "DIVERGENT"`; the recorded `python`/`mt5`
values were never compared. An owner whose real MT5 run diverged could reach
`MT5_VALIDATED` by labelling every field `"MATCH"`. Fixed: `_field_divergent`
now treats `status` as ADVISORY and flags a field DIVERGENT whenever the
python/mt5 values disagree (zero tolerance — the gold lane is exact).
Regression: `test_owner_declared_match_cannot_hide_value_divergence`.

**P1 — python column was unanchored to the frozen truth engine
(`owner_gate.verify_reconciliation`).** The docstring promised "the python
side of every event must equal the frozen expected execution," but
`expected_execution_sha256` was never consumed (dead in `frozen_inputs.json`);
a single fabricated `{python:42,mt5:42}` event reached `MT5_VALIDATED`. Fixed:
`expected_execution_sha256` is now a REQUIRED binding, cross-checked against
the frozen `gold_X.expected_execution_sha256`, so the reconciliation must
declare the exact frozen expected-execution artifact its python column came
from. Regression: `test_expected_execution_binding_must_match_frozen_truth`.

**P1 — `tester_models` binding was optional.** Omitting it left
`model_identities` empty, silently skipping the "was the intended tester model
actually used?" check for a gold leg. Fixed: `tester_models` is now a required
binding and must cover every model in `MODELS`. Regression:
`test_tester_models_binding_is_required_and_must_cover_all_models`.

**P1 — `certify_strategy._reconciliation_ok` accepted a PENDING_OWNER
reconciliation as step-8 evidence.** It returned True on mere presence of a
`fields`/`trades` block — which both frozen gold reconciliation artifacts
carry for the python↔DSL/source lanes while `python_vs_mt5_tester ==
"PENDING_OWNER"` and every `mt5 == None`. On a Windows host where the legs
pass, pointing `--reconciliation` at either gold artifact would set
`reconciliation_ok=True` and let VERIFIED stand. Fixed: the helper now
requires a non-PENDING `python_vs_mt5_tester` marker AND at least one real
(non-null) `mt5` observation. Regressions in
`tests/test_certify_strategy_tool.py` (both frozen gold artifacts → False).

**P2 (documented, not code-changed).** (a) `frozen_inputs.json`
`gold_1.config_hash` is empty, so the reconciliation's gold-1 CONFIG binding
is required non-empty but not cross-checked to a frozen anchor (gold-1 config
identity rests on fixture+dataset+source, which ARE anchored). Populating it
needs the real build hash (not fabricated here) — owner/build-side follow-up.
(b) The Gold #2 reproducibility pin is `frozen_inputs.json`
`gold_2.git_commit_recorded = 6b172dac92a6` (Gold #1's is `abea0f410c5a`);
any regeneration MUST pass `--git-commit 6b172dac92a6` to reproduce the
committed manifest hash. The freeze otherwise rests on "never regenerate" +
the git-diff guard (`test_docs_contract`), which both hold.

**Doc-truth fixes.** (1) `PROGRESS.md` CURRENT STATE wrongly claimed a "real
MetaEditor compile (0 errors / 0 warnings — owner environment)" for the EA;
truth: the **exporter script** compiled 0/0, but the **EA**'s last real owner
compile was 0 errors / **2 warnings**, closed by source-only edits never
recompiled — a strict 0/0 EA compile-of-record remains OWNER-PENDING. (2)
`README.md` "no owner artifacts exist yet" corrected to "not committed to this
repo" (owner captured evidence outside the repo; `data/` gitignored). (3)
`HANDOFF.md` weekly self-check "0-warning compile log exists" softened to an
owner-pending target.

**Financial/determinism spot-checks (no defect).** Kelly is capped at 0.25
AND off by default (MQL5 `KELLY_CAP 0.25` / `KELLY_DEFAULT_OFF=True`,
no-edge→no-trade); no martingale/grid-trading anywhere ("grid" = broker
tick/volume grid only). `RunManifest.digest()` excludes the wall-clock
`created` field, so INV-DET holds; remaining `datetime.now()`/`time.time()`
uses are audit-trail metadata, owner-runtime tooling, or `as_of` defaults that
deterministic callers override.

**Validation.** Full suite: **1593 passed, 1 skipped, 0 failed** (was 1585/1;
+8 owner-gate/certify regression tests); `ruff check python/ tests/` clean;
`git diff --check` clean. Frozen MQL5 anchor `227bf66`
unchanged (`git diff 227bf66 HEAD -- mql5/` empty); golds untouched. Owner
certification remains BLOCKED_OWNER_ENVIRONMENT / REALITY_GATE_BLOCKED —
nothing runtime-certified, nothing simulated.

## 2026-09-16 — Wave 2.1 final audit + Mac freeze for owner certification

**Purpose.** Audit Wave 2, make the repository internally truthful and
reproducible, freeze the code side, and prepare the Windows Owner
Certification handoff. No new features, strategies, ML architecture or
unrelated refactor. Authority model unchanged.

**Wave-2 fix re-verification.** All seven Wave-2 fixes were re-checked
against code AND against the old-bug condition (not just "a test exists"):
CPCV block partition (old code makes `n_splits+1` overlapping blocks →
`n_combos=C(7,3)=35` for t=100, the pinned test asserts 6/20), two-sided
CPCV embargo, governor failed-gate no-resurrection (old symmetric delta cap
leaves 0.30 on a gate-failed book; test asserts 0.0), governor demote-only
`[0,1]` multiplier clamp, drift execution-window alignment (old window gives
~0.8 execution-drift on the 60-trade fixture; test asserts 0.0), meta-OOS
one-look-before-look ordering + deterministic `as_of`, cost-stress `None`
guard, and the ML risk-seam duplicate-`order_key` robustness. No accidental
semantic changes found. Fixes 1/2/3/6 were PROVEN to fail under the old-bug
condition (block overlap → C(7,3)=35; symmetric cap → 0.30 on a gate-failed
book; old drift window → ~0.8 execution-drift; old `.loc[key]` → TypeError on
dup keys). Three fixes were green-on-green (correct implementation, but the
existing tests passed even with the old bug): meta-OOS ordering, cost-stress
`None` guard, and the telemetry cap had no failing-under-old-bug test. Wave 2.1
CLOSED these gaps by adding four regression tests: a `run_backtest` spy proving
the refused second OOS look never touches the slice (old code re-ran it), a
degenerate-run test driving `max_drawdown_pct=None` through the cost-stress
gate (old code raised `TypeError`), and a real ephemeral-port telemetry server
asserting a small body → 200 and an oversized `Content-Length` → 413 before any
read.

**Provenance / status truthfulness (the substantive change).** The
broker-evidence model is now stated as THREE distinct facts so the repo
neither over- nor under-claims:
1. **CAPTURED (owner) ≠ NOT PERFORMED.** The owner has already run the
   exporter on Windows and obtained a successful `denomination_probe`
   (`ok=true`, `source=OrderCalcProfit`) for EURUSD / XAUEUR / US30 / BTC.
2. **NOT COMMITTED / NOT REPRODUCIBLE ≠ MISSING.** `data/` is gitignored, so
   those raw exports are not in Git and cannot be re-derived on Mac; the
   in-repo parity report is `n_exports:0`, all classes PENDING.
3. **probe.ok ≠ PARITY PASS.** The ACCOUNT vs PROFIT verdict is rendered only
   when the harness runs on a committed export. No verdict is claimed; the
   denomination decision stays owner-gated (Wave-1 entry unchanged).
   Documented in `docs/BROKER_SYMBOL_PARITY.md` (new "Owner-evidence
   provenance" section + status table) and `PROGRESS.md` CURRENT STATE. No
   raw owner export is committed to green a dashboard, and none is fabricated
   or modified. `data/broker_exports/parity_report.json` (gitignored, local)
   confirms the Mac view is genuinely `n_exports:0`.

**Denomination semantics — unchanged (PENDING).** Reviewed the implemented
parity logic: `denomination_probe.ok=true` is only a precondition; the
harness returns `ACCOUNT_CURRENCY` only when both exported tick values agree
with the independent `OrderCalcProfit` witness, else `PROFIT_CURRENCY` /
`UNVERIFIED` / PENDING. With no committed export the verdict cannot be
rendered here, so PENDING stands. No runtime sizer/RiskManager/SymbolSpec
semantics changed for the sake of completion; no FX rate invented; no
circular derivation from `tick_value`.

**TASKS.md migration.** `TASKS.md` is the archival Phase-2.5 checklist; its
unchecked boxes are NOT a current backlog (the Phase 0–14 research-foundation
modules are all implemented and tested). Added a STATUS BANNER marking it
archival, stating Phases 0–14 are CODE-COMPLETE, identifying the only open
items as the OWNER-PENDING Reality-Gate boxes, and pointing current status to
`PROGRESS.md` / this log / `docs/WINDOWS_OWNER_HANDOFF.md`. Checkbox states
left verbatim; history preserved.

**Freeze anchor.** `artifacts/owner_mt5_gate/frozen_inputs.json` still anchors
the compile to `227bf66`; `git diff 227bf66 HEAD -- mql5/` is empty (Waves 1–2
touched only Python/docs/owner-gate metadata), so the owner compiles the same
EA. The gold artifacts are unchanged since the anchor (freeze invariant
intact).

**ML boundary — unchanged.** ML remains estimation-only: `ml_interfaces.py`
labeler/meta-label/calibrator/feature-store are intentional interface-only
stubs (no training/inference anywhere); the risk seam only drops/shrinks and
re-checks; regime/drift feeds are causal, bounded `[0,1]`, missing→conservative
`0.5`. No generic AI trading system introduced. See `docs/ML_VS_LLM_BOUNDARY.md`.

**Security final pass.** Re-swept the tree with focus on Wave-2 files: NO
high/critical/medium reachable findings. The telemetry body cap is correct and
not bypassable (missing/negative/non-numeric Content-Length handled; chunked
transfer-encoding is not auto-decoded by `BaseHTTPRequestHandler`, so no
unbounded read). Wave 2 introduced no new file-write/subprocess/deserialization
/network sink. All prior controls (loopback binds, paste-first providers,
`yaml.safe_load`, UI→LIVE reject, evidence binding, human-approval actor
prefixes) intact.

**Windows handoff.** Added `docs/WINDOWS_OWNER_HANDOFF.md`: final source SHA /
frozen compile anchor, the `-Strict` compile command, required MQL5 targets,
required owner exports (EURUSD/XAUEUR/US30/BTC), and the 12 owner actions
mapped onto the canonical ten-step `docs/MT5_ROUNDTRIP.md` protocol (no shorter
protocol invented).

**Validation.** Full deterministic suite: **1585 passed, 1 skipped, 0 failed**
(Wave 2 was 1581/1; Wave 2.1 added four regression tests, no source-behaviour
change); `git diff --check` clean. "Ruff clean" here means the
canonical package `ruff check python/ tests/` (All checks passed) — the repo's
established scope; a bare `ruff check` also lints legacy `tools/`/`examples/`
and reports ~13 PRE-EXISTING findings there, untouched by any wave and out of
the canonical scope (Wave 2.1 changed only docs, no Python). This is the final
Mac engineering freeze — the next phase is Windows Owner Certification. Nothing
is runtime-certified.

## 2026-09-16 — Wave 2 research/ML/governance hardening: correctness fixes, no new authority

**Scope.** Wave 2 finished the code-side research/intelligence/governance
work reachable on Mac (no MT5 runtime). Full-repo audits of ML, meta,
discovery, robustness/WFA/OOS, portfolio and a source-level security
review. The authority model is UNCHANGED — no ML/LLM/meta/discovery path
gained order authority; every fix only tightens correctness or the
reduce-only/one-look/no-leakage guarantees. Wave-1 denomination decision
stands unchanged (still owner-gated; parity report still PENDING all
asset classes — see the Wave-1 entry below).

**Fixes applied (each with a pinned regression test).**

1. **CPCV block partition leakage** (`robustness.combinatorial_purged_cv`).
   The hand-rolled stride/remainder block construction produced
   `n_splits + 1` blocks with a duplicated boundary index whenever
   `n_periods % n_splits != 0` (e.g. 100/6 → 7 blocks, index 16 in two
   blocks), leaking a bar across the train/test split of the same fold and
   understating PBO — which feeds `gate6_cpcv_pbo` and the discovery score.
   Replaced with `np.array_split` (exactly `n_splits` disjoint blocks). The
   CPCV embargo was also made TWO-SIDED (it previously purged training only
   *before* each test block, leaving the trailing-edge adjacency of a
   following train block un-embargoed).

2. **Governor resurrected failed-gate strategies** (`discovery/governor.py`).
   The symmetric per-strategy delta cap smoothed an ineligible strategy's
   weight down to `prev − max_strategy_delta` instead of zero, so a strategy
   that just failed its gate could keep non-zero allocation (violating
   "no valid certification ⇒ exactly zero weight, every mode"). Ineligible
   records are now forced to a HARD zero and exempted from the delta cap,
   mirroring the `zero_reason` exemption in `meta_layer._apply_modes`.
   Additionally, caller-supplied decay/ramp multipliers are clamped to
   `[0, 1]` (demote-only by contract) and a single strategy is capped at the
   gross target band — a hostile/buggy multiplier `> 1` can no longer inflate
   exposure.

3. **Drift execution-window misalignment** (`drift_feed._median_bars`). The
   execution-drift baseline used a `recent_n + baseline_n` window (40 trades
   with defaults) instead of the `baseline_n` window (20) that the
   expectancy/PF/winrate components use, diluting a real holding-period shift
   and UNDER-reporting execution drift (non-conservative). The bars windows
   now slice identically to the pnl windows.

4. **Meta-OOS one-look ordering** (`meta_oos.run_meta_oos`). The registry
   `check_identity` ran only *after* the OOS backtests, so a repeat look
   re-executed the whole OOS evaluation before raising. The check now runs
   BEFORE the OOS slice is consumed. A dead wall-clock `datetime.now()` call
   in that path was removed, and `policy_weights` now defaults `as_of` to the
   data's own last timestamp (deterministic) instead of wall-clock.

5. **`float(None)` crash in the cost-stress gate** (`pipeline.cost_stress_gate`).
   `compute_metrics` reports `max_drawdown_pct=None` for degenerate runs;
   `float(None)` would raise mid-stage. Now coerced to `0.0` (the run fails
   the survival test on other conditions anyway).

6. **ML risk-seam robustness** (`ml_interfaces.check_ml_invariants`). The
   guard indexed by a non-unique `order_key` and crashed (`float(Series)`)
   on a realistic book with two orders on the same bar/side. It now compares
   summed per-key exposure (conservative, reduce-only), behaviour-identical
   for unique keys.

7. **Telemetry body cap** (`telemetry_bridge.do_POST`). The collector read
   an unbounded `Content-Length` body before parsing; now capped at 1 MiB
   (413 otherwise). Defense-in-depth on top of the Wave-1 loopback bind.

8. **Docstring honesty.** `optimizer.walk_forward` no longer implies it
   records a one-look (it does not — `OosRegistry` on the S5 path does), and
   `OosRegistry` now documents its single-writer / TOCTOU assumption.

**Validation.** Full deterministic suite: 1581 passed, 1 skipped, 0 failed
(was 1576 passed / 1 skipped before the five new Wave-2 regression tests);
ruff clean; `git diff --check` clean. No MT5 runtime, Strategy Tester, real
tick, Gold, demo/live or owner evidence was run or fabricated on Mac.

**Security review.** Source-level audit of `python/`, `factory/`, `tools/`,
`scripts/`, `mql5/` found NO high/critical reachable vulnerabilities:
subprocess is fixed-argv only, no `eval`/`exec`/`pickle`/`yaml.load`, no
network dereferencing in the intake path (community text is treated strictly
as sanitized DATA), no hardcoded secrets, servers loopback-bound, and the
factory→execution, ML→order and UI→live authority controls are enforced
server-side (evidence binding, human-approval actor prefixes, no order
endpoint). The telemetry body cap (#7) was the only hardening applied.

## 2026-09-16 — Wave 1 code-side pass: tick-value denomination stays owner-gated; loopback-default network servers

> **SUPERSEDED (2026-09-18).** The tick-value denomination DEFER below is
> resolved by the 2026-09-18 "Audit-and-close wave" entry above: committed
> owner evidence (`artifacts/owner_mt5_gate/broker_parity.json`,
> `ACCOUNT_CURRENCY` MATCH for EURUSD/US30/XAUEUR) now attests the
> account-currency denomination, so the `profit_to_deposit` multiply is
> removed from the loss-per-lot path. The loopback-default network-server
> hardening in this entry stands.

**Trigger.** Wave 1 asked whether the runtime double-converts stop-loss
risk: `SpecLossPerLot` (and the Python `loss_per_lot`) multiply
`tick_value_loss` — read at runtime from `SYMBOL_TRADE_TICK_VALUE_LOSS`
(`SymbolSpec.mqh:82`) — by a runtime `ProfitToDeposit` FX factor
(`RiskManager.mqh:213,374`). If MT5 already denominates that tick value in
the *account* currency, the second multiply is an unjustified conversion
for cross-currency symbols (e.g. EURUSD/US30/BTC on a EUR account).

**Decision — DEFER, do NOT patch runtime semantics.** The
ACCOUNT_CURRENCY vs PROFIT_CURRENCY denomination is exactly what
`tools/broker_symbol_parity.py` resolves, and only from a committed owner
export carrying an independent `OrderCalcProfit` witness
(`docs/BROKER_SYMBOL_PARITY.md`, Stage A). In this tree
`data/broker_exports/` contains **no owner export** (`parity_report.json`
→ `n_exports: 0`; every asset class PENDING). The witness numbers quoted
in the Wave-1 directive are not present as verifiable artifacts, and
deriving the fix from them would (a) contradict the repo's own fail-closed
deferral of this denomination and (b) act on evidence that cannot be
attested on this host — a provenance violation. Per the Wave-1 rule
"evidence does not conclusively prove a defect → do not patch runtime
semantics, preserve fail-closed behavior": no sizer / RiskManager /
SymbolSpec semantics changed. The suspected double-conversion is recorded
as an **owner-gated open item**: it is confirmed or refuted only when real
FX/METAL/INDEX/CRYPTO owner exports land and the parity harness renders an
accepted `ACCOUNT_CURRENCY` verdict on Windows. `NEVER derive FX from
tick_value` and `no global FX state` remain in force.

**Security hardening (Wave 1F, applied).** The two unauthenticated HTTP
servers — the telemetry collector (`telemetry_bridge.py`) and the status
dashboard (`dashboard.py`) — bound `0.0.0.0` unconditionally, exposing an
attacker-writable JSONL sink and a status endpoint to the whole LAN. Both
now default to `127.0.0.1` with an explicit `--host` opt-in for cross-host
use behind a firewall/tunnel. Fail-safe default; no capability removed.
Cross-host telemetry from the MT5 terminal now requires an explicit
`--host 0.0.0.0` (documented in the collector's `--help`).

**Trigger.** The repository is now published as a squashed single-commit
snapshot: `227bf66 Initial commit`
(`227bf665654b2d2491c89c226dcff735570b915a`, branch `master`). The prior
freeze anchor `52cbaa5e0077056d75ac7ed2afc423ef24d5cd23` recorded in
`artifacts/owner_mt5_gate/frozen_inputs.json` is unreachable from this
history, so
`tests/test_docs_contract.py::test_owner_mt5_gate_package_exists_and_is_pending_owner`
failed its `git merge-base --is-ancestor <anchor> HEAD` check.

**Diagnosis (this is NOT the shallow-clone case).** The 2026-09-08
environment note below documents a *shallow clone* reproduction where the
anchor object is merely absent locally and `git fetch --unshallow`
restores it with no source change. That is explicitly not the situation
here: `.git/shallow` is absent, `git rev-list --count HEAD` is exactly
`1`, and the historical commits (`58ce3ad`, `29dd770`, `781290b`, and the
old anchor itself) genuinely do not exist in the object store and cannot
be fetched. The history was rewritten by a squash; the anchor is gone for
good, not hidden.

**Decision — provenance-correctness-only re-anchor.**

1. `frozen_inputs.json` `source.commit` is migrated
   `781bea4 -> 54613aa -> 52cbaa5 -> 227bf665…` and `source.branch` set to
   `master`, under the same rule as the 2026-09-08 anchor migrations: a
   change to the source-of-record snapshot moves the anchor.
2. This re-anchor touches provenance only. Every frozen semantic hash in
   the file — gold #1/#2 fixture, config, dataset, manifest, spec, and the
   Gold #2 `artifact_hash_chain` — is byte-untouched, and
   `git_commit_recorded` for each gold (the historical commit that
   *produced* that gold) is deliberately left as-is; it records when the
   gold was made, not the current freeze anchor.
3. The freeze invariant still holds and is still enforced: with the anchor
   equal to HEAD the golds are present at the snapshot exactly as frozen,
   so `git diff <anchor> HEAD -- artifacts/gold artifacts/gold_2` is empty
   and `merge-base --is-ancestor` passes. The contract was re-pointed to
   the truth, not weakened; `certification_manifest.json` remains
   `REALITY_GATE_BLOCKED` / `PENDING_OWNER` and no owner evidence was
   fabricated.

**Owner flow unchanged.** Checkout `227bf665…`, run
`tools\compile.ps1 -Strict` (0/0 expected), re-run the exporter on the
live account, commit the real broker exports, then re-run
`tools/broker_symbol_parity.py`.

---

## 2026-09-15 — Stage A validation count discrepancy and exporter sign gate

1. The reported `1599 passed / 1 skipped` versus `1598 passed / 1 skipped`
   difference is not reproducible from this checkout. Under the exact requested
   Python 3.13/uv dependency command with collection-only mode, the base
   `58ce3ad` collected 1,569 tests; the current Stage-A tree collected 1,576
   before the new regression test and 1,577 after it. The same dependency
   environment was used for both collections.
2. A path-level collection diff found exactly two base tests intentionally
   replaced (`test_derived_tick_value_identity` and
   `test_derived_identity_cross_currency`) and the nine Stage-A denomination
   tests that replaced/expanded that coverage; no unrelated test path
   disappeared or changed collection status. Therefore the reported one-test
   delta cannot be attributed to accidental test loss or a dependency change
   in this repository. It is an unreproduced run-context/collection-count
   discrepancy, not a reason to remove or weaken a test.
3. The MQL5 exporter now sets `denomination_probe.ok` only after both
   `OrderCalcProfit` calls succeed, all probe numeric inputs/outputs are valid,
   BUY produces a strict negative loss, and SELL produces a strict positive
   gain. Each failure keeps its specific reason and the last error observed;
   evidence fields remain `null` unless the complete invariant is true.

---

## 2026-09-15 — Stage A: independent tick-value denomination measurement

1. The old PENDING-only derived FX identity was a harness defect: it could not
   independently attest whether MT5's tick value was denominated in account or
   profit currency. Deriving FX from `tick_value / (contract_size × tick_size)`
   is circular and is forbidden.
2. The exporter now optionally records one-symbol evidence from an independent
   `OrderCalcProfit` witness at 1.0 lot over `N` ticks (default 100). BUY uses
   `ask → ask - N*tick` and must be negative; SELL uses `bid → bid - N*tick`
   and must be positive. Tick values are re-read at that same moment. Failure
   remains explicit (`ok=false`, reason, last_error) and numeric fields are not
   fabricated.
3. The harness assesses each symbol independently. `ACCOUNT_CURRENCY` requires
   agreement with both witness sides; `PROFIT_CURRENCY` requires the structural
   tick hypothesis plus a meaningful separation from the account witness;
   otherwise the result is `UNVERIFIED / PENDING`. The controls are intentionally
   conservative: agreement tolerance `1e-3`, separation minimum `1e-2`.
4. The optional probe stays outside `FIELD_MAP`, preserving backward
   compatibility for old four exports. The parity-only sizer replay no longer
   forces `currency_deposit := currency_profit`; it uses the export's actual
   `account_currency` only for an independently supported account-currency
   verdict, and otherwise remains PENDING without manufacturing a conversion.
5. This is observability/measurement only. `RiskManager.mqh`, `SymbolSpec.mqh`,
   the Python runtime sizer/engines and owner-gate artifacts are untouched; no
   runtime risk semantics changed. Broker parity is STILL NOT VERIFIED, and BTC
   remains an owner-side open measurement.

---

## 2026-09-10 — Asset-class coverage: one rule could no longer consume a symbol (METAL export counted as FX)

1. **Proven defect, from the owner's own exports.** `asset_classes_covered()`
   walked the required classes in a single `if`/`elif` chain, so the first rule
   that matched a symbol consumed it outright. Its FX branch carried a bare
   shape test — `len(name) == 6 and name.isalpha()` — and the owner's `XAUEUR`
   export (`SYMBOL_PATH` = `Metals\XAUEUR`) satisfied that test, so the METAL
   branch was never reached: with four exports committed, coverage read
   `FX: exported: XAUEUR` and `METAL: PENDING (no owner export)`. The gate
   therefore believed a metal export satisfied the FX requirement while still
   demanding a METAL export that had in fact been delivered. Reproduced
   before/after against the same four documents.
2. **Two bugs in one shape.** The chain made the *class* order-dependent, and
   the unconditional `out["FX"] = ...` made the *representative* depend on
   enumeration order (last valid export won). Coverage is a per-class property,
   not a partition of the symbol universe: a symbol either evidences a class or
   it does not, independently of the other classes, and each class needs one
   deterministically chosen witness.
3. **Fix — semantics only, no new broker taxonomy.** The markers are exactly
   the ones the harness already used, now data: `CLASS_PATH_MARKERS`
   (`forex/fx/major/minor`, `metal/xau/xag`, `index/indices/cfd`,
   `crypto/btc/eth` on `SYMBOL_PATH`) and `CLASS_NAME_PREFIXES`
   (`XAU`/`XAG`, `BTC`/`ETH`). `_asset_classes_supported(path, name)` returns
   every class a symbol evidences (independent checks, a list, no `elif`), and
   `asset_classes_covered()` fills each class once from the first candidate in
   an explicit order (upper-cased name, then path). The 6-letter shape test was
   not deleted wholesale and was not swapped for another broad rule: it survives
   only as a **fallback**, consulted when the export carries no class evidence
   at all (some brokers leave `SYMBOL_PATH` empty or uninformative) and never
   for a name a specific class already claims — the exclusion list reuses the
   repo's own metal/coin prefixes, so `XAUEUR` cannot reach FX even path-less.
   A symbol that genuinely evidences two classes now counts toward both, which
   is honest coverage rather than a substitution.
4. **Determinism policy, stated and tested.** No filesystem or caller order is
   used as an implicit tie-breaker; alphabetical, reverse-alphabetical,
   metal-first and directory order all yield the identical mapping, and with
   duplicate candidates the representative is the sorted-first valid match
   (`EURUSD` over `GBPUSD`, `XAGUSD` over `XAUUSD`) whichever way round the
   inputs arrive.
5. **Tests (7 new, nothing removed or weakened).** In
   `tests/test_broker_symbol_parity.py`: the four-export coverage table, the
   `XAUEUR`-is-not-FX regression (with and without a path), the fallback
   constraint (path-less pair still FX; evidenced classes never re-routed; no
   evidence ⇒ everything PENDING, never invented), multi-class independence,
   order independence including `build_report()` over real files, the
   deterministic-representative rule, and an `ast` pin that fails any
   `if`/`elif` chain whose branches both assign coverage — structural, so
   reformatting cannot dodge it. Mutation-checked against the real classifier:
   full revert 7 failed; independent checks with the unconstrained shape test
   2 failed; fallback deleted 1 failed (recording that the path-less case is
   deliberate); last-write-wins restored 1 failed; format-only reformat green.
6. **What this does NOT mean.** In this owner-export-only path the rows carry
   `python_spec=None`, so no field-by-field owner-vs-Python comparison is being
   performed; `Verdict: 92 rows, 0 mismatches, 4 pending` counts rows, it does
   not certify parity. **Asset-class coverage corrected — BROKER PARITY REMAINS
   NOT VERIFIED**, and the four derived FX conversion rows stay `PENDING`
   (never fabricated away). `mql5/` was not touched: no exporter, encoding,
   schema, field-name, numeric-formatting, tolerance or fail-closed-rule change,
   no engine/risk/meta/gold/frozen-artifact change, and no owner export was
   edited, created or replaced — `data/broker_exports/` does not exist in this
   sandbox checkout, so the four-export run used the module's own synthetic
   fixture documents in a throwaway directory purely to exercise the classifier.

## 2026-09-10 — Broker export file encoding: the exporter pins `CP_UTF8` instead of the machine ANSI code page

1. **The mismatch, read from the repository rather than guessed.** The
   exporter opened the file with `FileOpen(fname, FILE_WRITE | FILE_TXT |
   FILE_ANSI)` — no code page given, so `CP_ACP`, the terminal host's Windows
   ANSI code page — while every Python side of the contract decodes it as
   strict UTF-8: `load_owner_export()` is
   `json.loads(path.read_text(encoding="utf-8"))` (`tools/broker_symbol_parity.py`),
   as are `tools/verify_owner_mt5_gate.py` and `tools/owner_evidence_bind.py`,
   and `main()` writes the parity report back out with `encoding="utf-8"`. No
   reader tolerates a BOM (`utf-8-sig` appears only in the CSV data lane,
   `python/mql5bot/data.py`). Since the escaping contract deliberately passes
   non-ASCII characters through untouched, "UTF-8" was an assumption of the
   reader, never a promise of the writer: on a Western-European Windows, U+00D8
   lands as the single byte `0xD8`, which is not valid UTF-8, so a correctly
   escaped export is still skipped as malformed. It stayed invisible because
   the observed broker text is pure ASCII — byte-identical in UTF-8 and CP1252.
2. **`FileOpen` verified before choosing the form.** The signature is
   `FileOpen(name, flags, delimiter='\t', codepage=CP_ACP)` (the repo's own
   `Mql5BotDownloadData.mq5` passes the delimiter as the third argument). The
   code page "only affects files opened in text mode (`FILE_TXT` or
   `FILE_CSV`), and only if `FILE_ANSI` mode is selected for strings"; a text
   file opened without `FILE_ANSI` is written as UTF-16 *with a BOM*, which
   `encoding="utf-8"` cannot decode at all. So the tempting
   `FILE_WRITE | FILE_TXT` + `CP_UTF8` spelling is the wrong fix: the flag that
   looks "ANSI-only" is exactly the one that makes a code page mean anything.
   The documented UTF-8 text mode (MQL5 Book, *Selecting an encoding for text
   mode*) is `FILE_WRITE | FILE_TXT | FILE_ANSI, 0, CP_UTF8` — conversion
   through the UTF-8 code page, therefore BOM-less — with `0` for the delimiter
   because `FILE_TXT` ignores it and the argument is positional.
3. **The change is one line plus its rationale comment:**
   `int fh = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_ANSI, 0, CP_UTF8);`.
   The exported bytes are now determined by the program, not by the host
   locale, and the `FILE_TXT` mode itself is untouched, so line-ending and
   `FileWriteString()` behaviour are exactly as before. `JsonEscape()`, the
   schema, field names, numeric formatting and the verifier's verdict
   semantics did not move; the encoding of the string values (raw non-ASCII,
   no `\uXXXX` over-escaping) is unchanged, only the code page that turns
   those characters into bytes.
4. **No evidence invalidated, and no other lane dragged along.** For
   pure-ASCII broker content the file bytes are identical, so no committed
   export and no recorded hash moves — and
   `artifacts/owner_mt5_gate/{frozen_inputs,certification_manifest}.json`
   record no hash of the export script. `Logger`/`Allocation`/`StateStore`/
   `MagicMap` text files are read back by MQL5 itself and the CSV download lane
   is read with `utf-8-sig`; none carries a byte-exact UTF-8 contract, so they
   were left alone rather than "consolidated".
5. **Regression design (layer 4 of `tests/test_broker_symbol_parity.py`).** The
   reader is *executed* on candidate bytes: only BOM-less UTF-8 loads, while
   CP1252, UTF-16 and BOM-prefixed UTF-8 are rejected, and a wrong-code-page
   export is reported as skipped and never transcoded. The exporter is then
   read structurally rather than by string match — the `FileOpen` call's flags
   are compared as a set and its code page as an argument — so flag order, line
   breaks and naming cannot break it, and the documented
   `FILE_BIN` + `StringToCharArray(..., CP_UTF8)` + `FileWriteArray()` route is
   accepted as an equivalent implementation. Finally the file-layer settings
   parsed from the source are *modelled into bytes and piped through
   `load_owner_export()`*, so the pins fail for the real reason rather than for
   a spelling. Mutation-checked: the pre-fix line, `FILE_TXT | CP_UTF8` without
   `FILE_ANSI`, `FILE_UNICODE`, and an explicit `CP_ACP` each fail two tests; a
   format-only reformat, the reordered flag set and the numeric code page
   `65001` stay green.
6. **No compile claim.** MetaEditor cannot run in this sandbox, so the
   exporter has not been recompiled here — source validation only. Owner flow
   unchanged: `tools\compile.ps1 -Strict` (expect 0 errors / 0 warnings),
   re-run the exporter per required asset class, `python tools\broker_symbol_parity.py`.
   Broker parity remains NOT VERIFIED: one FX export leaves METAL / INDEX_CFD /
   CRYPTO `PENDING`.

## 2026-09-09 — Broker export emitted invalid JSON: `JsonQuote()` wrote string values unescaped, so a backslash in `SYMBOL_PATH` made the owner export unparsable

**Trigger.** Owner run on MetaQuotes-Demo (MT5 terminal build 6184,
MetaEditor 5.0.0.6184), `Mql5BotExportSymbolSpec` on EURUSD,H1. The
script reported success (`[mql5bot] exported EURUSD ->
MQL5\Files\Mql5Bot\broker_exports\EURUSD.json`) and the generated file
contained `"path": "Forex\EURUSD"`. `tools/broker_symbol_parity.py`
then reported `WARNING: skipping malformed export: Invalid \escape: line
11 column 19 (char 259)` and treated the owner export as unavailable.
The script had compiled 0 errors / 0 warnings in the owner's MetaEditor,
so this is a runtime **serialization** defect, not a compile defect.

**Decisions:**

1. **Fix the exporter, never the validator.** A raw backslash inside a
   JSON string literal is not a legal escape (RFC 8259 permits only
   `\"`, `\\`, `\/`, `\b`, `\f`, `\n`, `\r`, `\t` and `\uXXXX`),
   so the document was malformed and every parser — not just ours — had
   to reject it. The harness keeps its fail-closed rule (a malformed
   export is skipped and reported, never silently repaired), the strict
   schema check is unchanged, and the owner's malformed file was NOT
   hand-edited or replaced by a fabricated corrected artifact: no
   `data/broker_exports/` content was written to the repository at all.
2. **Escaping is generic and happens at the string-value level.**
   `JsonQuote()` now delegates to a new `JsonEscape()` used for every
   string written into the document: backslash first (it introduces
   every sequence that follows), then `"`, `\n`, `\r`, `\t`, `\b`,
   `\f`, then `\u00xx` for the remaining U+0000..U+001F range.
   Ordinary characters — non-ASCII included — are copied through
   untouched, the finished document is never post-processed, and no
   encoding transformation was introduced (still `FILE_WRITE |
   FILE_TXT | FILE_ANSI`). It is not a `SYMBOL_PATH` special case and
   no broker value is hard-coded: the export stays actual MT5 runtime
   data. MQL5 documents no `"\b"`/`"\f"` string escapes, so those two
   controls are matched by hex value (`"\x08"`, `"\x0C"`).
3. **Regression evidence exists without a compiler, and pins behaviour rather
   than layout.** `tests/test_broker_symbol_parity.py` gained three layers:
   (1) the JSON contract itself — the exported representation must equal the
   canonical encoding `json.dumps(value, ensure_ascii=False)` (named escapes,
   `\u00xx` for the rest of the control range, ordinary and non-ASCII text
   copied through), parse through `json.loads` and decode back to the exact
   broker value; (2) a lightweight source contract that locates the escaping
   helper by brace matching and reads its rules from either implementation
   style (`StringReplace()` table or per-character `case` labels), so
   indentation, parameter naming and brace placement cannot break it, and
   that backslash escaping precedes the rest; (3) harness behaviour — an
   escaped export is parsed and counted, the *un*escaped pre-fix bytes are
   skipped and never repaired. Mutation-checked: a layout-only reformat and a
   per-character rewrite stay green, while dropping a single rule, dropping
   the control range, escaping the finished document instead of the values,
   or restoring the pre-fix helper all fail. Replaying the
   pre-fix source in the sandbox reproduced the owner's exact diagnostic
   (`Invalid \escape: line 11 column 19 (char 259)`); replaying the
   fixed source produced a document the harness accepts with coverage
   `FX: exported: EURUSD` and METAL / INDEX_CFD / CRYPTO still `PENDING`
   — one FX export does not close the parity gate.
4. **Adjacent issue recorded, not changed.** The exporter writes
   `FILE_ANSI` while `load_owner_export()` reads UTF-8. For the ASCII
   broker text actually observed here the bytes are identical, so this
   fix does not touch encoding; a broker with non-ASCII symbol paths or
   server names is a separate, documented concern.
   *Superseded 2026-09-10:* the concern is fixed at the source instead of
   documented — the exporter now pins `CP_UTF8`, see the entry above.
5. **No certification movement.** Schema `mql5bot.broker_export/1`,
   `FIELD_MAP`, tolerances, the parity verdict semantics, the five
   engines, Risk/Meta/Kill-Switch, retry semantics, gold #1/#2 and the
   frozen provenance are untouched. MetaEditor cannot run in this
   sandbox, so the exporter has NOT been recompiled here — source
   validation only. Owner flow: compile at the new commit
   (`tools\compile.ps1 -Strict`, expect 0 errors / 0 warnings), re-run
   the exporter on the live account for every required asset class,
   commit the real exports, then re-run `tools/broker_symbol_parity.py`.
   Whether this commit becomes the new freeze anchor is an owner
   decision under the same rule as 2026-09-08 (a source change that
   forces a fresh strict compile moves the anchor; `frozen_inputs.json`
   was deliberately left untouched here).

**Environment note for the next validation run.**
`tests/test_docs_contract.py::test_owner_mt5_gate_package_exists_and_is_pending_owner`
proves freeze reachability with `git merge-base --is-ancestor <anchor> HEAD`.
In a shallow or partially cloned workspace (`.git/shallow` present, history
grafted at the base commit) the frozen anchor object is not present locally
and the check fails with `fatal: Not a valid commit name 52cbaa5e…` while the
working tree is perfectly fine. `git fetch --unshallow origin` fetches the
real history and the test passes with no source change at all; the contract
was deliberately NOT weakened for the sandbox. Full-suite validation for this
fix was run after unshallowing (213 commits reachable, anchor an ancestor of
HEAD, `git diff <anchor> HEAD -- artifacts/gold artifacts/gold_2` empty).

---

## 2026-09-08 (2) — Strict-compile warnings closed: OrderCalcMargin fail-closed, script version metadata, PowerShell 5.1 ASCII determinism

**Trigger.** Owner re-compile at `54613aa`: 0 errors but 2 warnings
(strict exit 3): `RiskManager.mqh(334,16) warning 83` (unchecked
`OrderCalcMargin` return) and `Mql5BotDownloadData.mq5(15,11) warning
68` (version `1.0.0` not market format). Additionally the owner had to
hand-convert `tools\compile.ps1` to UTF-8 BOM for PowerShell 5.1 — a
portability defect in the repository.

**Decisions:**

1. **Unchecked `OrderCalcMargin` in the margin step-down loop — fixed
   fail-closed, not silenced.** Margin is risk-critical (SPEC §3.3
   "query, never assume"): a broker-calculation failure must never
   pass as a successful margin calculation. The loop now checks the
   boolean return and vetoes (`outReason = "OrderCalcMargin failed
   during step-down"`, 0 lots) the moment a call fails — never keeps
   stepping with a stale value, never guesses. The other two
   RiskManager call sites and the ExportSymbolSpec probes were already
   checked; behavior on success is unchanged. Pinned by
   `test_every_ordercalcmargin_call_is_checked`.
2. **Script version metadata moved to the market plane.**
   `Mql5BotDownloadData.mq5` now carries `#property version "1.00"`,
   same plane and rationale as the EA fix (MetaEditor requires
   xxx.yyy executable metadata on every program type that declares
   it). `Mql5BotExportSymbolSpec.mq5` declares no version property
   (hence zero warnings) and is left unchanged. Release/package
   version 1.0.0 (CHANGELOG/pyproject/`MQL5BOT_VERSION`/Python Meta)
   is untouched. Pinned by `test_all_mql5_version_properties_are_market_format`.
3. **PowerShell sources are pure ASCII from now on.** Windows
   PowerShell 5.1 parses BOM-less scripts with the system ANSI
   codepage, so non-ASCII bytes (em-dashes in `compile.ps1`, `§` in
   `run_mt5_backtest.ps1`) are nondeterministic across hosts — the
   owner should never need a manual encoding conversion. Both files
   were converted to ASCII equivalents (log/comment text only; zero
   behavioral change). Pinned by
   `test_powershell_sources_are_ascii_for_ps51`. New `.ps1` tooling
   must stay ASCII or carry an explicit UTF-8 BOM committed to the
   repository.
4. **Freeze anchor migrated `54613aa` → this warnings-closure
   commit.** `54613aa` compiles with warnings → strict gate exit 3 →
   the certification protocol (which requires 0/0) is unsatisfiable at
   that anchor. Migration is warnings-closure-only: no engine
   semantics, gold fixtures, manifests or protocol content changed;
   fixture/config/dataset hashes inside `frozen_inputs.json` are
   untouched. Owner flow: checkout the anchor commit, run
   `powershell -ExecutionPolicy Bypass -File tools\compile.ps1
   -Strict` directly from the clean clone (no BOM step), expect exit
   0 with three 0/0 targets; verify evidence from the latest checkout
   carrying the migrated `frozen_inputs.json`. The previous anchor
   note is superseded here, never silently.

---

## 2026-09-08 — First real MetaEditor compile: four fabricated identifiers removed; retry mapping fixed against real MQL5 retcodes; EA metadata version plane

**Trigger.** The owner's Windows environment (MT5 build 6148,
MetaEditor 5.0.0.6184, PowerShell 5.1) ran the first REAL strict
compile: `Mql5Bot.mq5` → 50 errors / 2 warnings; both helper scripts
compiled clean. This is a genuine integration-boundary defect class:
identifiers written without a real MQL5 compiler present.

**Decisions (all preserve canonical AEGIS semantics):**

1. **`TRADE_RETCODE_RETRY` and `TRADE_RETCODE_NO_QUOTES` do not exist
   in MQL5** (official reference: Trade Operation Result Codes —
   10006 is REJECT, 10018 is MARKET_CLOSED). They were removed, not
   renamed to look-alikes:
   - The intended "no quotes" transient is the real
     `TRADE_RETCODE_PRICE_OFF` (10021, "there are no quotes to process
     the request") — used at the three self-detected no-quote sites in
     `TradeManager.mqh` and already present in the retryable set.
   - The intended "server says retry" class has NO real equivalent;
     the transient classes are explicitly covered one-per-code by
     `REQUOTE` (10004), `PRICE_CHANGED` (10020), `PRICE_OFF` (10021),
     `TIMEOUT` (10012). The fake RETRY case was DELETED — mapping it
     onto REJECT would invert semantics (a refusal is fatal).
     Rejects/market-closed/invalid-* stay fatal: fail-safe = never
     retry what we do not understand (SPEC §8.D unchanged).
2. **`POSITION_TYPE_LONG/SHORT` do not exist in MQL5** (real
   `ENUM_POSITION_TYPE` = {POSITION_TYPE_BUY, POSITION_TYPE_SELL}).
   A single explicit mapping was added in `Config.mqh`:
   `#define POSITION_TYPE_LONG POSITION_TYPE_BUY`,
   `#define POSITION_TYPE_SHORT POSITION_TYPE_SELL` — the project
   vocabulary stays at all 27 call sites; values match the real enum
   so every comparison/adoption/netting computation is unchanged.
   The comment documents the four distinct direction concepts
   (signal/position/order/deal) that must never be conflated.
3. **`Ask()/Bid()` are `const`.** They are pure `SymbolInfoDouble`
   reads with no member mutation; `MinStopDist(...) const` may then
   call them under MQL5 const-correctness rules. No cast, no caller
   change, no semantic change.
4. **`Allocation.mqh ParseStrategies` gained an explicit terminal
   `return false`** after its `while(true)` loop. The path is
   unreachable (every iteration returns/continues), but MQL5 requires
   every syntactic control path to return; fail-closed matches the
   parser's defensive contract.
5. **`QueueCancelByTicket` moved to a labeled public block** in
   `CTradeManager`. Ownership analysis: the EA's restart orphan-scan
   owns the recovery POLICY; the TradeManager owns execution
   AUTHORITY. This method is the ONLY external entry into the cancel
   path and it never sends an order directly — it enqueues a bounded,
   magic-tagged, deduped retry item. Making it public is the correct
   boundary, not a visibility accident; nothing else in the private
   region changed.
6. **EA metadata version is a separate plane.** The strict gate
   requires zero warnings; MetaEditor rejects `#property version
   "1.0.0"` for Expert Advisors ("must be xxx.yyy"). The EA and
   `Config.mqh` now carry `#property version "1.00"`. This is
   MetaEditor MARKET-METADATA format only. It does NOT change:
   repository release version 1.0.0 (CHANGELOG/pyproject),
   `MQL5BOT_VERSION "1.0.0"` (telemetry identity), Python Meta layer
   1.0.0 (`docs/VERSION_CONSISTENCY.md`). Scripts keep their existing
   properties (they compiled clean). `#property strict` (MQL4 relic)
   was left in place: the scripts carry it and compiled with zero
   warnings on build 6184, proving it is silent.

**Regression pins.** `tests/test_mql5_sources.py` now enforces: every
`TRADE_RETCODE_*`/`POSITION_TYPE_*` used in MQL5 belongs to the
authoritative real-constant allow-list; the retryable set is exactly
{REQUOTE, PRICE_CHANGED, PRICE_OFF, TIMEOUT}; the LONG/SHORT→BUY/SELL
mapping exists; Ask/Bid are const; QueueCancelByTicket is public;
EA/Config version properties are xxx.yyy.

**Provenance.** No Gold artifact, expected execution, Python research
behavior, or certification rule was touched. The EA source at this
commit supersedes the pre-compile freeze for COMPILATION purposes
only: gold fixtures, manifests and certification protocol are pinned
unchanged (docs-only / MQL5-compile-correctness change under the
freeze policy; the verifier's SOURCE_COMMIT check must be re-anchored
by the owner runbook if and only if this commit is adopted as the new
frozen anchor — recorded here, never silently).

---

## 2026-09-07 — Gold #2 reconstructed with NEW provenance; three sizing-provenance bugs found and closed; forced risk-veto design REJECTED as overfitting

**Status.** Gold #2 exists again as
`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE` (label pinned in
`artifacts/gold_2/manifest.json`). Sandbox-side deterministic evidence
is complete: **GOLD_2_PROVEN (LOCAL_DETERMINISTIC_GATE)**. The MT5 legs
against it (compile/tester/reconciliation) remain
**BLOCKED_OWNER_ENVIRONMENT** per the canonical TEN-step owner protocol.

**No continuity is claimed.** The historical Gold #2 artifacts (the
"seven trades") are absent from this environment; a tree-wide search
found nothing. This reconstruction is a NEW controlled experiment, not
a recovery; the manifest's `continuity_disclaimer` says so in the
artifact itself, and no test or doc may claim the historical trades
reproduce.

**What was built.**

* `examples/strategies/gold2_multifactor.json` — DSL spec: EMA8/21
  trend gate AND (RSI14 strict-zone escape OR Donchian-20 breakout),
  session [08:00, 16:00), state mode, SL 2.0 / TP 3.0 ATR14.
* `python/mql5bot/gold2_reference.py` — independent plain-numpy
  transcription of the spec (the Python↔DSL parity check is a real
  two-implementation comparison, plus `boundary_distances()`).
* `tools/build_gold2_standard.py` — engine-direct deterministic
  fixture builder (4 trading days × 1440 M1 bars, EURUSD parity spec):
  Day 1 meta 1.0 (SL/TP/signal exits, post-TP same-bar re-entry,
  session-boundary book entered 15:58 and flattened at 16:00), Day 2
  meta 0.5 (Risk→Meta ladder SEND 0.01), Day 3 meta 0.1 (escape-driven
  entries, SEND 0.08), Day 4 meta 0.0 (signal present, ALL entries
  dropped). 56 trades, 30L/26S, all three exit reasons, 10
  session-vetoed pre-open fires, RSI escape margins inside the
  ±0.5/±1/±2 bands (computed, persisted in
  `provenance.json::rsi_escape_edges`).
* `artifacts/gold_2/` — manifest, fixture CSV, Python trace, DSL
  trace, expected execution, reconciliation, provenance, all bound by
  the manifest hash chain.
* `tests/test_gold2_standard.py` — 18 tests; NO hand-typed expected
  values: every expectation is recomputed from fixture + engine; parity
  is exact (no tolerance on direction/reasons/vetoes).

**Provenance bugs found and closed (high-value findings).**

1. `META_SCHEDULE` was missing from the config hash. Fixed: the
   time-based allocation schedule is now a first-class member of
   `_config_hash()` (attack test: mutating ONLY the schedule changes
   the hash and the fills).
2. The builder's expected-execution sizing used `atr[signal_bar - 1]`
   — an off-by-one. The engine (`size_lots`) sizes on
   `atr[entry_bar - 1]` = `atr[signal_bar]`. Fixed, and proven two
   ways: a minimal ramp-tape experiment where only the signal-bar ATR
   reproduces the fill (±1 bars are distinguishable), and a full
   fixture reconciliation where all 56 engine fills equal the expected
   rows built from the signal-bar ATR.
3. The sizing BASIS is live equity, not day-start equity: the engine
   re-marks `basis = float(equity[i])` at the end of EVERY bar
   (engine.py). Expected execution now sizes on `equity[signal_bar]`
   and every fill reconciles exactly.

**REJECTED design (anti-overfitting).** An earlier draft added a
fifth day: a staircase of eight crash/spike impulse pairs meant to
force a 7% daily-loss halt inside the Gold fixture. It required
repeatedly escalating impulse magnitudes to overcome EMA-gap physics,
entries landed on momentum continuation bars (turning intended SLs into
TPs), and the resulting cascade was tuned until it produced the desired
ending — SCENARIO_MANIPULATION, not SCENARIO_DESIGN. It was deleted.
Rationale recorded, not hidden: the risk-veto/daily-loss mechanism does
not need Gold #2 to be dramatic; it is covered by dedicated
micro-fixtures (`tests/test_engine.py::test_daily_loss_limit_*`,
`tests/test_safety_micro_fixtures.py` which pins the `<=` halt
comparator by bracketing + literal source contract, and the Meta
reduce-only sweep). Gold #2 records the OBSERVED `risk_vetoes = 0`
honestly.

**Daily-loss halt semantics pinned.** Halt iff
`basis <= day_start_equity * (1 - lim/100)` evaluated at each bar open
on the previous-close basis — equality HALTS; the day lock lifts at the
next server-day boundary. Pinned by bracketing micro-fixture (halt
strictly below threshold, no halt strictly above) plus the literal
comparator check.

**Gold #1 regression.** Byte-identical under the frozen pin
(`--git-commit abea0f410c5a`) after every change in this entry.

---

## 2026-09-07 — RSI zone-escape: Python + DSL aligned to the EA rule — CONTRACT_GAP SUPERSEDED by PROVEN_EXACT (final closure)

**Supersedes.** The earlier same-day entry "RSI threshold tie rule —
CONTRACT_GAP (classified, pinned both ways)" is SUPERSEDED. A semantic
edge may not be simultaneously PROVEN and CONTRACT_GAP; this closure
resolves it to exactly ONE classification: **PROVEN_EXACT**.

**Decision.** The executing EA is the canonical authority for the tie
rule. `SignalEngine.mqh::EvaluateRsiReversal` was NOT modified. Instead,
the Python reference strategy (`mql5bot.strategies.rsi_reversal`) and the
DSL reference spec (`examples/strategies/rsi_reversal.json`, bumped to
version 2) were aligned to the EA zone-escape semantics:

* Zones are STRICT: oversold = `r < Oversold`, overbought = `r >
  Overbought`. Exact ties (r == 30.0/70.0) sit OUTSIDE the zone.
* Escape from oversold fires LONG: prev < oversold (strictly) and now >=
  oversold. Escape from overbought fires SHORT: prev > overbought
  (strictly) and now <= overbought.
* The escaped direction is CARRIED (EA `m_state`): the neutral band
  [oversold, overbought] (inclusive) holds the last direction; while the
  current sample is inside an extreme zone the OUTPUT direction is 0
  (stand aside) while the carried state persists.
* NaN on either sample produces no action (EA: invalid signal). For RSI
  this occurs only during warmup where no position exists, so observable
  behaviour is identical.

**Why this direction of alignment.** The EA is what would execute real
money; aligning the Python/DSL references to it avoids ever claiming the
EA diverges from its own reference. No MQL5 change was made, so no
compile-verified EA session was required to justify an EA edit; only the
runnable references moved.

**Proof.** `tests/test_indicator_semantics.py`:
`test_rsi_zone_escape_python_is_the_ea_rule_exactly` enumerates the full
tie-inclusive (prev, cur) truth table against a verbatim EA transcription
(every case including exact 30/70 ties must agree), and
`test_rsi_zone_escape_neutral_hold_and_extremes_pinned` pins hold-through-
neutral, stand-aside-at-extremes, and NaN warmup suppression. These
supersede the former
`test_contract_gap_python_cross_vs_ea_zone_at_exact_ties`.
`tests/test_dsl_parity.py` validates the DSL spec bar-by-bar against the
Python strategy, so the DSL inherits the same closure.

**Residual (honestly classified).** The sandbox cannot compile or run
MQL5. That the COMPILED EA behaves as transcribed remains the owner's
Strategy-Tester leg (BLOCKED_OWNER_ENVIRONMENT). The sandbox-side semantic
classification for this edge is final: PROVEN_EXACT.

---

## 2026-09-07 — Volume dust-guard unified at 1e-9 step units in BOTH runtimes (Reality Gate §4 semantic closure)

**Finding.** A cross-runtime divergence existed in the volume floor
dust-guard: `python/mql5bot/symbolspec.py::normalize_volume` used
`int(lots/step + 1e-12)` while the MQL5 side
(`SpecNormalizeVolume`, SymbolSpec.mqh:165, and the Meta re-normalisation
in Mql5Bot.mq5 OnNewBar) used `MathFloor(lots/step + 1e-9)`. In the input
zone `(k·step − 1e-9·step, k·step − 1e-12·step)` the two runtimes floored
to DIFFERENT grid points — one full volume step apart, i.e. a potentially
decision-changing split (lot size, and at the min boundary even
accept-vs-reject). The prior parity grid never landed in that zone, so the
split was latent. Reproduced and pinned by
`tests/test_volume_contract.py::test_the_pre_fix_split_zone_is_decision_changing`
(computed with the historical constants; kept as the permanent regression
per §36).

**Decision.** The canonical dust guard is `1e-9` step units in BOTH
runtimes. Python `normalize_volume` is aligned to the MQL5 constant (the
MQL5 source is untouched — it cannot be compile-verified in this sandbox,
and its value was the derivably-correct one). The guard is DERIVED, not
arbitrary:

* Purpose: absorb IEEE-754 double rounding when the TRUE mathematical
  volume sits exactly on the grid but the computed quotient `lots/step`
  lands a few ulp below the integer `k` (budget/loss-per-lot division,
  meta scaling, repeated arithmetic).
* Lower bound (guard must cover division dust): a correctly rounded double
  division errs by ≤ 0.5 ulp of the quotient; the full sizing chain
  (budget construction + loss-per-lot + division) contributes ≤ ~2 · 0.5
  ulp(k). For quotients k = volume_max/volume_step ≤ 1e6 — the DERIVED
  rescue envelope, which covers every realistic MT5 symbol spec (FX
  100/0.01 = 1e4; metals/index ≤ 5e4; crypto 500/0.001 = 5e5) — the worst
  case is ≤ 1.2e-10, an order of magnitude inside the 1e-9 guard. The old
  Python `1e-12` only covered quotients ≤ ~4.5e3, i.e. it silently lost
  one step on on-grid sizes computed from realistic equity/loss quotients
  (undersizing). Beyond the envelope (exotic specs only) the pinned worst
  case is a ONE-STEP UNDERSIZE with cross-runtime parity intact — risk
  only shrinks; the guard can never mint volume upward.
* Upper bound (guard must stay representation-only): the guard can promote
  a strictly-below-grid input by at most 1e-9 of one step (≤ 1e-11 lots
  for step 0.01 — relative risk error ≤ 1e-9 of a step, economically
  zero). Any relaxation beyond ~1e-6 of a step would start swallowing
  economically meaningful sub-step volume and is forbidden.

**Contract (pinned by `tests/test_volume_contract.py`).**
`normalize_volume` maps raw lots → execution volume as: non-positive →
0.0; else floor to the step grid with the 1e-9 dust guard; a positive
input whose floored grid point is below `volume_min` yields `volume_min`
(the SIZER separately rejects below-min risk budgets before ever calling
the normaliser — `BELOW_MIN`; the normaliser's min-bump is reachable only
off the sizing path and mirrors MQL5 exactly); caps
`min(volume_max, volume_limit)` are themselves floored onto the grid; a
cap below the minimum yields 0.0. Python and the MQL5 transcription are
bitwise-equal over the full adversarial matrix — exact equality, not
tolerance. This is `REPRESENTATION_TOLERANCE` (double dust), explicitly
NOT an `EXECUTION_TOLERANCE`: no economic magnitude is ever absorbed.

**Classification of the historical split:** `DECISION_CHANGING` in the
abstract (one-step lot difference; accept-vs-reject at the min boundary),
reachability limited to inputs tuned to ≤ 1e-12 of a step or to double
dust at quotient scales > ~4.5e3 — after unification the split no longer
exists in either direction. Evidence class: `LOCAL_DETERMINISTIC_GATE`
(Python) + `SOURCE_BEHAVIOR` (MQL5 transcription; runtime leg stays
`BLOCKED_OWNER_ENVIRONMENT`).

---

## 2026-09-07 — Cross-event contract, EMA seed parity, and the RSI tie-rule CONTRACT_GAP (Reality Gate §12/§13/§14/§15 closure)

**Cross contract (fixed under explicit contract, regression-locked).**
`indicators.crossover` previously fired an event at the NaN→value warmup
boundary (a NaN predecessor compared as "below" via `np.roll` padding),
while the EA — after the NaN value-feed fix above — suppresses evaluation
until two valid samples exist. That was a cross-runtime signal divergence
on every RSI-strategy warmup. Fix: an event now requires BOTH the current
and the previous sample valid. Polarity pinned: +1 = crossed above, −1 =
crossed below; `crossunder(a,b) == −crossover(a,b)` elementwise; the three
spellings `crossover(a,b) < 0`, `crossunder(a,b) > 0`, `crossover(b,a) > 0`
denote the SAME event — proven elementwise over the full NaN-inclusive
truth table (`tests/test_indicator_semantics.py`). The earlier
`crossunder` docstring described the sign backwards; corrected (docs-only,
the DSL runtime never consumed the sign). No threshold or polarity moved.

**EMA seed parity — classification: FORMAL_MODEL_PARITY +
WARMUP_EQUIVALENCE, quantified (mission §12).** Python canonical EMA
(manifest contract-v1) uses the SMA seed (first valid bar n−1); the
platform-model iMA computes from bar 0 seeded at price[0] (seeding detail
= COMMUNITY_EVIDENCE; official docs do not publish it — the owner's tester
leg is the final arbiter). Measured on the FROZEN gold fixture
(`tests/test_ema_seed_parity.py`):

* The seed residue decays EXACTLY geometrically at the forgetting factor
  (1 − 2/(n+1)) per bar — measured vs theory agree to 1e-6 relative. This
  DERIVES the decay ratios instead of pinning arbitrary ones: EMA(10)
  residue shrinks (11/9)^30 ≈ 411.6× per 30 bars; EMA(30) shrinks
  (31/29)^30 ≈ 7.39× per 30 bars. Residue < 1e-6 price units by bar 19
  (fast) / 53 (slow) on this fixture.
* Decision audit: ema_crossover_ref desired positions are IDENTICAL
  between seed models from bar 29 to the fixture end; before bar 29 the
  Python model is flat by contract. Measured near-miss margin: min
  |fast−slow| separation from bar 29 = 6.62e-6 vs max seed residue
  4.84e-6 → 1.37× ON THIS FIXTURE. HONEST LIMITATION: this does not
  prove decision-neutrality for arbitrary data — a seed flip inside the
  first ~slow-period bars remains possible on other datasets and stays
  classified WARMUP until the owner's MT5 reconciliation settles the
  platform side. Convergence alone is NOT accepted as parity; the window
  and margin are the contract.
* `indicators.ema` seeding was NOT changed (mission: never silently).

**RSI threshold tie rule — CONTRACT_GAP (classified, pinned both ways).**
**SUPERSEDED 2026-09-07** by the PROVEN_EXACT closure at the top of this
log (Python + DSL aligned to the EA zone-escape rule). Kept for history.
The Python cross-event spelling fires when the previous sample EQUALS the
line then moves off it (`≤`→`>`), while the EA zone-escape requires the
previous sample STRICTLY in the zone (`<` then `≥`), and symmetrically at
the current tie. The difference exists ONLY when RSI lands EXACTLY on
30.0/70.0 — constructible in fixtures, effectively measure-zero on tick-
quantized broker data, but NOT provably unreachable. Both behaviours are
pinned elementwise (`test_contract_gap_python_cross_vs_ea_zone_at_exact_ties`);
closing the gap belongs to the three-way reference-parity workstream and
requires a compile-verified EA session — it was NOT closed by intuition
here. Everything else in the (prev,cur) ∈ {NaN, below, equal, above}²
matrix is contractually identical.

**State memory (§14) & extreme transitions (§15).** `crossover`/
`crossunder` are pure and stateless: repeated evaluation, restart (fresh
copy) and replay are bitwise identical; a one-bar mutation never changes
decisions strictly before it. Extreme→extreme single-bar jumps produce
exactly ONE event in the observed direction — bar-close sampling observes
no intermediate values BY DESIGN; documented, not "fixed".

---

## 2026-09-07 — Warmup policy fixed as deterministic NaN propagation; EMPTY_VALUE never reaches a comparator (Reality Gate §8–§10 closure)

**Finding (source audit, MQL5 leg = BLOCKED_OWNER_ENVIRONMENT).** The EA's
`SignalEngine.GetValue` returned `0.0` on `INVALID_HANDLE`/CopyBuffer
failure and passed `EMPTY_VALUE` (DBL_MAX — the official MQL5 marker for
uninitialized indicator buffer slots, mql5.com "Other Constants"; RSI(14)
first valid value is index 14 per the official "Applying One Indicator to
Another" article) straight through to the strategy comparators. The
`IsNaN()` guards in the five strategies were therefore dead code on those
paths, and three warmup phantom-signal classes existed at source level:

* RSI_REVERSAL — on the FIRST valid RSI bar, `rPrev == EMPTY_VALUE`
  compares as overbought, the "escape overbought" transition fires, and a
  phantom SELL is produced (unless RSI happens to be below oversold).
* BOLLINGER_REVERSAL — `EMPTY_VALUE` lower band compares `close < lower`
  → phantom BUY in the first period−1 bars.
* MACD_MOMENTUM — `EMPTY_VALUE` signal line compares `line < signal`
  → phantom SELL before the signal line exists.
* DONCHIAN_BREAKOUT — independent class: out-of-range `iHigh`/`iLow`
  return 0, fabricating a zero-width channel → phantom breakout before
  N+2 bars exist.
* EMA_CROSSOVER — no EMPTY_VALUE region (built-in iMA computes from bar
  0); its only warmup difference is the seed (§ EMA seed contract below).

The Python canonical strategies are NaN-padded and NaN-guarded (no signal
before readiness), so the split was a genuine cross-runtime signal
divergence — a certification blocker until fixed.

**Decision (smallest justified contract — no new policy invented).** The
project's warmup model is (C) **deterministic NaN propagation**: an
unavailable/uninitialized indicator value is NaN in BOTH runtimes, every
strategy suppresses evaluation on NaN, and a suppressed bar emits an
INVALID signal (EA) / zero desired position (Python). `GetValue` now maps
INVALID_HANDLE, CopyBuffer≤0, and EMPTY_VALUE to an IEEE NaN (runtime
0/0), activating the already-present `IsNaN` guards; `EvaluateDonchian`
gates on `Bars(symbol, tf) >= period + 2` (the channel's shift range).
This is the minimal change that makes the MQL5 side honour the SAME
contract the Python side and the gold-standard traces already implement —
nothing about thresholds, signal polarity or Meta behaviour moved.

**INIT_FAILED audit (§10).** `INIT_FAILED` is used ONLY for fatal EA
states, each with a logged reason: symbol-spec build failure, trading not
enabled (terminal/EA/account), SignalEngine handle creation failure
(missing indicator IS fatal), PositionGuard init failure, magic
allocation failure, TradeManager/Allocation/StateStore init failures.
Input validation uses `INIT_PARAMETERS_INCORRECT` (distinct category).
Data insufficiency is explicitly NOT fatal — it suppresses signals via the
NaN contract above. `INIT_FAILED` is not a catch-all validation
mechanism, and no new path was added.

**Readiness matrix (first valid bar, closed-bar shift-1 evaluation).**

| Indicator | Lookback | First valid (0-based) | Stateful | NaN behaviour | Requires previous | Platform init (evidence class) | Python init | Contract |
|---|---|---|---|---|---|---|---|---|
| iMA MODE_EMA | 0 | bar 0 (seed = price[0]) | recursive | no EMPTY region | yes (recursive) | computed from first bar (COMMUNITY_EVIDENCE; runtime = owner leg) | SMA seed at bar period−1 | WARMUP-classified seed difference (§ EMA entry) |
| iRSI(14) | 15 | bar 14 | Wilder recursion | EMPTY_VALUE bars 0..13 (OFFICIAL_DOCUMENTATION) | yes | EMPTY prefix (OFFICIAL_DOCUMENTATION) | SMA seed, first valid bar 14 | NaN until first valid; suppressed |
| iATR(14) | 15 | bar 14 (Wilder) | Wilder recursion | EMPTY prefix | yes | EMPTY prefix (OFFICIAL_DOCUMENTATION, same mechanism) | Wilder, first valid bar 14 | NaN until first valid |
| iBands(20) | 20 | bar 19 | none | EMPTY bars 0..18 | no | EMPTY prefix (OFFICIAL_DOCUMENTATION) | SMA±k·σ, first valid bar 19 | NaN until first valid |
| iMACD(12,26,9) | main 0 (platform) / slow−1 (Py); signal +signal−1 | Py: main bar 25, signal bar 33 | recursive | EMPTY prefix where undefined | yes | main computed from bar 0 (seeded like iMA); signal EMPTY until defined (COMMUNITY_EVIDENCE; owner leg) | EMA-diff valid bar slow−1; signal valid bar slow+signal−2 | NaN until first valid; WARMUP-classified window difference vs platform (gold strategy unaffected) |
| Donchian(N) | N+1 bars | closed-bar index N (EA gate: `Bars >= N+2`) | state var | n/a (raw highs/lows) | state persists | Bars gate (this decision) | NaN-padded channel, valid from index N | invalid until window fully defined; both runtimes use the SAME prior-N window |

Evidence classes per §11: OFFICIAL_DOCUMENTATION (EMPTY_VALUE semantics,
RSI first-valid index), SOURCE_BEHAVIOR (the EA source as written),
COMMUNITY_EVIDENCE (iMA/iMACD seeding specifics — not settled until the
owner's tester leg), TESTED_RUNTIME = none in this sandbox (no MetaEditor)
→ those legs stay `BLOCKED_OWNER_ENVIRONMENT`.

**Regression lock.** `tests/test_indicator_readiness.py` (matrix +
phantom-signal reproduction of the OLD behaviour + proof the fixed
semantics suppresses), `tests/test_mql5_sources.py::
test_signal_engine_nan_warmup_contract` (source pins).

---

## 2026-09-04 — 0–20 execution plan: Phase 9 environmental blocker, parallel-research protocol (documented decision)

**Decision.** The canonical 0–20 execution plan (owner-pasted, governs from
this date) requires each phase's EXIT GATE before the next begins, and any
gate that cannot pass must STOP with a report.  Phase 9 (MT5 Truth Engine)
cannot pass in this Linux sandbox: its gate is "PASS only if on Windows:
EA compiles, tester executes, raw report preserved, parser reads a real
report".  Python-only research phases 10–13 therefore proceed **in
parallel** while Phase 9 stays **OPEN** — this mirrors the repo's standing
pattern (MetaEditor verification is an owner round-trip; the Compile line
of PROGRESS.md has reported NOT VERIFIED every phase and is never guessed).
Nothing claiming MT5 execution truth is produced: phase-10 benchmarks and
phase-11+ statistics remain FAST-engine research results, explicitly not
final certification until the Phase-9 owner round-trip passes and the
Truth-Engine reconciliation exists.  Phase order otherwise unchanged;
re-opening this waiver requires a new DECISIONS entry.

---

## 2026-09-04 — Headless tester: deterministic contract + locale-tolerant report parsing (AEGIS Phase 2)

**Decision.** The headless Strategy Tester stack (`python/mql5bot/mt5tester.py`,
`tools/run_mt5_backtest.{py,ps1}`) fixes symbol/timeframe/model/dates/
deposit/currency/leverage explicitly per run and derives a deterministic
report stem, but does NOT pretend to control spread: MT5 tester applies the
broker symbol conditions (spread source, tick history). Cost scenarios
(BASE/STRESSED/SEVERE) are applied in the Python execution model and
compared against MT5 runs with documented tolerances (Phases 4/6) — never
presented as identity. MT5 tester HTML reports are locale-labelled; the
parser therefore (a) preserves every raw label/value pair, (b) matches
metrics through English synonym labels case-insensitively, and (c) treats
the report file as the source of truth when any ambiguity remains. The
.5f engine enumeration per MetaTrader 5 docs is 0 = every tick, 1 = 1-minute
OHLC (default), 2 = open prices, 3 = every tick on real ticks, 4 = real
ticks. Raw `.htm` reports are always preserved before parsing; exit code 3
guards `run`/`batch` on non-Windows hosts instead of silently skipping.
Owner round-trip remains mandatory before any backtest claim (HANDOFF §10).

## 2026-09-04 — Compile round-trip gates on real compiler output (AEGIS Phase 1)

**Decision.** `tools/compile.ps1` verifies success only when the produced
`.ex5` exists AND is newer than the compile start time, with the MetaEditor
log captured verbatim (per-file logs in `%TEMP%`, one combined reproducible
log with SHA-256s in `logs/`). English `error`/`warning` tokens are counted
when present; non-English MetaEditor builds produce no tokens, so the
`.ex5` freshness check is authoritative and the raw log is always kept for
human review — a stale `.ex5` from an earlier build is never accepted as
proof. `-Strict` fails the run on any warning token.

---

## 2026-09-04 — Keep the committed Mql5Bot tree in place while Aegis releases land (DEV)

**Decision.** The canonical layout in SPEC §6 (`ea/MQL5/...`, `factory/...`,
`schemas/`, `research/`, docs set) is the destination architecture, but this
repository already contains a working, tested, two-language stack under
`mql5/`, `python/`, `tests/`. We will NOT rename/move/restructure that tree as
a first step: restructuring without a compile-capable environment would
destroy working functionality for zero behavioural gain (audit §1, §7).

**Rationale.** Release work is incremental and evidence-based. The Mql5Bot EA
becomes the Release-A seed: its files grow into SPEC §8 behaviour, and new
canonical models are first implemented in Python where they can be unit-tested
in this sandbox, then ported to MQL5 in compile-verified sessions (audit §17).
SPEC §8 class/file names (e.g. `SymbolSpec.mqh`) will be used for new MQL5
files when they are added, inside the existing `mql5/Include/Mql5Bot/` tree.

**Cost.** The layout differs from SPEC §6 until a later consolidation release;
`docs/IMPLEMENTATION_AUDIT.md` §1 maps current paths. The SPEC §6 layout
remains the target for a dedicated, separately planned refactor that keeps
`git history` intact and is verified by the MQL5 unit-test harness.

## 2026-09-04 — Python-first canonical risk/identity models (DEV)

**Decision.** Release-A's "injected `SSymbolSpec` risk math", "volume/price
normalisation", and "FNV-1a magic derivation" are implemented first as pure,
dependency-light Python modules in `python/mql5bot/` (canonical model +
synthetic-spec tests), and the MQL5 port must match them. The existing
`CRiskManager`/`CTradeManager` code is left running untouched until the port
lands in a compile-verified session.

**Rationale.** SPEC §14 requires PositionSizer tests on synthetic broker specs
(EURUSD 5-digit, USDJPY, XAUUSD, US30-like, BTCUSD-like; clamping; insufficient
margin). MetaEditor is unavailable in this environment, so MQL5 changes cannot
be compile-verified here; the Python twin is the verifiable specification of
the arithmetic. This mirrors the existing, working strategy-parity approach
(README "Strategy ↔ backtest parity") and extends it to risk code. Keeping the
old EA untouched avoids regressions (task rule: never destroy working
functionality).

**Cost.** A short window where the live EA's internal math and the canonical
Python model are not yet byte-identical; the EA remains demo-only per its own
documentation, and the port task is tracked in the audit's order list (§17.2).

## 2026-09-04 — SPEC.md §19 (external references) reconciliation (DOC)

**Decision.** The committed `docs/SPEC.md` ends at §18 "OUTPUT STYLE".
HANDOFF.md §4.17 refers to "SPEC §19" for the external-repository policy
(paper_trading_view, BTC multi-horizon builder, MT5 docker/data-bridge,
AutoTradeSignal/core, highcharts). Policy is applied as written in HANDOFF §4
and in the work-session brief: reference-only, no third-party trading code
imported, no Highcharts, no Selenium in the core. When SPEC.md is next
edited, fold this section in as its final numbered section.

## 2026-09-04 — Version naming (DOC)

**Decision.** The committed code labels itself Mql5Bot "1.0.0"
(`Config.mqh`, `Mql5Bot.mq5`, `CHANGELOG.md`). Aegis `v1.0.0` per SPEC §5.6 is
the end of Release E. The code's own version string keeps tracking the
committed EA codebase; Aegis release tags (`A-ea-core` … `v1.0.0`) are
separate and follow SPEC.

---

## 2026-09-04 — Engine state hardening (never soften a halt or pause)

**Decision.** `ENGINE_NO_NEW_TRADES` (daily-loss breach) is the *soft* pause
and `ENGINE_HALT` (drawdown kill switch, SL-guard escalation, manual trip)
is the *hard* stop. Only a day rollover clears the daily-loss pause; the
kill switch is cleared ONLY by an explicit one-shot reset (input
`InpResetKillSwitch` + GlobalVariable `reset_ack` edge — see state-store
commit) — never by equity recovery and never by a rollover. A daily-loss
breach while a guard pause or the halt is active must NOT soften that state
(the EA only applies the daily pause from `ENGINE_NORMAL`). Mirrored in
`python/mql5bot/failsafe.py`.

## 2026-09-04 — Cold-state persistence: strict text, delete-then-write

**Decision.** Internal EA state files (`AEGIS_STATE v1` ticket registry,
`MAGICMAP v1`) stay strict line-based text until the EA↔Factory JSON
contract ships (a reviewed JSON writer lands with that contract). Saves are
delete-then-write because `FileOpen(FILE_WRITE|FILE_READ)` does not
truncate — stale tail rows would resurrect removed tickets/ids on load.
Reads are strict: a corrupt header quarantines the file aside (never
applied partially); malformed rows are skipped. Hot state (kill switch,
reason, day key, day-start equity, equity peak) rides GlobalVariables so a
restart always restores it; management flags (`partialDone`, `beDone`) are
persisted per `POSITION_IDENTIFIER` in the cold registry — never in the
position comment (brokers overwrite comments).

---

## Earlier decisions carried from HANDOFF.md §4 (kept; [SPEC]-consistent)

1. **[SPEC §3.1]** Signal/Risk separation: strategies emit signals only;
   meta-layer and Risk Engine veto; Factory never trades (files only).
2. **[SPEC §3.2]** Every position always has an SL; failure to set SL → close +
   CRITICAL + alert.
3. **[SPEC §3.3, §3.10]** Query broker specs at runtime; all risk math on an
   injected `SSymbolSpec` struct (unit-testable with synthetic specs).
4. **[SPEC §3.9]** Stable identity: Magic = FNV-1a hash of `strategy_id` into a
   reserved range, persisted in a registry; never index-based.
5. **[SPEC §3.8]** Attribution/management state persisted by
   `POSITION_IDENTIFIER` in files, NOT in the position comment (brokers
   overwrite comments).
6. **[SPEC §3.4]** No `Sleep()`; retries via a `RetryQueue` processed in
   OnTimer with backoff.
7. **[SPEC §9]** Strategy Tester: DSL specs delivered as one bundle via
   `#property tester_file`; WebRequest/Calendar skipped in tester.
8. **[SPEC §2]** Releases A→E gated by DoD; release N+1 starts only after N is
   tagged. Compiled AND DSL copies of the 4 reference strategies with a
   bar-by-bar parity test (golden test of the DSL engine).
9. **[SPEC §12.2]** Combination default = `weighted_netting` (one book position
   per symbol; opposite signals netted; pro-rata attribution).
10. **[SPEC §12.2]** Weights = gate × regime_fit × performance × correlation ×
    drift factors; adaptive part clamped [0.25, 1.5], ≤ ±15 %/day; hard zeros
    allowed; daily cadence; ≤10 meta parameters.
11. **[SPEC §10.4]** Gate 3 demo = ≥ 4 weeks AND ≥ 30 trades (low-frequency
    exception: ≥ 8 weeks AND ≥ 15 trades, flagged). OOS budget: one look per
    strategy version.
12. **[SPEC §8.C]** Kelly sizing capped ≤ 0.25 Kelly, off by default;
    martingale forbidden; grid/averaging off by default and hard-capped.
13. **[SPEC §8.H]** Two separate Telegram bot tokens (EA vs Factory).
14. **[SPEC §4]** Factory: Python 3.11+, FastAPI, SQLAlchemy+Alembic, SQLite,
    Jinja2+HTMX (no JS framework), binds 127.0.0.1, password from env; MQL5
    compile is local-only (PowerShell), GitHub CI is Python-only.
15. **[SPEC §8.A]** Server GMT offset estimated from
    `TimeCurrent() − TimeGMT()` when connected, persisted.
16. External repos: read-only inspiration; no third-party trading code; no
    Highcharts (licensing) — if interactive charting is ever needed,
    TradingView lightweight-charts only, recorded here first.

## Open questions

- None blocking. (Owner-side compile logs for MQL5 batches are required before
  those batches are considered done — see audit §17.)

## ML-1..ML-7 — Meta Layer contract 1.0.0 → 1.1.0 (2026-09-05)

Pre-implementation contract hardening (mandate Phase 1).  All seven
corrections resolve ambiguity or non-determinism that would have made
the implementation contradictory or order-dependent; none weakens a
safeguard.  Full rationale in `docs/META_LAYER_IMPLEMENTATION_SPEC.md`.

- **ML-1 (correlation simultaneity).**  The 1.0.0 wording
  ("overlapping exposure with already-weighted strategies") is
  sequential and order-dependent: A→B→C ≠ C→A→B.  Corrected to a
  SIMULTANEOUS snapshot: one pairwise correlation matrix over all
  eligible candidates × the PREVIOUS decision's persisted weights
  (equal prior when absent) → one raw penalty vector.  Permutation
  invariance is a pinned test property, not an implementation
  accident.
- **ML-2 (missing data classified, not neutralized).**  1.0.0 said
  missing source → NEUTRAL 1.0.  That is a free pass: an uncertified
  or unmonitored strategy would quietly earn full weight.  Corrected
  to: REQUIRED source missing ⇒ INELIGIBLE (UNCERTIFIED); OPTIONAL
  source missing for one strategy ⇒ bounded conservative fallback
  (the zero-observation value) + journal flag; missing for ALL ⇒
  global equal-weight fallback.  Neutral 1.0 is never granted.
- **ML-3 (all-zero vs global failure).**  The 1.0.0 pair (hard zero /
  equal-weight fallback) left the "all raw scores == 0" state
  undefined.  Corrected: zero WITH source present is a HARD ZERO
  (ineligible, never resurrected); all candidates hard-zero ⇒ SAFE
  HOLD, not equal weight.  Equal weight exists ONLY for global
  source failure.
- **ML-4 (normalization pipeline made explicit).**  "Normalization
  may only REDUCE weights" was imprecise (a proportional share of a
  budget can exceed a small raw product).  Replaced by the normative
  pipeline: mask → proportional share → cap (reduce) → bounded
  redistribution into uncapped ELIGIBLE only → budget scale →
  constraints (reduce) → change limit.  Zeros never receive mass.
- **ML-5 (determinism clauses).**  strategy_id-ascending ordering,
  lexical tie-breaks, canonical JSON serialization, fixed float
  policy — byte-identical journals for identical inputs.
- **ML-6 (eligibility taxonomy + activation states).**  Named
  INELIGIBLE reasons (UNCERTIFIED, CERT_FAILED, REGIME_FORBIDDEN,
  REGIME_UNKNOWN, DRIFT_BLOCK, STALE_DATA, DISABLED, COOLDOWN,
  KILL_SWITCH, CONFIG_INVALID) and the DISABLED→SHADOW→DEMO→
  LIVE_SMALL→ACTIVE ladder with explicit, audited, never-automatic
  transitions (default DISABLED).
- **ML-7 (daily weight-change limit).**  New clause controlling
  weight oscillation between decisions (config `max_weight_change`,
  default off).  Hard zeros always take effect immediately;
  re-entry restarts from zero.  Risk Engine remains the final
  authority for every order (unchanged, restated).

## ML-8 — EA allocation consumer & sizing seam (2026-09-05)

Implementation decision under the UNCHANGED SPEC contract
(`in/allocation.json`, line 107).  (a) `mql5/Include/Mql5Bot/Allocation.mqh`
is a strict consumer of exactly the documented schema: schema_version
"1", digest, computed_at (UTC ISO), per-strategy id/weight; stale
(>7 days) decays to the caller's base gate weight; missing/malformed
falls back to the base gate weight — never "last known good" and
never silently applied.  (b) The single EA seam scales risk-approved
lots AFTER `RiskManager.GetLots` and BEFORE any order path —
reduce-only by construction; SL/TP, risk %, limits and the kill
switch are untouched.  (c) No Meta Layer math is duplicated in MQL5
(weights are computed only in `meta_layer.py` and consumed in the EA;
parity is by construction, pinned structurally).  No contract revision
was required.

## ML-9 — Exposure clamp vs Risk-Engine authorities (contract 1.1.0 → 1.1.1)

Empirical-gate mission Phase 1 found that §5.2 ("Daily clamp … clamped
to the portfolio daily-loss budget enforced by the Risk Engine") could
be read as if the Meta Layer computes or targets the daily-loss budget.
It does not and must not: the four controls are DISTINCT and remain
owned as follows — (A) meta weight-change limit = Δweight between
decisions (Meta); (B) daily-loss limit = maximum permitted account
loss (Risk Engine ONLY); (C) drawdown kill-switch = maximum equity
drawdown (Risk Engine ONLY); (D) portfolio exposure cap = maximum
allocation/exposure (Meta owns its ALLOCATION budgets; the Risk
Engine owns the hard account exposure limits).  §5.2 is reworded
accordingly: the layer's clamps are its own allocation budgets; no
daily-loss or drawdown quantity is an input, parameter, or branch of
the Meta Layer.  The implementation already matched the corrected
semantics (no such input exists in code); this was a WORDING fix, and
a regression test now pins that the layer's surface cannot express a
daily-loss or drawdown authority.

## ML-10 — Version consistency: declared contract version corrected to 1.1.1 (2026-09-05)

Audit (meta-production mission, Phase 1) found the Python producer
(`meta_layer._versions()`) and the MQL5 consumer header declaring contract
**1.1.0** while the implemented semantics have been contract **1.1.1**
(ML-9, authority split) since `0a722f1`. Resolution: contract **1.1.1** is
the single authoritative version; the producer now emits
`CONTRACT_VERSION = "1.1.1"` from one code constant; `Allocation.mqh` and
`Mql5Bot.mq5` references updated. No contract clause changed; the
allocation wire format is unchanged (`body.schema_version = "1"`);
readers gate on `decision_version`/`schema_version`, never on
`contract_version`, so journals/files remain compatible both directions.
The contract document's stale lifecycle note (claiming no implementation
exists) is replaced by the real status: IMPLEMENTED — SOFTWARE PASS;
EMPIRICAL VALIDATION: SHADOW-READY; MT5/demo evidence PENDING (owner).
Enforced by `tests/test_docs_consistency.py`.

---

## D-CONV-1..6 — Final convergence decisions (2026-09-06)

1. **Entry chain is ONE function** (`discovery/entry_chain.py`) implementing the §57 event order; non-strategy origins are refused BEFORE any gate. Rationale: veto order must be inspectable in a single place; per-layer checks scattered across call sites allowed "who blocks whom" to drift.
2. **Approval records bind evidence hash + policy version; machine actors can never carry human_approval=True.** Rationale: §32 structured approvals are the last human checkpoint — a forgeable flag is worse than none.
3. **Governor applies decay×ramp AFTER gross-target normalization.** Rationale: safety multipliers that get renormalized away are decorative; degradation must reduce REAL allocation.
4. **Campaign progress is bound to policy hash AND dataset hash; either mismatch refuses continuation.** Rationale: §15 data-boundary — continuing research across a data change silently invalidates every stored comparison.
5. **Correlation classification distinguishes UNKNOWN instead of defaulting to 0 or 1.** Rationale: §26 — missing evidence must not impersonate an answer; portfolio admission already treats UNKNOWN conservatively.
6. **Research runner is injected into the console; without it campaigns are registered PAUSED with a visible warning.** Rationale: a fake "research done" is a §0 violation (no silent approximation).
