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
//|  Custom\Mql5Bot\gold and cannot collide with a broker symbol; if   |
//|  a NON-custom (broker) symbol of the same name already exists the  |
//|  script REFUSES rather than shadow it.                            |
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
//|     out of the range MT5 accepts (5308). Properties are set ONE    |
//|     AT A TIME; the return of EACH call is checked and, on failure, |
//|     the diagnostic names the property, its enum, its value, its    |
//|     source field and _LastError. A property is never silently      |
//|     skipped -- a skipped property means the symbol is not the      |
//|     certified one, so any failure REFUSES.                        |
//|                                                                  |
//|  OBSERVABILITY: EVERY outcome writes a JSON diagnostic to          |
//|  MQL5\Files\<InpOutDir>\<symbol>.json -- especially a refusal,     |
//|  which previously wrote nothing usable. The record carries:       |
//|   {"refused":bool,"symbol":...,"stage":...,"last_error":int,      |
//|    "failed_call":...,"failed_property":<enum name>,               |
//|    "failed_value":...,"failed_source":<manifest/spec field>,      |
//|    "properties":[{"enum","value","source","ok","last_error"}...], |
//|    "error":...}                                                   |
//|  On success it ALSO carries the faithful-import fields:           |
//|    fixture_file_sha256, manifest_dataset_hash, n_bars,            |
//|    roundtrip_sha256, timeframe. The gate attaches this file to     |
//|    stage_4.json whether the import passes or fails.               |
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
input string InpOutDir      = "Mql5Bot\\gold_import_out";               // result JSON dir

//+------------------------------------------------------------------+
//| raw-byte file IO (relative to MQL5\Files) - byte-deterministic    |
//+------------------------------------------------------------------+
bool ReadFileBytes(const string path, uchar &bytes[])
  {
   int h = FileOpen(path, FILE_READ|FILE_BIN);
   if(h==INVALID_HANDLE) return false;
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
   int h = FileOpen(path, FILE_WRITE|FILE_BIN);
   if(h==INVALID_HANDLE) return false;
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
//| diagnostic writer: EVERY outcome writes a populated JSON here.    |
//| refusal record carries the failing property/value/source/enum    |
//| and _LastError so the gate is never blind again.                 |
//+------------------------------------------------------------------+
void RefuseAt(const string outPath, const string symbol, const string stage,
              const string why, const int lastErr)
  {
   string props = "[" + g_propsJson + "]";
   string doc = "{\"error\":"          + DslCanonEscape(why) +
                ",\"failed_call\":"     + DslCanonEscape(g_failCall) +
                ",\"failed_property\":" + DslCanonEscape(g_failEnum) +
                ",\"failed_source\":"   + DslCanonEscape(g_failSource) +
                ",\"failed_value\":"    + DslCanonEscape(g_failValue) +
                ",\"last_error\":"      + IntegerToString(lastErr) +
                ",\"properties\":"      + props +
                ",\"refused\":true" +
                ",\"stage\":"           + DslCanonEscape(stage) +
                ",\"symbol\":"          + DslCanonEscape(symbol) + "}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", symbol, " REFUSED [", stage, "]: ", why,
         " (last_error=", lastErr, ")");
  }

