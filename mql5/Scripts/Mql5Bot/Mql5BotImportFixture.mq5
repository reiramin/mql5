//+------------------------------------------------------------------+
//|  Mql5BotImportFixture.mq5 - frozen gold fixture -> custom symbol  |
//|                                                                  |
//|  STATUS: SOURCE-ONLY on Mac; the owner compiles it (tools\       |
//|  compile.ps1 -Strict) and runs it. The IMPORT RESULT is          |
//|  OWNER-PENDING until this script reports refused=false with a     |
//|  round-trip dataset hash equal to the manifest pin.              |
//|                                                                  |
//|  THE BLOCKER IT CLOSES: the repo has no custom-symbol path (no    |
//|  CustomSymbolCreate / CustomRatesUpdate anywhere), so the frozen  |
//|  Gold fixtures could never become Strategy-Tester data and the    |
//|  gate's dataset-import stage was unrunnable. This script makes a   |
//|  custom symbol out of a COMMITTED fixture and PROVES it faithful. |
//|                                                                  |
//|  Inputs are ONLY committed/owner-staged files copied under        |
//|  MQL5\Files: the fixture CSV (the EXACT bytes Python hashed), its  |
//|  gold manifest (broker_spec + dataset_hash), and the stage-3      |
//|  SymbolSpec export. NO CopyRates of live history, no chart, no     |
//|  invented properties: every symbol property comes from the        |
//|  manifest or the SymbolSpec export, and a missing one REFUSES.    |
//|                                                                  |
//|  CHART-INDEPENDENT: the symbol and timeframe are taken ONLY from  |
//|  the inputs (InpSymbolName) and the manifest ("timeframe"). The    |
//|  script never reads the attached chart's predefined symbol/period  |
//|  variables nor the chart symbol/period query functions; it         |
//|  behaves identically no matter which chart it is dropped on (the   |
//|  owner gate runs it from a BTC,H1 chart).                         |
//|                                                                  |
//|  SYMBOL NAME (EURUSD.G1): MT5 restricts custom-symbol names to     |
//|  Latin letters/digits and the punctuation ". _ & #" only, <=32    |
//|  chars incl. the terminating 0. "EURUSD.G1" (9 chars) satisfies    |
//|  this. The script validates the name and REFUSES before creating   |
//|  anything if it does not. The custom-symbol path is InpSymbolGroup |
//|  ("Mql5Bot\\gold"), placing it under Custom\Mql5Bot\gold; it       |
//|  cannot collide with the broker's own "EURUSD" (different name),   |
//|  and if a NON-custom (broker) symbol of the same name already      |
//|  exists the script REFUSES rather than shadow it.                 |
//|                                                                  |
//|  WHY "EURUSD.G1" AND NOT "GOLD1_EURUSD" (R7, gate_run9): a custom  |
//|  symbol is Forex by default, and in Forex calc mode MT5 DERIVES   |
//|  the base and profit currencies from the first/second three-char  |
//|  chunks of the NAME (MQL5 book, "Custom symbol properties":       |
//|  name "Dummy" -> pseudo-currencies "Dum"+"my"). "GOLD1_EURUSD"     |
//|  derived base "GOL"/profit "D1_", which failed verify_properties   |
//|  even though CustomSymbolSetString returned ok=true (last_error 0):|
//|  in Forex mode base/profit currencies "cannot be set" and the set  |
//|  call reports success WITHOUT taking effect. The documented Forex   |
//|  naming form is XXXYYY + optional suffix, so "EURUSD.G1" makes     |
//|  MT5's own inference correct by construction: base "EUR", profit    |
//|  "USD". Margin currency IS settable and is set + read-back as      |
//|  before. See docs/DECISIONS.md 2026-09-19 (R7).                    |
//|                                                                  |
//|  MT5 NAME/PATH RULE (documented + enforced): custom-symbol names   |
//|  are unique across the ENTIRE symbol hierarchy, so SymbolExist is  |
//|  a GLOBAL existence check (not per-folder). Also, CustomSymbolCreate|
//|  treats a symbol_path whose LAST element equals the symbol name as  |
//|  the symbol itself rather than a folder; the script therefore       |
//|  REFUSES when the last element of InpSymbolGroup equals             |
//|  InpSymbolName (an ambiguous name/group pair) before creating.     |
//|                                                                  |
//|  IDEMPOTENCY -- VERIFY-FIRST SYMBOL-STATE CONTRACT (R10, gate_run13;|
//|  supersedes the R9 drop-first three-outcome contract; errs 5304     |
//|  ERR_CUSTOM_SYMBOL_EXIST / 5306 selected-state / 4305               |
//|  ERR_MARKET_SELECT_ERROR): a prior run can leave the custom symbol  |
//|  behind, and a SUCCESSFUL run deliberately ENDS with                |
//|  SymbolSelect(sym,true) so the tester can see it. R9 answered by    |
//|  dropping the survivor (or adopting after a failed drop), which     |
//|  REQUIRED a deselect -- and gate_run13 measured that deselect       |
//|  itself failing with 4305 ERR_MARKET_SELECT_ERROR ("error adding    |
//|  or deleting a symbol in Market Watch"): ChartClose is              |
//|  ASYNCHRONOUS -- it queues a close command and returns, the chart   |
//|  is NOT gone when the call returns -- so the immediate deselect ran |
//|  while MT5 still considered the symbol in use. R10 removes the      |
//|  need to deselect at all on the steady-state re-run: property       |
//|  WRITES are the ONLY thing that requires a deselected symbol (the   |
//|  5306 rule), and on a re-run the survivor was configured by the     |
//|  previous run from the SAME manifest, so every property already     |
//|  holds the correct value -- rewriting already-correct values is     |
//|  what MANUFACTURED the deselect requirement. Bars never need it:    |
//|  CustomRatesDelete/CustomRatesUpdate work on a SELECTED custom      |
//|  symbol (the normal live-feed path for custom symbols). The symbol  |
//|  STATE is resolved fail-closed BEFORE any mutation:                 |
//|   1. CREATED-FRESH: no symbol of the name exists ->                 |
//|      CustomSymbolCreate + the full property application.            |
//|      symbol_state="created_fresh".                                  |
//|   2. ADOPTED-VERIFIED: a custom survivor exists and EVERY settable  |
//|      property reads back EQUAL to the manifest spec -- checked      |
//|      FIRST, before touching anything (the R8 CALCULATED tick        |
//|      values are excluded: not settable (5307), they must never      |
//|      force a rewrite). ZERO property writes, NO deselect, Market    |
//|      Watch untouched: straight to the bars. This is the steady-     |
//|      state re-run and it needs NOTHING from Market Watch.           |
//|      symbol_state="adopted_verified".                               |
//|   3. ADOPTED-REAPPLIED: the survivor exists but N>0 properties      |
//|      DIFFER from the spec. Only then is a deselect required: close  |
//|      any OTHER chart on the symbol (never the script's own), POLL   |
//|      until no chart displays it (bounded <=10 x Sleep(300) --       |
//|      ChartClose is asynchronous, never assume the close happened),  |
//|      retry SymbolSelect(sym,false) bounded (<=5 x Sleep(300),       |
//|      return + _LastError checked, LAST failure reported), then      |
//|      re-apply through the SAME shared ApplySymbolProperties         |
//|      sequence a fresh create uses (never a second partial writer).  |
//|      symbol_state="adopted_reapplied" +                             |
//|      "adopt_properties_rewritten":N (the count that differed and    |
//|      forced the rewrite).                                           |
//|   4. REFUSED-BECAUSE-UNDESELECTABLE: differing properties REQUIRE   |
//|      a deselect and the hardened release cannot obtain one --       |
//|      typically this script's OWN chart displays the symbol (it can  |
//|      never be closed, and ChartSetSymbolPeriod on the chart a       |
//|      script is running on TERMINATES that script, which would kill  |
//|      this importer mid-run and produce no JSON at all, worse than   |
//|      a clean refusal, so it is NEVER attempted) -- or the deselect  |
//|      still fails after the bounded retry (4305). The record names   |
//|      the failing call, its _LastError, and the operator             |
//|      remediation: close any chart on the symbol in the terminal,    |
//|      then re-run the gate.                                          |
//|  Either adopt path then wipes ALL bars (CustomRatesDelete + zero-   |
//|  bar VERIFY -- no bar from a prior fixture may survive), rewrites   |
//|  them from the fixture, and runs the UNCHANGED read-back            |
//|  verification + round-trip dataset-hash check. Adoption is accepted |
//|  only by passing exactly the evidence a fresh create must pass --   |
//|  the gate's guarantee comes from that verification, not from the    |
//|  symbol being new. A NON-custom (broker) symbol of the same name    |
//|  still refuses untouched (never shadowed).                          |
//|  RUNNING THE GATE TWICE IN A ROW MUST PRODUCE IDENTICAL RESULTS --  |
//|  the second run adopts the verified survivor with zero Market-Watch |
//|  traffic and passes on identical evidence; the symbol_state field   |
//|  names which path ran, so an adopted import can never look like a   |
//|  fresh create.                                                      |
//|                                                                  |
//|  err=5306 FAMILY (custom-symbol STATE / VALUE errors, 53xx):       |
//|   - STATE: a symbol SELECTED in Market Watch cannot be deleted     |
//|     (5306) or have its properties changed. The script therefore    |
//|     deselects the symbol (SymbolSelect(sym,false)) BEFORE any      |
//|     delete or CustomSymbolSet* -- and, since R10, only when a      |
//|     write is actually REQUIRED -- and selects it (SymbolSelect(...,|
//|     true)) only AFTER every property is set and the bars written.  |
//|     A stale prior custom symbol is resolved by the verify-first    |
//|     contract above (create / adopt-verified / adopt-reapplied /    |
//|     undeselectable refusal).                                       |
//|   - VALUE: a property value from the SymbolSpec/manifest may be    |
//|     out of the range MT5 accepts (5308 ERR_CUSTOM_SYMBOL_PARAMETER_|
//|     ERROR, "a wrong parameter while setting the property"; NOT     |
//|     5307, which is a read-only PROPERTY). Properties are set ONE   |
//|     AT A TIME; the return of EACH call is checked and, on failure, |
//|     the diagnostic names the property, its enum, its value, its    |
//|     source field and _LastError. A property is never silently      |
//|     skipped -- a skipped property means the symbol is not the      |
//|     certified one, so any failure REFUSES.                        |
//|   - VALUE ORDERING (5308, gate_run8): a fresh custom symbol starts |
//|     with volume_min/max/step all 0, so setting SYMBOL_VOLUME_MIN   |
//|     (0.01) BEFORE max/step is an inconsistent intermediate state   |
//|     (min>max=0, min not a multiple of step=0) that MT5 rejects     |
//|     with 5308. The docs give no ordering rule, so the volume       |
//|     family is written MAX -> STEP -> MIN -> LIMIT: MIN is only     |
//|     ever validated against the REAL broker ceiling and grid, and   |
//|     every intermediate symbol state stays internally consistent.   |
//|     More generally every property is ordered so no partially-set   |
//|     symbol is ever internally inconsistent.                       |
//|                                                                  |
//|  TICK-VALUE ECONOMICS (err=5307 ERR_CUSTOM_SYMBOL_PROPERTY_WRONG): |
//|  gate_run7 measured CustomSymbolSetDouble REFUSING                 |
//|  SYMBOL_TRADE_TICK_VALUE_PROFIT with last_error 5307. The MQL5     |
//|  docs say why: 5307 is "An invalid custom symbol property"         |
//|  (Runtime Errors table), and the MQL5 book (Custom symbol          |
//|  properties) states "not all properties are allowed to change.     |
//|  When trying to set a read-only property, we get the error         |
//|  CUSTOM_SYMBOL_PROPERTY_WRONG (5307)". SYMBOL_TRADE_TICK_VALUE_    |
//|  PROFIT and SYMBOL_TRADE_TICK_VALUE_LOSS are documented in         |
//|  ENUM_SYMBOL_INFO_DOUBLE as "CALCULATED tick price for a           |
//|  profitable/losing position" -- the terminal DERIVES them; they    |
//|  are not settable storage. SYMBOL_TRADE_TICK_VALUE ("Value of      |
//|  SYMBOL_TRADE_TICK_VALUE_PROFIT") IS settable (it is named in the  |
//|  CustomSymbolSetDouble history-reset note) and gate_run7 set it    |
//|  successfully. DESIGN DECISION (docs/DECISIONS.md 2026-09-19):     |
//|  this script NEVER calls CustomSymbolSet* on the two calculated    |
//|  properties. It sets SYMBOL_TRADE_TICK_VALUE from the manifest     |
//|  tick_value_profit and then, AFTER selection + bars, READS BACK    |
//|  the terminal-DERIVED _PROFIT/_LOSS (bounded, Sleep-free retry).   |
//|  R8 SCOPE (gate_run10): these calculated values are derived lazily |
//|  from a pricing context; a bars-only Forex custom symbol reads     |
//|  them back as 0 (nothing to derive from). That is a NAMED, SCOPED  |
//|  limitation, NOT a refusal: the Gold legs certify strategy logic + |
//|  execution path on the fixture, while broker tick-value ECONOMICS  |
//|  are certified separately by stage-3 broker parity + the           |
//|  OrderCalcProfit witness in RiskManager. The read-back is RECORDED |
//|  for transparency (available/ok per property in derived_tick_      |
//|  values) but NEVER gates stage 4 -- blocking here would refuse a   |
//|  symbol whose economics a stronger gate already certifies.        |
//|                                                                  |
//|  READ-BACK CONTRACT (verify_properties): after every property is   |
//|  set and the bars are written, EVERY set property is read back     |
//|  via SymbolInfoInteger/Double/String and compared to the value     |
//|  that was set; ANY divergence REFUSES. A skipped or silently       |
//|  mutated property can therefore never masquerade as set.          |
//|                                                                  |
//|  OBSERVABILITY: the FIRST action of OnStart is a Print() banner    |
//|  naming EVERY resolved input and the relative+absolute output path |
//|  ("[import] STARTUP ..."), so the gate's terminal-log backstop     |
//|  names the cause even when no JSON is ever written (sandbox        |
//|  refusal, undelivered parameters...). EVERY outcome writes a JSON  |
//|  diagnostic. The output path is taken from InpOutFile -- the EXACT  |
//|  path the gate passes in (never a default the script guesses); a    |
//|  manual run without InpOutFile falls back to                        |
//|  <InpOutDir>\<symbol>.json. MQL5 SANDBOX: FileOpen resolves ONLY    |
//|  RELATIVE paths under MQL5\Files, so an absolute InpOutFile could   |
//|  never be written; it is detected up front, Printed loudly, and     |
//|  replaced by the relative fallback so the diagnostic still lands    |
//|  where the sandbox allows. Every FileOpen failure Prints the path   |
//|  and _LastError to the terminal log. The JSON is                    |
//|  written on EVERY exit path -- especially every early refusal,      |
//|  which previously wrote nothing usable. The record carries:       |
//|   {"refused":bool,"symbol":...,"stage":...,"last_error":int,      |
//|    "failed_call":...,"failed_property":<enum name>,               |
//|    "failed_value":...,"failed_source":<manifest/spec field>,      |
//|    "properties":[{"enum","value","source","ok","last_error"}...], |
//|    "error":...}                                                   |
//|  Every record ALSO names which symbol-state path ran (R9/R10):    |
//|    "symbol_state":"unresolved"|"created_fresh"|"adopted_verified"| |
//|    "adopted_reapplied" and, on the adopt paths,                    |
//|    "adopt_properties_rewritten":N (0 = verified in place, nothing  |
//|    written). The state is set ONLY when the named path has         |
//|    actually happened; a refusal reports the state it was in when   |
//|    it refused ("unresolved" until a path completes), never a state |
//|    it aspired to -- an adopted import is a PASS, but its evidence  |
//|    must never look like a fresh create.                            |
//|  Every record ALSO carries the read-back evidence:                |
//|    "verified_properties":[{"enum","expected","readback","ok"}...] |
//|    "derived_tick_values":{"trade_calc_mode",                      |
//|        "limitation":<named scope>,                                 |
//|        "properties":[{"enum","settable":false,"manifest_value",   |
//|                       "readback","source","ok"}...]}              |
//|  On success it ALSO carries the faithful-import fields:           |
//|    fixture_file_sha256, manifest_dataset_hash, n_bars,            |
//|    roundtrip_sha256, timeframe. The gate attaches this file to     |
//|    stage_4.json whether the import passes or fails. The committed  |
//|    Python classifier (gate_selfcheck.classify_stage4_outcome)      |
//|    fails a success record CLOSED unless every verified_properties  |
//|    (SETTABLE) entry read back equal; the CALCULATED tick values    |
//|    must be RECORDED (both enums) but are a NAMED limitation, not a |
//|    gate (R8) -- an unavailable/divergent derived value PASSES with |
//|    the limitation surfaced in the stage reason, never silently.   |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslCanon.mqh>   // DslSha256HexBytes / DslSha256Hex / DslCanonEscape

