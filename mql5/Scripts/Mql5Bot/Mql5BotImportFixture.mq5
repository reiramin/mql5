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
//|  SYMBOL NAME (GOLD_EURUSD): MT5 restricts custom-symbol names to   |
//|  Latin letters/digits and the punctuation ". _ & #" only, <=32    |
//|  chars incl. the terminating 0. "GOLD_EURUSD" (11 chars, letters   |
//|  + "_") satisfies this. The script validates the name and REFUSES  |
//|  before creating anything if it does not. The custom-symbol path   |
//|  is InpSymbolGroup ("Mql5Bot\\gold"), which places it under        |
//|  Custom\Mql5Bot\gold and cannot collide with a broker symbol; if  |
//|  a NON-custom (broker) symbol of the same name already exists the  |
//|  script REFUSES rather than shadow it.                            |
//|                                                                  |
//|  MT5 NAME/PATH RULE (documented + enforced): custom-symbol names   |
//|  are unique across the ENTIRE symbol hierarchy, so SymbolExist is  |
//|  a GLOBAL existence check (not per-folder). Also, CustomSymbolCreate|
//|  treats a symbol_path whose LAST element equals the symbol name as  |
//|  the symbol itself rather than a folder; the script therefore       |
//|  REFUSES when the last element of InpSymbolGroup equals             |
//|  InpSymbolName (an ambiguous name/group pair) before creating.     |
//|                                                                  |
//|  IDEMPOTENCY (err=5304 ERR_CUSTOM_SYMBOL_EXIST): a prior run that   |
//|  created the symbol and then failed at a later stage can leave the  |
//|  custom symbol behind; a bare CustomSymbolCreate then fails with    |
//|  5304. This script resolves the symbol STATE fail-closed BEFORE     |
//|  creating: SymbolExist first; if it exists AND is custom, deselect  |
//|  + CustomSymbolDelete + VERIFY it is gone, then create fresh; if    |
//|  the delete fails, name the failing call and its _LastError and     |
//|  REFUSE (never charge into a create that will 5304); if it exists   |
//|  but is NOT custom, refuse (broker symbol) untouched. RUNNING THE   |
//|  GATE TWICE IN A ROW MUST PRODUCE IDENTICAL RESULTS -- a clean       |
//|  second run either succeeds identically or refuses at symbol_state  |
//|  with the same named reason.                                       |
//|                                                                  |
//|  err=5306 FAMILY (custom-symbol STATE / VALUE errors, 53xx):       |
//|   - STATE: a symbol SELECTED in Market Watch cannot be deleted     |
//|     (5306) or have its properties changed. The script therefore    |
//|     deselects the symbol (SymbolSelect(sym,false)) BEFORE any      |
//|     delete or CustomSymbolSet*, and selects it (SymbolSelect(...,  |
//|     true)) only AFTER every property is set and the bars written.  |
//|     A stale prior custom symbol is detected (SymbolExist w/        |
//|     is_custom) and recreated deterministically.                   |
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
//|  tick_value_profit and then, in the verify_properties stage,       |
//|  READS BACK the terminal-DERIVED _PROFIT/_LOSS and REFUSES unless  |
//|  both equal the manifest broker values -- because tick_value_loss  |
//|  is the field the P0-1 sizing correction rests on, a custom        |
//|  symbol whose derived tick values diverge from the broker's would  |
//|  NOT reproduce broker sizing in the tester, and claiming so would  |
//|  be false. The derived pair is recorded as a NAMED, SCOPED         |
//|  limitation (derived_tick_values in the JSON): proven by derived-  |
//|  equality at import time, never by storage.                       |
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
//|    entry and both derived tick values read back equal.            |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslCanon.mqh>   // DslSha256HexBytes / DslSha256Hex / DslCanonEscape