//+------------------------------------------------------------------+
//| deselect + drop a custom symbol (5306-safe: a SELECTED symbol     |
//| cannot be deleted, so deselect first)                            |
//+------------------------------------------------------------------+
void DropSymbol(const string sym)
  {
   SymbolSelect(sym, false);
   CustomRatesDelete(sym, 0, LONG_MAX);
   CustomSymbolDelete(sym);
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
//| main import                                                      |
//+------------------------------------------------------------------+
void OnStart()
  {
   string sym     = InpSymbolName;
   string outPath = InpOutDir + "\\" + sym + ".json";

   // ---- 0. custom-symbol NAME must satisfy MT5's rules ------------
   if(!ValidCustomSymbolName(sym))
     { RefuseAt(outPath, sym, "name_check",
                "symbol name violates MT5 custom-symbol rules (Latin "
                "letters/digits and only . _ & #, <=31 chars): "+sym, 0);
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

   // ---- 2b. resolve symbol STATE deterministically (err=5306 guard)-
   // A broker (non-custom) symbol of the same name must never be shadowed.
   // A selected symbol cannot be deleted or mutated, so we always deselect
   // first, then recreate the custom symbol from clean.
   bool isCustom=false;
   if(SymbolExist(sym, isCustom))
     {
      if(!isCustom)
        { RefuseAt(outPath, sym, "symbol_state",
                   "a NON-custom (broker) symbol named "+sym+
                   " already exists; refusing to shadow a broker symbol", 0);
          return; }
      // stale custom symbol from a prior run: drop it deterministically
      DropSymbol(sym);
     }
   else
     {
      // even if SymbolExist says no, ensure it is not lingering selected
      SymbolSelect(sym, false);
     }

   ResetLastError();
   if(!CustomSymbolCreate(sym, InpSymbolGroup))
     { RefuseAt(outPath, sym, "create_symbol",
                "CustomSymbolCreate failed for group "+InpSymbolGroup,
                GetLastError());
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
   sok = sok && SetD(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT,
                     "SYMBOL_TRADE_TICK_VALUE_PROFIT", tickValProfit,
                     "manifest.broker_spec.tick_value_profit");
   sok = sok && SetD(sym, SYMBOL_TRADE_TICK_VALUE_LOSS,
                     "SYMBOL_TRADE_TICK_VALUE_LOSS", tickValLoss,
                     "manifest.broker_spec.tick_value_loss");
   sok = sok && SetD(sym, SYMBOL_TRADE_CONTRACT_SIZE,
                     "SYMBOL_TRADE_CONTRACT_SIZE", contractSize,
                     "manifest.broker_spec.contract_size");
   sok = sok && SetD(sym, SYMBOL_VOLUME_MIN, "SYMBOL_VOLUME_MIN", volMin,
                     "manifest.broker_spec.volume_min");
   sok = sok && SetD(sym, SYMBOL_VOLUME_MAX, "SYMBOL_VOLUME_MAX", volMax,
                     "manifest.broker_spec.volume_max");
   sok = sok && SetD(sym, SYMBOL_VOLUME_STEP, "SYMBOL_VOLUME_STEP", volStep,
                     "manifest.broker_spec.volume_step");
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
       DropSymbol(sym);
       RefuseAt(outPath, sym, "set_properties",
                g_failCall+"("+g_failEnum+"="+g_failValue+" from "+g_failSource+
                ") failed", err);
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
       DropSymbol(sym);
       RefuseAt(outPath, sym, "write_bars", "CustomRatesUpdate failed", err);
       return; }

   // ---- select the symbol ONLY now: after every property is set and
   //      the bars are written (a selected symbol cannot be mutated) --
   if(!SymbolSelect(sym, true))
     { int err = GetLastError();
       DropSymbol(sym);
       RefuseAt(outPath, sym, "select_symbol",
                "SymbolSelect(true) failed after import", err);
       return; }

   // ---- read them back at the fixture timeframe (explicit sym/tf) --
   MqlRates back[];
   int got = CopyRates(sym, tf, 0, nBars, back);
   if(got != nBars)
     { int err = GetLastError();
       DropSymbol(sym);
       RefuseAt(outPath, sym, "readback",
                "readback bar count "+IntegerToString(got)+
                " != "+IntegerToString(nBars)+
                " (timeframe generation perturbed the fixture)", err);
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
     { DropSymbol(sym);
       RefuseAt(outPath, sym, "roundtrip",
                "roundtrip dataset hash "+roundtripSha+
                " != manifest dataset_hash "+datasetHash+
                " (custom symbol does not faithfully hold the fixture)", 0);
       return; }

   // ---- success: the custom symbol provably equals the fixture ----
   // the diagnostic block (properties/last_error/stage) is carried on the
   // success record too, so the gate attaches identical observability data
   // whether stage 4 passes or fails.
   string doc = "{\"fixture_file_sha256\":" + DslCanonEscape(fixtureSha) +
                ",\"last_error\":0" +
                ",\"manifest_dataset_hash\":" + DslCanonEscape(datasetHash) +
                ",\"n_bars\":" + IntegerToString(got) +
                ",\"properties\":[" + g_propsJson + "]" +
                ",\"refused\":false" +
                ",\"roundtrip_sha256\":" + DslCanonEscape(roundtripSha) +
                ",\"stage\":\"complete\"" +
                ",\"symbol\":" + DslCanonEscape(sym) +
                ",\"timeframe\":" + DslCanonEscape(tfStr) + "}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", sym, ": ", got, " bars, dataset hash MATCHES manifest ",
         datasetHash, " -> ", outPath);
  }
//+------------------------------------------------------------------+