input string InpFixtureCsv  = "Mql5Bot\\gold_import\\gold_fixture.csv"; // fixture CSV (under MQL5\Files)
input string InpManifest    = "Mql5Bot\\gold_import\\manifest.json";    // gold manifest (broker_spec + dataset_hash)
input string InpSymbolSpec  = "Mql5Bot\\broker_exports\\EURUSD.json";   // stage-3 SymbolSpec export
input string InpSymbolName  = "EURUSD.G1";                               // custom symbol (XXXYYY+suffix so Forex currency inference is correct)
input string InpSymbolGroup = "Mql5Bot\\gold";                          // custom-symbol group
input string InpOutDir      = "Mql5Bot\\gold_import_out";               // result JSON dir (fallback only)
input string InpOutFile     = "";                                       // EXACT result JSON path the gate passes (under MQL5\Files); empty => InpOutDir\<symbol>.json

//+------------------------------------------------------------------+
//| raw-byte file IO (relative to MQL5\Files) - byte-deterministic    |
//+------------------------------------------------------------------+
bool ReadFileBytes(const string path, uchar &bytes[])
  {
   ResetLastError();
   int h = FileOpen(path, FILE_READ|FILE_BIN);
   if(h==INVALID_HANDLE)
     {
      Print("[import] FileOpen(READ) FAILED path=", path,
            " last_error=", GetLastError());
      return false;
     }
   int size = (int)FileSize(h);
   ArrayResize(bytes, size);
   if(size>0) FileReadArray(h, bytes, 0, size);
   FileClose(h);
   return true;
  }

string BytesToText(const uchar &bytes[])
  {
   int n = ArraySize(bytes);
   if(n<=0) return "";
   return CharArrayToString(bytes, 0, n, CP_UTF8);
  }