input string InpFixtureCsv  = "Mql5Bot\\gold_import\\gold_fixture.csv"; // fixture CSV (under MQL5\Files)
input string InpManifest    = "Mql5Bot\\gold_import\\manifest.json";    // gold manifest (broker_spec + dataset_hash)
input string InpSymbolSpec  = "Mql5Bot\\broker_exports\\EURUSD.json";   // stage-3 SymbolSpec export
input string InpSymbolName  = "GOLD_EURUSD";                             // custom symbol to create/update
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
// this property; prove the derived value equals the manifest broker value.
bool VerDerivedD(const string sym, const ENUM_SYMBOL_INFO_DOUBLE id,
                 const string enumName, const double manifestVal,
                 const string source)
  {
   double got = 0.0;
   bool fetched = SymbolInfoDouble(sym, id, got);
   string want = DoubleToString(manifestVal, 10);
   string have = DoubleToString(got, 10);
   bool ok = fetched && (want == have);
   if(g_derivedCount>0) g_derivedJson += ",";
   g_derivedJson += "{\"enum\":"          + DslCanonEscape(enumName) +
                    ",\"manifest_value\":"+ DslCanonEscape(want) +
                    ",\"ok\":"            + (ok ? "true" : "false") +
                    ",\"readback\":"      + DslCanonEscape(
                        fetched ? have : "(SymbolInfoDouble failed)") +
                    ",\"settable\":false" +
                    ",\"source\":"        + DslCanonEscape(source) + "}";
   g_derivedCount++;
   if(!ok) MarkVerifyFail("SymbolInfoDouble(derived readback)", enumName, have);
   return ok;
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
   return "{\"limitation\":" + DslCanonEscape(
            "SYMBOL_TRADE_TICK_VALUE_PROFIT/SYMBOL_TRADE_TICK_VALUE_LOSS are "
            "calculated by MT5 and rejected by CustomSymbolSetDouble (5307 "
            "ERR_CUSTOM_SYMBOL_PROPERTY_WRONG); faithfulness is proven by "
            "readback equality against the manifest broker values, never by "
            "setting") +
          ",\"properties\":["    + g_derivedJson + "]" +
          ",\"trade_calc_mode\":" + DslCanonEscape(g_calcModeStr) + "}";
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
                ",\"verified_properties\":[" + g_verifyJson + "]}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", symbol, " REFUSED [", stage, "]: ", why,
         " (last_error=", lastErr, ")");
  }

//+------------------------------------------------------------------+
//| deselect + drop a custom symbol and VERIFY it is gone.            |
//| A SELECTED symbol cannot be deleted (5306), so deselect first.    |
//| Returns true ONLY when SymbolExist reports the name is no longer  |
//| present (so a following CustomSymbolCreate cannot 5304). On       |
//| failure, whichCall names the call that failed and lastErr is its  |
//| _LastError -- the caller REFUSES with that fact rather than       |
//| colliding with ERR_CUSTOM_SYMBOL_EXIST.                          |
//+------------------------------------------------------------------+
bool DropCustomSymbolChecked(const string sym, string &whichCall, int &lastErr)
  {
   whichCall = ""; lastErr = 0;
   SymbolSelect(sym, false);                 // 5306-safe: deselect before delete
   CustomRatesDelete(sym, 0, LONG_MAX);      // clear any bars (no-op if none)
   ResetLastError();
   if(!CustomSymbolDelete(sym))
     { whichCall = "CustomSymbolDelete"; lastErr = GetLastError(); return false; }
   bool isCustom = false;
   ResetLastError();
   if(SymbolExist(sym, isCustom))            // it MUST actually be gone now
     { whichCall = "SymbolExist(still present after delete)";
       lastErr = GetLastError(); return false; }
   return true;
  }