bool WriteTextLF(const string path, const string text)
  {
   uchar bytes[];
   int n = StringToCharArray(text, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(n>0) ArrayResize(bytes, n-1);          // drop trailing '\0'
   ResetLastError();
   int h = FileOpen(path, FILE_WRITE|FILE_BIN);
   if(h==INVALID_HANDLE)
     {
      Print("[import] FileOpen(WRITE) FAILED path=", path,
            " last_error=", GetLastError());
      return false;
     }
   if(ArraySize(bytes)>0) FileWriteArray(h, bytes, 0, ArraySize(bytes));
   FileClose(h);
   return true;
  }

//+------------------------------------------------------------------+
//| running per-property diagnostic (never refuse silently)           |
//+------------------------------------------------------------------+
string g_propsJson = "";   // JSON array body of every property attempted
int    g_propCount = 0;
string g_failCall  = "";   // which CustomSymbolSet* failed
string g_failEnum  = "";   // the exact property enum name
string g_failValue = "";   // the value passed
string g_failSource= "";   // which field of which manifest/spec export

void AppendProp(const string enumName, const string valueStr,
                const string source, const bool ok, const int err)
  {
   if(g_propCount>0) g_propsJson += ",";
   g_propsJson += "{\"enum\":"       + DslCanonEscape(enumName) +
                  ",\"value\":"      + DslCanonEscape(valueStr) +
                  ",\"source\":"     + DslCanonEscape(source) +
                  ",\"ok\":"         + (ok ? "true" : "false") +
                  ",\"last_error\":" + IntegerToString(err) + "}";
   g_propCount++;
  }

// set ONE property, checking its own return; record it either way
bool SetI(const string sym, const ENUM_SYMBOL_INFO_INTEGER id,
          const string enumName, const long v, const string source)
  {
   ResetLastError();
   bool ok = CustomSymbolSetInteger(sym, id, v);
   int  err = GetLastError();
   AppendProp(enumName, IntegerToString(v), source, ok, err);
   if(!ok) { g_failCall="CustomSymbolSetInteger"; g_failEnum=enumName;
             g_failValue=IntegerToString(v); g_failSource=source; }
   return ok;
  }

bool SetD(const string sym, const ENUM_SYMBOL_INFO_DOUBLE id,
          const string enumName, const double v, const string source)
  {
   ResetLastError();
   bool ok = CustomSymbolSetDouble(sym, id, v);
   int  err = GetLastError();
   AppendProp(enumName, DoubleToString(v, 10), source, ok, err);
   if(!ok) { g_failCall="CustomSymbolSetDouble"; g_failEnum=enumName;
             g_failValue=DoubleToString(v, 10); g_failSource=source; }
   return ok;
  }

bool SetS(const string sym, const ENUM_SYMBOL_INFO_STRING id,
          const string enumName, const string v, const string source)
  {
   ResetLastError();
   bool ok = CustomSymbolSetString(sym, id, v);
   int  err = GetLastError();
   AppendProp(enumName, v, source, ok, err);
   if(!ok) { g_failCall="CustomSymbolSetString"; g_failEnum=enumName;
             g_failValue=v; g_failSource=source; }
   return ok;
  }

//+------------------------------------------------------------------+
//| READ-BACK verification (stage verify_properties): every property  |
//| that was SET is read back and compared to the value it was set    |
//| to; the terminal-DERIVED tick values (NOT settable, 5307) are     |
//| compared to the manifest broker values. Doubles are compared at   |
//| the pipeline's own %.10f precision. EVERY comparison is recorded  |
//| (no short-circuit) so the evidence names all divergences at once. |
//+------------------------------------------------------------------+
string g_verifyJson  = "";   // JSON array body: set-property read-backs
int    g_verifyCount = 0;
string g_derivedJson = "";   // JSON array body: derived tick-value checks
int    g_derivedCount= 0;

void AppendVerify(const string enumName, const string expected,
                  const string readback, const bool ok)
  {
   if(g_verifyCount>0) g_verifyJson += ",";
   g_verifyJson += "{\"enum\":"     + DslCanonEscape(enumName) +
                   ",\"expected\":" + DslCanonEscape(expected) +
                   ",\"ok\":"       + (ok ? "true" : "false") +
                   ",\"readback\":" + DslCanonEscape(readback) + "}";
   g_verifyCount++;
  }

void MarkVerifyFail(const string call, const string enumName,
                    const string readback)
  {
   // only the FIRST divergence is named in failed_*; the full picture is in
   // the verified_properties array either way
   if(g_failEnum!="" && g_failCall!="") return;
   g_failCall = call; g_failEnum = enumName;
   g_failValue = readback; g_failSource = "readback vs value set";
  }

bool VerI(const string sym, const ENUM_SYMBOL_INFO_INTEGER id,
          const string enumName, const long expected)
  {
   long got = 0;
   bool fetched = SymbolInfoInteger(sym, id, got);
   bool ok = fetched && (got == expected);
   AppendVerify(enumName, IntegerToString(expected),
                fetched ? IntegerToString(got) : "(SymbolInfoInteger failed)",
                ok);
   if(!ok) MarkVerifyFail("SymbolInfoInteger(readback)", enumName,
                          IntegerToString(got));
   return ok;
  }

bool VerD(const string sym, const ENUM_SYMBOL_INFO_DOUBLE id,
          const string enumName, const double expected)
  {
   double got = 0.0;
   bool fetched = SymbolInfoDouble(sym, id, got);
   string want = DoubleToString(expected, 10);
   string have = DoubleToString(got, 10);
   bool ok = fetched && (want == have);
   AppendVerify(enumName, want,
                fetched ? have : "(SymbolInfoDouble failed)", ok);
   if(!ok) MarkVerifyFail("SymbolInfoDouble(readback)", enumName, have);
   return ok;
  }

bool VerS(const string sym, const ENUM_SYMBOL_INFO_STRING id,
          const string enumName, const string expected)
  {
   string got = "";
   bool fetched = SymbolInfoString(sym, id, got);
   bool ok = fetched && (got == expected);
   AppendVerify(enumName, expected,
                fetched ? got : "(SymbolInfoString failed)", ok);
   if(!ok) MarkVerifyFail("SymbolInfoString(readback)", enumName, got);
   return ok;
  }

// NOT settable (5307 ERR_CUSTOM_SYMBOL_PROPERTY_WRONG): the terminal DERIVES
// this property. It is documented as a "Calculated tick price"
// (ENUM_SYMBOL_INFO_DOUBLE) and MT5 computes it LAZILY from a pricing/quote
// context and the account-currency conversion for the symbol's calc mode. A
// freshly built Forex custom symbol that carries only OHLC bars (no ticks, no
// cross-rate feed to the account currency) frequently has nothing to derive
// from, so the value reads back 0 even after selection + bars (gate_run10:
// _PROFIT=0 while the SETTABLE SYMBOL_TRADE_TICK_VALUE=1.0 read back fine).
//
// R8 SCOPE DECISION (docs/DECISIONS.md 2026-09-19): this read is
// NON-AUTHORITATIVE for stage 4 and NEVER refuses. It records the readback
// for transparency (equal / divergent / unavailable) with a named, scoped
// limitation. The Gold legs certify STRATEGY LOGIC + EXECUTION PATH on the
// fixture; broker tick-value ECONOMICS are certified separately by stage-3
// broker parity + the OrderCalcProfit witness in RiskManager. Blocking here
// would refuse a symbol whose economics a stronger gate already certifies.
//
// It still tries hard first: after selection + bars it nudges a recompute and
// re-reads a BOUNDED number of times (NO Sleep in this hot read-back loop --
// the event-driven EA/include sources ban Sleep outright, SPEC 3.4; this
// SCRIPT's only Sleeps are the bounded Market-Watch release and drop retries,
// R9/R10), taking the value the moment it becomes non-zero.
bool VerDerivedD(const string sym, const ENUM_SYMBOL_INFO_DOUBLE id,
                 const string enumName, const double manifestVal,
                 const string source)
  {
   double got = 0.0;
   bool fetched = false;
   for(int attempt=0; attempt<32; attempt++)
     {
      MqlTick tick;
      SymbolInfoTick(sym, tick);            // nudge a lazy recompute (no Sleep)
      fetched = SymbolInfoDouble(sym, id, got);
      if(fetched && got != 0.0)
         break;
     }
   string want = DoubleToString(manifestVal, 10);
   string have = DoubleToString(got, 10);
   bool equal = fetched && (want == have);
   bool available = fetched && (got != 0.0);
   if(g_derivedCount>0) g_derivedJson += ",";
   g_derivedJson += "{\"available\":"     + (available ? "true" : "false") +
                    ",\"enum\":"          + DslCanonEscape(enumName) +
                    ",\"manifest_value\":"+ DslCanonEscape(want) +
                    ",\"ok\":"            + (equal ? "true" : "false") +
                    ",\"readback\":"      + DslCanonEscape(
                        fetched ? have : "(SymbolInfoDouble failed)") +
                    ",\"settable\":false" +
                    ",\"source\":"        + DslCanonEscape(source) + "}";
   g_derivedCount++;
   // NOTE: no MarkVerifyFail here (R8) -- a divergent/unavailable calculated
   // tick value is a recorded limitation, never a refusal.
   return equal;
  }

//+------------------------------------------------------------------+
//| diagnostic writer: EVERY outcome writes a populated JSON here.    |
//| refusal record carries the failing property/value/source/enum    |
//| and _LastError so the gate is never blind again.                 |
//+------------------------------------------------------------------+
string g_calcModeStr = "";   // SYMBOL_TRADE_CALC_MODE readback (derivation basis)

// the NAMED, SCOPED limitation + the derived-equality evidence, carried on
// EVERY record so a skipped-vs-derived property can never pass silently
string DerivedBlockJson()
  {
   return "{\"authoritative\":false" +
          ",\"limitation\":" + DslCanonEscape(
            "SYMBOL_TRADE_TICK_VALUE_PROFIT/SYMBOL_TRADE_TICK_VALUE_LOSS are "
            "CALCULATED by MT5 (rejected by CustomSymbolSetDouble with 5307 "
            "ERR_CUSTOM_SYMBOL_PROPERTY_WRONG) and are derived lazily from a "
            "pricing context; a bars-only Forex custom symbol may read them "
            "back as 0. This is a NAMED, SCOPED limitation, not a failure: "
            "the Gold legs certify strategy logic + execution path on the "
            "fixture, while broker tick-value economics are certified "
            "separately by stage-3 broker parity + the OrderCalcProfit "
            "witness (docs/DECISIONS.md R5/R8). Recorded here for "
            "transparency (available/ok per property), never gated") +
          ",\"properties\":["    + g_derivedJson + "]" +
          ",\"trade_calc_mode\":" + DslCanonEscape(g_calcModeStr) + "}";
  }

// R9/R10 SYMBOL-STATE HONESTY: every record names which path produced the
// symbol. The field is set ONLY when the named path has ACTUALLY happened
// (CustomSymbolCreate succeeded / the survivor read back fully equal / the
// re-apply completed); until then it stays "unresolved". gate_run13's
// refused record claimed an adopted state although no adoption had
// occurred -- the state was set before the path was proven. A refusal must
// report the state it was in when it refused, never a state it aspired to.
// An adopted import is a PASS (it earns it through the identical read-back
// + round-trip evidence), but the evidence must never look like a fresh
// create.
string g_symbolState    = "unresolved"; // "unresolved"|"created_fresh"|
                                        // "adopted_verified"|"adopted_reapplied"
int    g_adoptRewritten = -1;  // adopt path: N properties that DIFFERED and
                               // were rewritten (0 = verified in place,
                               // nothing written; -1 = not an adopt)
int    g_dropAttempts   = 0;   // attempts made by the LAST DropCustomSymbolChecked

string SymbolStateJson()
  {
   string s = "\"symbol_state\":" + DslCanonEscape(g_symbolState);
   if(g_adoptRewritten >= 0)
      s += ",\"adopt_properties_rewritten\":" +
           IntegerToString(g_adoptRewritten);
   return s;
  }

void RefuseAt(const string outPath, const string symbol, const string stage,
              const string why, const int lastErr)
  {
   string props = "[" + g_propsJson + "]";
   string doc = "{\"derived_tick_values\":" + DerivedBlockJson() +
                ",\"error\":"           + DslCanonEscape(why) +
                ",\"failed_call\":"     + DslCanonEscape(g_failCall) +
                ",\"failed_property\":" + DslCanonEscape(g_failEnum) +
                ",\"failed_source\":"   + DslCanonEscape(g_failSource) +
                ",\"failed_value\":"    + DslCanonEscape(g_failValue) +
                ",\"last_error\":"      + IntegerToString(lastErr) +
                ",\"properties\":"      + props +
                ",\"refused\":true" +
                ",\"stage\":"           + DslCanonEscape(stage) +
                ",\"symbol\":"          + DslCanonEscape(symbol) +
                "," + SymbolStateJson() +
                ",\"verified_properties\":[" + g_verifyJson + "]}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", symbol, " REFUSED [", stage, "]: ", why,
         " (last_error=", lastErr, ")");
  }

//+------------------------------------------------------------------+
//| release `sym` from Market Watch so a property write (or a delete) |
//| becomes possible -- the 5306 rule (R10 hardened). Two async facts  |
//| drive the shape (gate_run13, deselect failed with 4305             |
//| ERR_MARKET_SELECT_ERROR = "error adding or deleting a symbol in    |
//| Market Watch"):                                                    |
//|  (a) ChartClose is ASYNCHRONOUS: it queues a close command and     |
//|      returns; the chart is NOT gone when the call returns, and MT5 |
//|      considers the symbol in use while any chart displays it. So   |
//|      after issuing the closes this function POLLS until no chart   |
//|      displays sym, bounded (<=10 iterations, Sleep(300) between).  |
//|      The close is never assumed to have happened.                  |
//|  (b) MT5 releases a symbol asynchronously even after the charts    |
//|      are gone, so SymbolSelect(sym,false) gets its OWN bounded     |
//|      retry (<=5, Sleep(300) between), the return value and         |
//|      _LastError checked each time; the LAST failure is reported.   |
//| The script's OWN chart is NEVER closed (closing it would kill this |
//| script mid-run) and its symbol is NEVER changed either:            |
//| ChartSetSymbolPeriod on the chart a script is running on           |
//| TERMINATES that script -- it would kill the importer mid-run and   |
//| produce no JSON at all, which is worse than a clean refusal. Do    |
//| NOT try it. If the own chart displays sym, this function fails     |
//| honestly and the caller decides (verify-first adoption needs no    |
//| release at all; only a required-but-impossible release refuses,    |
//| with the operator remediation named).                              |
//| Sleep is legal in scripts; the event-driven EA/include sources     |
//| stay Sleep-free (SPEC 3.4).                                        |
//+------------------------------------------------------------------+
bool ReleaseFromMarketWatch(const string sym, string &whichCall, int &lastErr)
  {
   whichCall = ""; lastErr = 0;
   // 1. close any OTHER chart displaying the symbol; MT5 will not release
   //    a symbol while a chart is open on it. The own-chart guard runs
   //    BEFORE any ChartClose.
   long ownChart = ChartID();
   long cid = ChartFirst();
   while(cid >= 0)
     {
      long nextCid = ChartNext(cid);
      if(ChartSymbol(cid) == sym)
        {
         if(cid == ownChart)
           {
            whichCall = "own chart displays " + sym +
                        " (this script's chart can never be closed, and "
                        "ChartSetSymbolPeriod on the running script's own "
                        "chart TERMINATES the script mid-run -- never "
                        "attempted; the symbol cannot be released while "
                        "its chart shows)";
            lastErr = 0;
            return false;
           }
         ChartClose(cid);
        }
      cid = nextCid;
     }
   // 2. ChartClose is asynchronous: POLL until no chart displays sym,
   //    bounded. Do not assume the close happened.
   for(int poll = 0; poll < 10; poll++)
     {
      bool chartShown = false;
      for(long c = ChartFirst(); c >= 0; c = ChartNext(c))
         if(ChartSymbol(c) == sym) { chartShown = true; break; }
      if(!chartShown)
         break;
      Sleep(300);
     }
   // 3. the deselect itself, in its OWN bounded retry: the symbol may stay
   //    "in use" briefly even after the charts are gone (4305).
   for(int attempt = 1; attempt <= 5; attempt++)
     {
      ResetLastError();
      if(SymbolSelect(sym, false))
         return true;
      whichCall = "SymbolSelect(false)";     // the LAST failure is reported
      lastErr   = GetLastError();
      if(attempt < 5)
         Sleep(300);
     }
   return false;
  }

//+------------------------------------------------------------------+
//| release + drop a custom symbol and VERIFY it is gone (R9/R10      |
//| hardened). A SELECTED symbol cannot be deleted (5306). Since R10   |
//| this is CLEANUP-ONLY (a refusal after a create/mutation must not   |
//| leave debris): the pre-create path never drops -- a survivor is    |
//| adopted verify-first instead (header contract). The release goes   |
//| through ReleaseFromMarketWatch (chart close + async poll + bounded |
//| deselect retry); then the delete is retried a BOUNDED 5 times with |
//| Sleep(300) between: CustomRatesDelete -> ResetLastError ->         |
//| CustomSymbolDelete -> SymbolExist verify. Returns true ONLY when   |
//| SymbolExist reports the name gone (so a following                  |
//| CustomSymbolCreate could never collide with                        |
//| ERR_CUSTOM_SYMBOL_EXIST (5304)). On exhaustion, whichCall/lastErr  |
//| name the LAST failing call; g_dropAttempts counts delete attempts  |
//| (0 = failed before the first delete).                              |
//+------------------------------------------------------------------+
bool DropCustomSymbolChecked(const string sym, string &whichCall, int &lastErr)
  {
   whichCall = ""; lastErr = 0;
   g_dropAttempts = 0;
   if(!ReleaseFromMarketWatch(sym, whichCall, lastErr))
      return false;
   // bounded delete retry: the release after deselection is asynchronous
   for(int attempt = 1; attempt <= 5; attempt++)
     {
      g_dropAttempts = attempt;
      CustomRatesDelete(sym, 0, LONG_MAX);   // clear any bars (no-op if none)
      ResetLastError();
      if(!CustomSymbolDelete(sym))
        { whichCall = "CustomSymbolDelete"; lastErr = GetLastError(); }
      else
        {
         bool isCustom = false;
         ResetLastError();
         if(!SymbolExist(sym, isCustom))     // it MUST actually be gone now
            return true;
         whichCall = "SymbolExist(still present after delete)";
         lastErr = GetLastError();
        }
      if(attempt < 5)
         Sleep(300);                         // scripts may Sleep; bounded
     }
   return false;
  }

//+------------------------------------------------------------------+
//| best-effort cleanup after a POST-create refusal. Never blocks the |
//| refusal; returns a human suffix noting any leftover so the record |
//| stays honest. A leftover is self-healed on the next run by the    |
//| verify-first adoption contract (idempotency).                     |
//+------------------------------------------------------------------+
string CleanupAfterFail(const string sym)
  {
   string wc = ""; int le = 0;
   if(DropCustomSymbolChecked(sym, wc, le)) return "";
   return " [cleanup: "+wc+" left "+sym+" behind (last_error="+
          IntegerToString(le)+"); next run removes it deterministically "
          "before creating]";
  }