//+------------------------------------------------------------------+
//| best-effort cleanup after a POST-create refusal. Never blocks the |
//| refusal; returns a human suffix noting any leftover so the record |
//| stays honest. A leftover is self-healed by the pre-create,        |
//| verified drop on the next run (idempotency).                     |
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
   // be shadowed. A stale custom symbol from a prior FAILED run makes a
   // bare create 5304 (ERR_CUSTOM_SYMBOL_EXIST): delete it, VERIFY it is
   // gone, and REFUSE fail-closed if the delete fails -- never charge into
   // a create that will 5304. Running twice in a row is therefore
   // deterministic (identical success, or the same named symbol_state
   // refusal).
   bool isCustom=false;
   if(SymbolExist(sym, isCustom))
     {
      if(!isCustom)
        { RefuseAt(outPath, sym, "symbol_state",
                   "a NON-custom (broker) symbol named "+sym+
                   " already exists; refusing to shadow a broker symbol", 0);
          return; }
      // stale custom symbol from a prior run: drop it AND verify it is gone
      string wc=""; int le=0;
      if(!DropCustomSymbolChecked(sym, wc, le))
        { RefuseAt(outPath, sym, "symbol_state",
                   "a stale custom symbol named "+sym+" from a prior run "
                   "could not be removed ("+wc+" failed); refusing rather "
                   "than colliding with ERR_CUSTOM_SYMBOL_EXIST (5304)", le);
          return; }
     }
   else
     {
      // even if SymbolExist says no, ensure it is not lingering selected
      SymbolSelect(sym, false);
     }

   ResetLastError();
   if(!CustomSymbolCreate(sym, InpSymbolGroup))
     { RefuseAt(outPath, sym, "create_symbol",
                "CustomSymbolCreate failed for group "+InpSymbolGroup+
                " (last_error 5304 = ERR_CUSTOM_SYMBOL_EXIST means a prior "
                "symbol survived deletion)", GetLastError());
       return; }
   // the symbol is freshly created and NOT selected in Market Watch, so it
   // is safe to set every property. We select it only after bars are written.

   // ---- 2c. set every property ONE AT A TIME, checking each -------
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
   sok = sok && SetS(sym, SYMBOL_CURRENCY_PROFIT, "SYMBOL_CURRENCY_PROFIT",
                     ccyProfit, "manifest.broker_spec.currency_profit");
   sok = sok && SetS(sym, SYMBOL_CURRENCY_BASE, "SYMBOL_CURRENCY_BASE",
                     ccyBase, "SymbolSpec("+InpSymbolSpec+").symbol.currency_base");
   sok = sok && SetS(sym, SYMBOL_CURRENCY_MARGIN, "SYMBOL_CURRENCY_MARGIN",
                     ccyMargin, "SymbolSpec("+InpSymbolSpec+").symbol.currency_margin");
   if(!sok)
     { int err = GetLastError();
       string suffix = CleanupAfterFail(sym);
       RefuseAt(outPath, sym, "set_properties",
                g_failCall+"("+g_failEnum+"="+g_failValue+" from "+g_failSource+
                ") failed"+suffix, err);
       return; }

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
   // NOT settable (5307): the terminal-DERIVED tick values must equal the
   // manifest broker values, or the tester legs on this symbol would NOT
   // reproduce broker sizing (tick_value_loss underpins the P0-1 sizing
   // correction) -- REFUSE rather than certify a false economics claim.
   bool dok = true;
   dok = VerDerivedD(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT,
                     "SYMBOL_TRADE_TICK_VALUE_PROFIT", tickValProfit,
                     "manifest.broker_spec.tick_value_profit") && dok;
   dok = VerDerivedD(sym, SYMBOL_TRADE_TICK_VALUE_LOSS,
                     "SYMBOL_TRADE_TICK_VALUE_LOSS", tickValLoss,
                     "manifest.broker_spec.tick_value_loss") && dok;
   if(!dok)
     { string suffix = CleanupAfterFail(sym);
       RefuseAt(outPath, sym, "verify_properties",
                "terminal-DERIVED "+g_failEnum+" read back as "+g_failValue+
                " != manifest broker value (trade_calc_mode="+g_calcModeStr+
                "); a tester leg on this symbol would NOT reproduce broker "
                "tick-value economics"+suffix, 0);
       return; }

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
                ",\"timeframe\":" + DslCanonEscape(tfStr) +
                ",\"verified_properties\":[" + g_verifyJson + "]}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", sym, ": ", got, " bars, dataset hash MATCHES manifest ",
         datasetHash, " -> ", outPath);
  }
//+------------------------------------------------------------------+