//+------------------------------------------------------------------+
//| custom-symbol name rule: Latin letters/digits and only . _ & #    |
//| (<=32 chars incl. the terminating 0, so <=31 usable chars)       |
//+------------------------------------------------------------------+
bool ValidCustomSymbolName(const string s)
  {
   int n = StringLen(s);
   if(n<=0 || n>31) return false;
   for(int i=0;i<n;i++)
     {
      ushort c = StringGetCharacter(s, i);
      bool ok = (c>='A' && c<='Z') || (c>='a' && c<='z') ||
                (c>='0' && c<='9') ||
                c=='.' || c=='_' || c=='&' || c=='#';
      if(!ok) return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| MT5 name/path rule: CustomSymbolCreate treats a symbol_path whose |
//| LAST element equals the symbol name as the symbol itself, not a   |
//| folder. So the last element of the group must NOT equal the name  |
//| (e.g. group "Mql5Bot\gold" + name "GOLD_EURUSD" is fine;          |
//| "Mql5Bot\gold\GOLD_EURUSD" as a GROUP would be ambiguous). Names  |
//| are compared case-insensitively (MT5 symbol names are not case-   |
//| sensitive). Returns true when the pair is unambiguous.           |
//+------------------------------------------------------------------+
bool GroupPathOkForName(const string grp, const string sym)
  {
   string parts[];
   int n = StringSplit(grp, '\\', parts);
   if(n <= 0) return true;               // empty/relative group: no last folder
   string last = parts[n-1];
   StringToUpper(last);
   string s = sym;
   StringToUpper(s);
   return (last != s);
  }

//+------------------------------------------------------------------+
//| parse the fixture CSV "time,open,high,low,close,volume"          |
//| time is "YYYY-MM-DD HH:MM:SS"; every numeric column is %.10f      |
//+------------------------------------------------------------------+
bool ParseFixtureCsv(const string text, datetime &times[], double &open[],
                     double &high[], double &low[], double &close[],
                     double &volume[], int &nOut)
  {
   string lines[];
   int nLines = StringSplit(text, '\n', lines);
   int n=0;
   bool headerSeen=false;
   for(int li=0; li<nLines; li++)
     {
      string line = lines[li];
      StringReplace(line, "\r", "");
      if(StringLen(line)==0) continue;
      if(!headerSeen) { headerSeen=true; continue; }   // skip header row
      string cols[];
      if(StringSplit(line, ',', cols) < 6) return false;
      // "2024-01-01 00:00:00" -> "2024.01.01 00:00:00"
      string ts = cols[0];
      StringReplace(ts, "-", ".");
      ArrayResize(times, n+1);  ArrayResize(open, n+1);
      ArrayResize(high, n+1);   ArrayResize(low, n+1);
      ArrayResize(close, n+1);  ArrayResize(volume, n+1);
      times[n]  = StringToTime(ts);
      open[n]   = StringToDouble(cols[1]);
      high[n]   = StringToDouble(cols[2]);
      low[n]    = StringToDouble(cols[3]);
      close[n]  = StringToDouble(cols[4]);
      volume[n] = StringToDouble(cols[5]);
      n++;
     }
   nOut = n;
   return (n > 0);
  }

//+------------------------------------------------------------------+
//| datetime -> "YYYY-MM-DD HH:MM:SS" (pandas index format)          |
//+------------------------------------------------------------------+
string FormatTs(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return StringFormat("%04d-%02d-%02d %02d:%02d:%02d",
                       dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec);
  }

//+------------------------------------------------------------------+
//| map a manifest timeframe string to ENUM_TIMEFRAMES               |
//+------------------------------------------------------------------+
bool TimeframeFromString(const string tf, ENUM_TIMEFRAMES &out)
  {
   string s = tf;
   StringToUpper(s);
   if(s=="M1")  { out=PERIOD_M1;  return true; }
   if(s=="M5")  { out=PERIOD_M5;  return true; }
   if(s=="M15") { out=PERIOD_M15; return true; }
   if(s=="M30") { out=PERIOD_M30; return true; }
   if(s=="H1")  { out=PERIOD_H1;  return true; }
   if(s=="H4")  { out=PERIOD_H4;  return true; }
   if(s=="D1")  { out=PERIOD_D1;  return true; }
   return false;
  }

//+------------------------------------------------------------------+
//| re-serialize bars to the EXACT pandas CSV byte stream:           |
//|   header "time,open,high,low,close,volume\n"                     |
//|   each row "%s,%.10f,%.10f,%.10f,%.10f,%.10f\n"                   |
//+------------------------------------------------------------------+
string SerializeCsv(const datetime &times[], const double &open[],
                    const double &high[], const double &low[],
                    const double &close[], const double &volume[],
                    const int n)
  {
   string out = "time,open,high,low,close,volume\n";
   for(int i=0;i<n;i++)
      out += StringFormat("%s,%.10f,%.10f,%.10f,%.10f,%.10f\n",
                          FormatTs(times[i]), open[i], high[i], low[i],
                          close[i], volume[i]);
   return out;
  }

//+------------------------------------------------------------------+
//| require a numeric property from the manifest broker_spec         |
//+------------------------------------------------------------------+
bool ReqNum(CDslJson &json, const int obj, const string key, double &out,
            string &missing)
  {
   int m = json.Member(obj, key);
   if(m < 0) { missing = key; return false; }
   out = json.Num(m);
   return true;
  }

bool ReqStr(CDslJson &json, const int obj, const string key, string &out,
            string &missing)
  {
   int m = json.Member(obj, key);
   if(m < 0) { missing = key; return false; }
   out = json.Str(m);
   return true;
  }

//+------------------------------------------------------------------+
//| MQL5 FILE SANDBOX: FileOpen resolves ONLY relative paths under    |
//| MQL5\Files (this script never uses FILE_COMMON). An absolute path |
//| (drive letter or leading slash) is refused by the sandbox and     |
//| nothing gets written -- exactly the "terminal ran, no JSON"        |
//| symptom. Detect it up front so the terminal log names the cause.  |
//+------------------------------------------------------------------+
bool LooksAbsolutePath(const string p)
  {
   if(StringLen(p)==0) return false;
   if(StringFind(p, ":")>=0) return true;      // drive letter (C:\...)
   ushort c0 = StringGetCharacter(p, 0);
   return (c0=='\\' || c0=='/');               // rooted / UNC
  }

//+------------------------------------------------------------------+
//| ONE property-application sequence (R9): called by BOTH the        |
//| fresh-create path and the adopt-in-place path. It is deliberately  |
//| a single function -- a second copy would drift, and the volume     |
//| MAX -> STEP -> MIN -> LIMIT ordering (R6, err 5308) must hold      |
//| identically on both paths. The symbol must be DESELECTED when     |
//| this runs (a selected symbol cannot have properties changed,      |
//| err 5306). Every property is set ONE AT A TIME with each return   |
//| checked and recorded (AppendProp); on the first failure the       |
//| g_fail* diagnostics name the call/property/value/source.          |
//+------------------------------------------------------------------+
bool ApplySymbolProperties(const string sym,
                           const double digits, const double point,
                           const double tickSize, const double tickValProfit,
                           const double contractSize,
                           const double volMin, const double volMax,
                           const double volStep, const double volLimit,
                           const double stopsLevel, const double freezeLevel,
                           const string ccyProfit, const string ccyBase,
                           const string ccyMargin)
  {
   bool sok = true;
   sok = sok && SetI(sym, SYMBOL_DIGITS, "SYMBOL_DIGITS", (long)digits,
                     "manifest.broker_spec.digits");
   sok = sok && SetD(sym, SYMBOL_POINT, "SYMBOL_POINT", point,
                     "manifest.broker_spec.point");
   sok = sok && SetD(sym, SYMBOL_TRADE_TICK_SIZE, "SYMBOL_TRADE_TICK_SIZE",
                     tickSize, "manifest.broker_spec.tick_size");
   sok = sok && SetD(sym, SYMBOL_TRADE_TICK_VALUE, "SYMBOL_TRADE_TICK_VALUE",
                     tickValProfit, "manifest.broker_spec.tick_value_profit");
   // SYMBOL_TRADE_TICK_VALUE_PROFIT / SYMBOL_TRADE_TICK_VALUE_LOSS are NOT
   // set here: MT5 documents them as CALCULATED and CustomSymbolSetDouble
   // rejects them with 5307 ERR_CUSTOM_SYMBOL_PROPERTY_WRONG (gate_run7).
   // They are verified by READ-BACK against the manifest in the
   // verify_properties stage below -- refusing on divergence, never skipping.
   sok = sok && SetD(sym, SYMBOL_TRADE_CONTRACT_SIZE,
                     "SYMBOL_TRADE_CONTRACT_SIZE", contractSize,
                     "manifest.broker_spec.contract_size");
   // VOLUME FAMILY ORDERING (err=5308 ERR_CUSTOM_SYMBOL_PARAMETER_ERROR,
   // gate_run8): a freshly created custom symbol starts with volume_min=0,
   // volume_max=0, volume_step=0. Setting SYMBOL_VOLUME_MIN=0.01 FIRST is an
   // internally inconsistent intermediate state (min > max=0, and min is not a
   // multiple of step=0), which CustomSymbolSetDouble rejects with 5308 -- "a
   // wrong parameter while setting the property" (5307 would mean a read-only
   // PROPERTY; 5308 means the VALUE, so volume_min IS settable, its value was
   // refused). The MQL5 docs give no ordering rule, so we impose one that keeps
   // EVERY intermediate state consistent: set the ceiling (MAX) and the grid
   // (STEP) BEFORE the floor (MIN), so MIN is only ever validated against the
   // real broker max and step (min<=max, min a multiple of step). LIMIT
   // (aggregate cap, 0=none) is set last, after the [min,max] band exists.
   sok = sok && SetD(sym, SYMBOL_VOLUME_MAX, "SYMBOL_VOLUME_MAX", volMax,
                     "manifest.broker_spec.volume_max");
   sok = sok && SetD(sym, SYMBOL_VOLUME_STEP, "SYMBOL_VOLUME_STEP", volStep,
                     "manifest.broker_spec.volume_step");
   sok = sok && SetD(sym, SYMBOL_VOLUME_MIN, "SYMBOL_VOLUME_MIN", volMin,
                     "manifest.broker_spec.volume_min");
   sok = sok && SetD(sym, SYMBOL_VOLUME_LIMIT, "SYMBOL_VOLUME_LIMIT", volLimit,
                     "manifest.broker_spec.volume_limit");
   sok = sok && SetI(sym, SYMBOL_TRADE_STOPS_LEVEL, "SYMBOL_TRADE_STOPS_LEVEL",
                     (long)stopsLevel, "manifest.broker_spec.stops_level_points");
   sok = sok && SetI(sym, SYMBOL_TRADE_FREEZE_LEVEL, "SYMBOL_TRADE_FREEZE_LEVEL",
                     (long)freezeLevel, "manifest.broker_spec.freeze_level_points");
   // CURRENCY PROPERTIES (R7): a Forex-mode custom symbol DERIVES base and
   // profit currencies from the name (first/second three-char chunks). These
   // two SetString calls therefore return ok=true WITHOUT taking effect -- MT5
   // overrides them with the name inference. They are kept for generality (a
   // non-Forex symbol WOULD honour them) and cause no failure (they return
   // ok), but correctness for base/profit comes from the XXXYYY+suffix NAME
   // (EURUSD.G1 -> EUR/USD) and is PROVEN by the read-back in
   // verify_properties, never assumed. Margin currency IS settable and this
   // call sticks. Read-back is the authoritative guarantee for all three.
   sok = sok && SetS(sym, SYMBOL_CURRENCY_PROFIT, "SYMBOL_CURRENCY_PROFIT",
                     ccyProfit, "manifest.broker_spec.currency_profit");
   sok = sok && SetS(sym, SYMBOL_CURRENCY_BASE, "SYMBOL_CURRENCY_BASE",
                     ccyBase, "SymbolSpec("+InpSymbolSpec+").symbol.currency_base");
   sok = sok && SetS(sym, SYMBOL_CURRENCY_MARGIN, "SYMBOL_CURRENCY_MARGIN",
                     ccyMargin, "SymbolSpec("+InpSymbolSpec+").symbol.currency_margin");
   return sok;
  }

//+------------------------------------------------------------------+
//| R10 VERIFY-FIRST adopt precheck: read back every SETTABLE property |
//| of the surviving symbol and compare it to the manifest/spec value  |
//| with EXACTLY the semantics of the final verify_properties stage    |
//| (doubles at the pipeline's own %.10f precision). Returns the       |
//| number of properties that DIFFER; g_diffList names them. Property  |
//| WRITES are the only thing that needs a deselected symbol (5306),   |
//| so an all-equal survivor is adopted with ZERO writes and no        |
//| Market-Watch traffic at all -- the steady-state re-run. The R8     |
//| CALCULATED tick values (_PROFIT/_LOSS) are deliberately NOT        |
//| checked here: they are not settable (5307) and must never force a  |
//| rewrite. The property list and its order mirror                    |
//| ApplySymbolProperties one-to-one (incl. volume MAX->STEP->MIN->    |
//| LIMIT) so the two can never drift apart silently.                  |
//+------------------------------------------------------------------+
string g_diffList  = "";   // comma-joined enum names that differed
int    g_diffCount = 0;

void NoteDiff(const string enumName)
  {
   if(g_diffCount > 0) g_diffList += ",";
   g_diffList += enumName;
   g_diffCount++;
  }

void DiffI(const string sym, const ENUM_SYMBOL_INFO_INTEGER id,
           const string enumName, const long want)
  {
   long got = 0;
   if(!SymbolInfoInteger(sym, id, got) || got != want)
      NoteDiff(enumName);
  }

void DiffD(const string sym, const ENUM_SYMBOL_INFO_DOUBLE id,
           const string enumName, const double want)
  {
   double got = 0.0;
   if(!SymbolInfoDouble(sym, id, got) ||
      DoubleToString(got, 10) != DoubleToString(want, 10))
      NoteDiff(enumName);
  }

void DiffS(const string sym, const ENUM_SYMBOL_INFO_STRING id,
           const string enumName, const string want)
  {
   string got = "";
   if(!SymbolInfoString(sym, id, got) || got != want)
      NoteDiff(enumName);
  }

int CountPropertyDiffs(const string sym,
                       const double digits, const double point,
                       const double tickSize, const double tickValProfit,
                       const double contractSize,
                       const double volMin, const double volMax,
                       const double volStep, const double volLimit,
                       const double stopsLevel, const double freezeLevel,
                       const string ccyProfit, const string ccyBase,
                       const string ccyMargin)
  {
   g_diffList = ""; g_diffCount = 0;
   DiffI(sym, SYMBOL_DIGITS, "SYMBOL_DIGITS", (long)digits);
   DiffD(sym, SYMBOL_POINT, "SYMBOL_POINT", point);
   DiffD(sym, SYMBOL_TRADE_TICK_SIZE, "SYMBOL_TRADE_TICK_SIZE", tickSize);
   DiffD(sym, SYMBOL_TRADE_TICK_VALUE, "SYMBOL_TRADE_TICK_VALUE",
         tickValProfit);
   DiffD(sym, SYMBOL_TRADE_CONTRACT_SIZE, "SYMBOL_TRADE_CONTRACT_SIZE",
         contractSize);
   DiffD(sym, SYMBOL_VOLUME_MAX, "SYMBOL_VOLUME_MAX", volMax);
   DiffD(sym, SYMBOL_VOLUME_STEP, "SYMBOL_VOLUME_STEP", volStep);
   DiffD(sym, SYMBOL_VOLUME_MIN, "SYMBOL_VOLUME_MIN", volMin);
   DiffD(sym, SYMBOL_VOLUME_LIMIT, "SYMBOL_VOLUME_LIMIT", volLimit);
   DiffI(sym, SYMBOL_TRADE_STOPS_LEVEL, "SYMBOL_TRADE_STOPS_LEVEL",
         (long)stopsLevel);
   DiffI(sym, SYMBOL_TRADE_FREEZE_LEVEL, "SYMBOL_TRADE_FREEZE_LEVEL",
         (long)freezeLevel);
   DiffS(sym, SYMBOL_CURRENCY_PROFIT, "SYMBOL_CURRENCY_PROFIT", ccyProfit);
   DiffS(sym, SYMBOL_CURRENCY_BASE, "SYMBOL_CURRENCY_BASE", ccyBase);
   DiffS(sym, SYMBOL_CURRENCY_MARGIN, "SYMBOL_CURRENCY_MARGIN", ccyMargin);
   return g_diffCount;
  }

//+------------------------------------------------------------------+
//| main import                                                      |
//+------------------------------------------------------------------+
void OnStart()
  {
   // PROOF, not hope: the FIRST action is a Print() naming EVERY resolved
   // input, so the gate's terminal-log backstop shows exactly which inputs
   // this run got (compiled-in defaults vs the gate's .set) and where it
   // will write -- even when no JSON is ever produced.
   Print("[import] STARTUP fixture_csv=", InpFixtureCsv,
         " manifest=", InpManifest,
         " symbol_spec=", InpSymbolSpec);
   Print("[import] STARTUP symbol=", InpSymbolName,
         " group=", InpSymbolGroup,
         " out_dir=", InpOutDir,
         " out_file=", InpOutFile);

   string sym     = InpSymbolName;
   // OBSERVABILITY: write to the EXACT path the gate passes (InpOutFile).
   // Only a manual run (no gate) falls back to the guessed default.
   string outPath = (StringLen(InpOutFile) > 0)
                    ? InpOutFile
                    : (InpOutDir + "\\" + sym + ".json");
   // SANDBOX GUARD: an absolute InpOutFile can never be written (FileOpen
   // refuses it); say so loudly and fall back to the relative default so the
   // diagnostic JSON still lands under MQL5\Files where the sandbox allows.
   if(LooksAbsolutePath(outPath))
     {
      Print("[import] SANDBOX: out path '", outPath, "' is absolute; MQL5 ",
            "FileOpen only writes RELATIVE paths under MQL5\\Files -- ",
            "falling back to ", InpOutDir, "\\", sym, ".json");
      outPath = InpOutDir + "\\" + sym + ".json";
     }
   Print("[import] STARTUP out_rel=", outPath,
         " out_abs=", TerminalInfoString(TERMINAL_DATA_PATH),
         "\\MQL5\\Files\\", outPath);

   // ---- 0. custom-symbol NAME must satisfy MT5's rules ------------
   if(!ValidCustomSymbolName(sym))
     { RefuseAt(outPath, sym, "name_check",
                "symbol name violates MT5 custom-symbol rules (Latin "
                "letters/digits and only . _ & #, <=31 chars): "+sym, 0);
       return; }
   // the last element of the group path must not equal the name, or MT5
   // would treat the path's tail as the symbol itself (name/path rule)
   if(!GroupPathOkForName(InpSymbolGroup, sym))
     { RefuseAt(outPath, sym, "name_check",
                "ambiguous name/group pair: the last element of group '"+
                InpSymbolGroup+"' equals the symbol name '"+sym+"'; MT5 "
                "would treat it as the symbol, not a folder", 0);
       return; }

   // ---- 1. read the committed fixture CSV as raw bytes -----------
   uchar csvBytes[];
   if(!ReadFileBytes(InpFixtureCsv, csvBytes))
     { RefuseAt(outPath, sym, "read_fixture",
                "cannot read fixture csv: "+InpFixtureCsv, GetLastError());
       return; }
   string fixtureSha = DslSha256HexBytes(csvBytes);

   // ---- read + parse the gold manifest (broker_spec + dataset_hash)
   uchar manBytes[];
   if(!ReadFileBytes(InpManifest, manBytes))
     { RefuseAt(outPath, sym, "read_manifest",
                "cannot read manifest: "+InpManifest, GetLastError());
       return; }
   CDslJson man;
   if(!man.Parse(BytesToText(manBytes)))
     { RefuseAt(outPath, sym, "parse_manifest",
                "manifest JSON parse error: "+man.Error(), 0);
       return; }
   int mroot = man.Root;
   int bspec = man.Member(mroot, "broker_spec");
   if(bspec < 0)
     { RefuseAt(outPath, sym, "parse_manifest", "manifest has no broker_spec", 0);
       return; }

   string datasetHash = man.GetStr(mroot, "dataset_hash", "");
   if(datasetHash == "")
     { RefuseAt(outPath, sym, "parse_manifest", "manifest has no dataset_hash", 0);
       return; }
   string tfStr = man.GetStr(mroot, "timeframe", "");
   ENUM_TIMEFRAMES tf;
   if(!TimeframeFromString(tfStr, tf))
     { RefuseAt(outPath, sym, "parse_manifest",
                "manifest timeframe unusable: "+tfStr, 0);
       return; }

   // the staged fixture MUST be the frozen one, byte-for-byte
   if(fixtureSha != datasetHash)
     { RefuseAt(outPath, sym, "fixture_hash",
                "fixture csv sha256 "+fixtureSha+
                " != manifest dataset_hash "+datasetHash+
                " (converted/foreign frame, not the frozen fixture)", 0);
       return; }

   // ---- read the stage-3 SymbolSpec export (for base/margin ccy) --
   // nested under {"symbol":{...}} in the mql5bot.broker_export/1 schema
   uchar specBytes[];
   int sspec = -1;
   CDslJson spec;
   if(ReadFileBytes(InpSymbolSpec, specBytes))
     {
      if(spec.Parse(BytesToText(specBytes)))
         sspec = spec.Member(spec.Root, "symbol");
     }

   // ---- 2. collect every property (manifest first, never invented)
   string missing = "";
   double digits=0, point=0, tickSize=0, tickValProfit=0, tickValLoss=0;
   double contractSize=0, volMin=0, volMax=0, volStep=0, volLimit=0;
   double stopsLevel=0, freezeLevel=0;
   string ccyProfit="";
   bool ok = true;
   ok = ok && ReqNum(man, bspec, "digits", digits, missing);
   ok = ok && ReqNum(man, bspec, "point", point, missing);
   ok = ok && ReqNum(man, bspec, "tick_size", tickSize, missing);
   ok = ok && ReqNum(man, bspec, "tick_value_profit", tickValProfit, missing);
   ok = ok && ReqNum(man, bspec, "tick_value_loss", tickValLoss, missing);
   ok = ok && ReqNum(man, bspec, "contract_size", contractSize, missing);
   ok = ok && ReqNum(man, bspec, "volume_min", volMin, missing);
   ok = ok && ReqNum(man, bspec, "volume_max", volMax, missing);
   ok = ok && ReqNum(man, bspec, "volume_step", volStep, missing);
   ok = ok && ReqNum(man, bspec, "volume_limit", volLimit, missing);
   ok = ok && ReqNum(man, bspec, "stops_level_points", stopsLevel, missing);
   ok = ok && ReqNum(man, bspec, "freeze_level_points", freezeLevel, missing);
   ok = ok && ReqStr(man, bspec, "currency_profit", ccyProfit, missing);
   if(!ok)
     { RefuseAt(outPath, sym, "collect_properties",
                "manifest broker_spec missing property: "+missing, 0);
       return; }

   // currency_base/currency_margin are not in the manifest broker_spec;
   // they come from the stage-3 SymbolSpec export, never invented
   string ccyBase="", ccyMargin="";
   if(sspec >= 0)
     {
      ccyBase   = spec.GetStr(sspec, "currency_base", "");
      ccyMargin = spec.GetStr(sspec, "currency_margin", "");
     }
   if(ccyBase == "" || ccyMargin == "")
     { RefuseAt(outPath, sym, "collect_properties",
                "currency_base/currency_margin absent from the "
                "SymbolSpec export ("+InpSymbolSpec+") and not in the "
                "manifest - refusing rather than inventing them", 0);
       return; }

   // ---- parse the fixture bars ------------------------------------
   datetime times[]; double open[], high[], low[], close[], volume[];
   int nBars=0;
   if(!ParseFixtureCsv(BytesToText(csvBytes), times, open, high, low, close,
                       volume, nBars))
     { RefuseAt(outPath, sym, "parse_fixture", "malformed fixture csv", 0);
       return; }

   // ---- 2b. resolve symbol STATE deterministically & IDEMPOTENTLY -
   // SymbolExist is a GLOBAL check (names are unique across the whole
   // hierarchy). A broker (non-custom) symbol of the same name must never
   // be shadowed. A custom survivor from a prior run is resolved by the
   // R10 VERIFY-FIRST contract (header): read back every settable property
   // against the manifest spec BEFORE touching anything. All equal ->
   // adopt with ZERO property writes and NO deselect -- the steady-state
   // re-run needs nothing from Market Watch, because property WRITES are
   // the only thing that requires a deselected symbol (5306) and
   // rewriting already-correct values is what manufactured the failing
   // deselect of gate_run13 (4305 ERR_MARKET_SELECT_ERROR). Any
   // difference -> hardened release (close other charts, POLL the
   // asynchronous ChartClose, bounded deselect retry), then re-apply
   // through the SAME shared ApplySymbolProperties sequence. Refuse ONLY
   // when a REQUIRED release cannot be obtained. Running twice in a row
   // therefore produces identical evidence, with symbol_state naming
   // which path ran.
   bool isCustom = false;
   bool needCreate = true;
   bool adopted = false;
   int  adoptDiffs = 0;
   if(SymbolExist(sym, isCustom))
     {
      if(!isCustom)
        { RefuseAt(outPath, sym, "symbol_state",
                   "a NON-custom (broker) symbol named "+sym+
                   " already exists; refusing to shadow a broker symbol", 0);
          return; }
      needCreate = false;
      adopted    = true;
      adoptDiffs = CountPropertyDiffs(sym, digits, point, tickSize,
                                      tickValProfit, contractSize, volMin,
                                      volMax, volStep, volLimit, stopsLevel,
                                      freezeLevel, ccyProfit, ccyBase,
                                      ccyMargin);
      if(adoptDiffs == 0)
        {
         // every settable property already equals the spec: the survivor is
         // adopted VERIFIED -- ZERO property writes, no deselect, Market
         // Watch untouched. The state is set here because the verification
         // has actually happened (and the unchanged verify_properties stage
         // below proves it again on the record).
         g_symbolState    = "adopted_verified";
         g_adoptRewritten = 0;
         Print("[import] SYMBOL_STATE adopted_verified: every settable "
               "property of the surviving custom symbol ", sym,
               " already equals the manifest spec; ZERO property writes, "
               "no deselect needed");
        }
      else
        {
         // N properties differ -> a re-apply is REQUIRED, and only property
         // writes need a deselected symbol (5306)
         Print("[import] adopt precheck: ", adoptDiffs,
               " differing propert(y/ies) vs the manifest spec (",
               g_diffList, "); deselect + re-apply required");
         string wc = ""; int le = 0;
         if(!ReleaseFromMarketWatch(sym, wc, le))
           { // symbol_state stays "unresolved": no adoption occurred, and
             // the record must say the state it was in, not the one it
             // aspired to
             RefuseAt(outPath, sym, "symbol_state",
                      "cannot adopt the surviving custom symbol "+sym+": "+
                      IntegerToString(adoptDiffs)+" propert(y/ies) differ "
                      "from the manifest spec ("+g_diffList+") and must be "
                      "re-applied, but properties cannot be changed on a "
                      "selected symbol (5306) and the release failed: "+wc+
                      " (last_error="+IntegerToString(le)+"; 4305 = "
                      "ERR_MARKET_SELECT_ERROR, error adding or deleting a "
                      "symbol in Market Watch; ChartClose is asynchronous). "
                      "Operator remediation: close any chart on "+sym+
                      " in the terminal, then re-run the gate", le);
             return; }
        }
      // no bar from a prior fixture may survive into this dataset: wipe the
      // full range and VERIFY the symbol carries zero bars.
      // CustomRatesDelete works on a SELECTED custom symbol (the normal
      // live-feed path), so the verified adopt stays Market-Watch-free.
      CustomRatesDelete(sym, 0, LONG_MAX);
      ResetLastError();
      int leftoverBars = Bars(sym, tf);
      if(leftoverBars > 0)
        { int lbErr = GetLastError();
          RefuseAt(outPath, sym, "symbol_state",
                   "adopt-in-place: CustomRatesDelete left "+
                   IntegerToString(leftoverBars)+" bar(s) on "+sym+
                   "; a prior fixture's bars must never survive into "
                   "this dataset", lbErr);
          return; }
     }
   else
     {
      // even if SymbolExist says no, ensure it is not lingering selected
      SymbolSelect(sym, false);
     }

   if(needCreate)
     {
      ResetLastError();
      if(!CustomSymbolCreate(sym, InpSymbolGroup))
        { RefuseAt(outPath, sym, "create_symbol",
                   "CustomSymbolCreate failed for group "+InpSymbolGroup+
                   " (last_error 5304 = ERR_CUSTOM_SYMBOL_EXIST means a prior "
                   "symbol survived deletion)", GetLastError());
          return; }
      // the symbol is freshly created and NOT selected in Market Watch, so it
      // is safe to set every property. We select it only after bars are
      // written. Only now is the path proven, so only now may the record
      // carry it (a refusal above stays "unresolved").
      g_symbolState = "created_fresh";
     }

   // ---- 2c. set every property ONE AT A TIME, checking each -------
   // ONE sequence for EVERY path that writes at all (R9/R10): a freshly
   // created symbol and an adopted survivor with differing properties go
   // through the IDENTICAL ApplySymbolProperties calls (same volume
   // MAX->STEP->MIN->LIMIT ordering) and then the identical read-back +
   // round-trip verification below. An adopted_verified survivor skips
   // this block entirely -- zero writes is the point -- and is still
   // proven by the same verification below. Adoption earns its PASS by
   // exactly the same evidence as a fresh create: the guarantee comes from
   // that verification, not from the symbol being new.
   if(needCreate || adoptDiffs > 0)
     {
      if(!ApplySymbolProperties(sym, digits, point, tickSize, tickValProfit,
                                contractSize, volMin, volMax, volStep,
                                volLimit, stopsLevel, freezeLevel, ccyProfit,
                                ccyBase, ccyMargin))
        { int err = GetLastError();
          string suffix = CleanupAfterFail(sym);
          RefuseAt(outPath, sym, "set_properties",
                   g_failCall+"("+g_failEnum+"="+g_failValue+" from "+
                   g_failSource+") failed"+suffix, err);
          return; }
      if(adopted)
        {
         // only now has the re-apply actually completed
         g_symbolState    = "adopted_reapplied";
         g_adoptRewritten = adoptDiffs;
         Print("[import] SYMBOL_STATE adopted_reapplied: ", adoptDiffs,
               " differing propert(y/ies) forced a full re-apply (",
               g_diffList, ")");
        }
     }

   // ---- 3. write the bars via CustomRatesUpdate -------------------
   MqlRates rates[];
   ArrayResize(rates, nBars);
   for(int i=0;i<nBars;i++)
     {
      rates[i].time         = times[i];
      rates[i].open         = open[i];
      rates[i].high         = high[i];
      rates[i].low          = low[i];
      rates[i].close        = close[i];
      rates[i].tick_volume  = (long)MathRound(volume[i]);
      rates[i].real_volume  = 0;
      rates[i].spread       = 0;
     }
   ResetLastError();
   if(CustomRatesUpdate(sym, rates) < 0)
     { int err = GetLastError();
       string suffix = CleanupAfterFail(sym);
       RefuseAt(outPath, sym, "write_bars",
                "CustomRatesUpdate failed"+suffix, err);
       return; }

   // ---- select the symbol ONLY now: after every property is set and
   //      the bars are written (a selected symbol cannot be mutated) --
   if(!SymbolSelect(sym, true))
     { int err = GetLastError();
       string suffix = CleanupAfterFail(sym);
       RefuseAt(outPath, sym, "select_symbol",
                "SymbolSelect(true) failed after import"+suffix, err);
       return; }

   // ---- 3b. verify_properties: READ BACK every property that was set
   //      and compare to the value it was set to; ANY divergence REFUSES.
   //      No short-circuit: every comparison is recorded so the evidence
   //      names all divergences at once.
   bool vok = true;
   vok = VerI(sym, SYMBOL_DIGITS, "SYMBOL_DIGITS", (long)digits) && vok;
   vok = VerD(sym, SYMBOL_POINT, "SYMBOL_POINT", point) && vok;
   vok = VerD(sym, SYMBOL_TRADE_TICK_SIZE, "SYMBOL_TRADE_TICK_SIZE",
              tickSize) && vok;
   vok = VerD(sym, SYMBOL_TRADE_TICK_VALUE, "SYMBOL_TRADE_TICK_VALUE",
              tickValProfit) && vok;
   vok = VerD(sym, SYMBOL_TRADE_CONTRACT_SIZE, "SYMBOL_TRADE_CONTRACT_SIZE",
              contractSize) && vok;
   // read back the volume family in the same MAX->STEP->MIN->LIMIT order it
   // was set, so the verified_properties evidence array mirrors the writes
   vok = VerD(sym, SYMBOL_VOLUME_MAX, "SYMBOL_VOLUME_MAX", volMax) && vok;
   vok = VerD(sym, SYMBOL_VOLUME_STEP, "SYMBOL_VOLUME_STEP", volStep) && vok;
   vok = VerD(sym, SYMBOL_VOLUME_MIN, "SYMBOL_VOLUME_MIN", volMin) && vok;
   vok = VerD(sym, SYMBOL_VOLUME_LIMIT, "SYMBOL_VOLUME_LIMIT", volLimit) && vok;
   vok = VerI(sym, SYMBOL_TRADE_STOPS_LEVEL, "SYMBOL_TRADE_STOPS_LEVEL",
              (long)stopsLevel) && vok;
   vok = VerI(sym, SYMBOL_TRADE_FREEZE_LEVEL, "SYMBOL_TRADE_FREEZE_LEVEL",
              (long)freezeLevel) && vok;
   vok = VerS(sym, SYMBOL_CURRENCY_PROFIT, "SYMBOL_CURRENCY_PROFIT",
              ccyProfit) && vok;
   vok = VerS(sym, SYMBOL_CURRENCY_BASE, "SYMBOL_CURRENCY_BASE",
              ccyBase) && vok;
   vok = VerS(sym, SYMBOL_CURRENCY_MARGIN, "SYMBOL_CURRENCY_MARGIN",
              ccyMargin) && vok;
   if(!vok)
     { string suffix = CleanupAfterFail(sym);
       RefuseAt(outPath, sym, "verify_properties",
                "read-back of a set property diverged from the value set ("+
                g_failEnum+" read back as "+g_failValue+
                "); the custom symbol is not the certified one"+suffix, 0);
       return; }

   // the derivation basis: which calc mode the terminal derives tick
   // values under (recorded in the evidence, never assumed)
   g_calcModeStr = IntegerToString(
       SymbolInfoInteger(sym, SYMBOL_TRADE_CALC_MODE));
   // R8 SCOPE DECISION: the CALCULATED tick values (5307, not settable) are
   // read back AFTER selection + bars (with a bounded, Sleep-free retry inside
   // VerDerivedD) and RECORDED for transparency -- but they NEVER refuse
   // stage 4. A bars-only Forex custom symbol legitimately reads them back as
   // 0 (nothing to derive from). Broker tick-value economics are certified
   // separately by stage-3 broker parity + the OrderCalcProfit witness; the
   // Gold legs certify strategy logic + execution path on the fixture. The
   // committed classifier (gate_selfcheck.properties_verified) surfaces the
   // readback as a NAMED limitation and PASSES -- never a silent pass, never
   // an over-strict block (docs/DECISIONS.md R5/R8).
   VerDerivedD(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT,
               "SYMBOL_TRADE_TICK_VALUE_PROFIT", tickValProfit,
               "manifest.broker_spec.tick_value_profit");
   VerDerivedD(sym, SYMBOL_TRADE_TICK_VALUE_LOSS,
               "SYMBOL_TRADE_TICK_VALUE_LOSS", tickValLoss,
               "manifest.broker_spec.tick_value_loss");

   // ---- read them back at the fixture timeframe (explicit sym/tf) --
   MqlRates back[];
   int got = CopyRates(sym, tf, 0, nBars, back);
   if(got != nBars)
     { int err = GetLastError();
       string suffix = CleanupAfterFail(sym);
       RefuseAt(outPath, sym, "readback",
                "readback bar count "+IntegerToString(got)+
                " != "+IntegerToString(nBars)+
                " (timeframe generation perturbed the fixture)"+suffix, err);
       return; }
   ArraySetAsSeries(back, false);

   datetime rt_times[]; double rt_open[], rt_high[], rt_low[], rt_close[], rt_vol[];
   ArrayResize(rt_times, got); ArrayResize(rt_open, got);
   ArrayResize(rt_high, got);  ArrayResize(rt_low, got);
   ArrayResize(rt_close, got); ArrayResize(rt_vol, got);
   for(int i=0;i<got;i++)
     {
      rt_times[i] = back[i].time;
      rt_open[i]  = back[i].open;
      rt_high[i]  = back[i].high;
      rt_low[i]   = back[i].low;
      rt_close[i] = back[i].close;
      rt_vol[i]   = (double)back[i].tick_volume;
     }

   // ---- re-derive the dataset hash from the round-tripped bars ----
   string rebuilt = SerializeCsv(rt_times, rt_open, rt_high, rt_low,
                                 rt_close, rt_vol, got);
   string roundtripSha = DslSha256Hex(rebuilt);
   if(roundtripSha != datasetHash)
     { string suffix = CleanupAfterFail(sym);
       RefuseAt(outPath, sym, "roundtrip",
                "roundtrip dataset hash "+roundtripSha+
                " != manifest dataset_hash "+datasetHash+
                " (custom symbol does not faithfully hold the fixture)"+suffix, 0);
       return; }

   // ---- success: the custom symbol provably equals the fixture ----
   // the diagnostic block (properties/last_error/stage) is carried on the
   // success record too, so the gate attaches identical observability data
   // whether stage 4 passes or fails.
   string doc = "{\"derived_tick_values\":" + DerivedBlockJson() +
                ",\"fixture_file_sha256\":" + DslCanonEscape(fixtureSha) +
                ",\"last_error\":0" +
                ",\"manifest_dataset_hash\":" + DslCanonEscape(datasetHash) +
                ",\"n_bars\":" + IntegerToString(got) +
                ",\"properties\":[" + g_propsJson + "]" +
                ",\"refused\":false" +
                ",\"roundtrip_sha256\":" + DslCanonEscape(roundtripSha) +
                ",\"stage\":\"complete\"" +
                ",\"symbol\":" + DslCanonEscape(sym) +
                "," + SymbolStateJson() +
                ",\"timeframe\":" + DslCanonEscape(tfStr) +
                ",\"verified_properties\":[" + g_verifyJson + "]}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", sym, ": ", got, " bars, dataset hash MATCHES manifest ",
         datasetHash, " symbol_state=", g_symbolState, " -> ", outPath);
  }
//+------------------------------------------------------------------+
