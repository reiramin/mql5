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
//|  Contract (mirrors the DSL-parity pattern that already works):    |
//|   1. read the fixture CSV as raw bytes; sha256 == manifest        |
//|      dataset_hash, else refuse (a converted frame is not the      |
//|      fixture).                                                    |
//|   2. create/update a custom symbol; set every property from the   |
//|      manifest broker_spec, filling currency_base/currency_margin  |
//|      from the SymbolSpec export; a missing property refuses and    |
//|      creates nothing.                                             |
//|   3. write the bars via CustomRatesUpdate, read them back, and     |
//|      re-serialize to the EXACT pandas float_format="%.10f" / LF    |
//|      CSV byte stream; its sha256 must again equal the manifest     |
//|      dataset_hash. Any mismatch REFUSES and deletes the symbol -   |
//|      the import never half-lands.                                 |
//|   Output MQL5\Files\<InpOutDir>\<symbol>.json:                    |
//|     {"refused":false,"symbol":...,"n_bars":...,                   |
//|      "manifest_dataset_hash":...,"fixture_file_sha256":...,       |
//|      "roundtrip_sha256":...,"timeframe":...}                      |
//|   or {"error":...,"symbol":...,"refused":true} on any refusal.    |
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
//| refusal: write nothing but the refusal record, create no symbol  |
//+------------------------------------------------------------------+
void WriteRefusal(const string outPath, const string symbol,
                  const string why)
  {
   string doc = "{\"error\":" + DslCanonEscape(why) +
                ",\"refused\":true" +
                ",\"symbol\":" + DslCanonEscape(symbol) + "}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", symbol, " REFUSED: ", why);
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

   // ---- 1. read the committed fixture CSV as raw bytes -----------
   uchar csvBytes[];
   if(!ReadFileBytes(InpFixtureCsv, csvBytes))
     { WriteRefusal(outPath, sym, "cannot read fixture csv: "+InpFixtureCsv);
       return; }
   string fixtureSha = DslSha256HexBytes(csvBytes);

   // ---- read + parse the gold manifest (broker_spec + dataset_hash)
   uchar manBytes[];
   if(!ReadFileBytes(InpManifest, manBytes))
     { WriteRefusal(outPath, sym, "cannot read manifest: "+InpManifest);
       return; }
   CDslJson man;
   if(!man.Parse(BytesToText(manBytes)))
     { WriteRefusal(outPath, sym, "manifest JSON parse error: "+man.Error());
       return; }
   int mroot = man.Root;
   int bspec = man.Member(mroot, "broker_spec");
   if(bspec < 0)
     { WriteRefusal(outPath, sym, "manifest has no broker_spec"); return; }

   string datasetHash = man.GetStr(mroot, "dataset_hash", "");
   if(datasetHash == "")
     { WriteRefusal(outPath, sym, "manifest has no dataset_hash"); return; }
   string tfStr = man.GetStr(mroot, "timeframe", "");
   ENUM_TIMEFRAMES tf;
   if(!TimeframeFromString(tfStr, tf))
     { WriteRefusal(outPath, sym, "manifest timeframe unusable: "+tfStr);
       return; }

   // the staged fixture MUST be the frozen one, byte-for-byte
   if(fixtureSha != datasetHash)
     { WriteRefusal(outPath, sym, "fixture csv sha256 "+fixtureSha+
                    " != manifest dataset_hash "+datasetHash+
                    " (converted/foreign frame, not the frozen fixture)");
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
     { WriteRefusal(outPath, sym,
                    "manifest broker_spec missing property: "+missing);
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
     { WriteRefusal(outPath, sym,
                    "currency_base/currency_margin absent from the "
                    "SymbolSpec export ("+InpSymbolSpec+") and not in the "
                    "manifest - refusing rather than inventing them");
       return; }

   // ---- parse the fixture bars ------------------------------------
   datetime times[]; double open[], high[], low[], close[], volume[];
   int nBars=0;
   if(!ParseFixtureCsv(BytesToText(csvBytes), times, open, high, low, close,
                       volume, nBars))
     { WriteRefusal(outPath, sym, "malformed fixture csv"); return; }

   // ---- 2b. create the custom symbol and set every property -------
   // clean any prior instance so a stale symbol cannot masquerade
   CustomRatesDelete(sym, 0, LONG_MAX);
   CustomSymbolDelete(sym);
   if(!CustomSymbolCreate(sym, InpSymbolGroup))
     { WriteRefusal(outPath, sym, "CustomSymbolCreate failed, err="+
                    IntegerToString(GetLastError())); return; }

   bool sok = true;
   sok = sok && CustomSymbolSetInteger(sym, SYMBOL_DIGITS, (long)digits);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_POINT, point);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_TRADE_TICK_SIZE, tickSize);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_TRADE_TICK_VALUE, tickValProfit);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT, tickValProfit);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS, tickValLoss);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE, contractSize);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_VOLUME_MIN, volMin);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_VOLUME_MAX, volMax);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_VOLUME_STEP, volStep);
   sok = sok && CustomSymbolSetDouble(sym, SYMBOL_VOLUME_LIMIT, volLimit);
   sok = sok && CustomSymbolSetInteger(sym, SYMBOL_TRADE_STOPS_LEVEL, (long)stopsLevel);
   sok = sok && CustomSymbolSetInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL, (long)freezeLevel);
   sok = sok && CustomSymbolSetString(sym, SYMBOL_CURRENCY_PROFIT, ccyProfit);
   sok = sok && CustomSymbolSetString(sym, SYMBOL_CURRENCY_BASE, ccyBase);
   sok = sok && CustomSymbolSetString(sym, SYMBOL_CURRENCY_MARGIN, ccyMargin);
   if(!sok)
     { CustomSymbolDelete(sym);
       WriteRefusal(outPath, sym, "CustomSymbolSet* failed, err="+
                    IntegerToString(GetLastError())); return; }

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
   if(CustomRatesUpdate(sym, rates) < 0)
     { CustomSymbolDelete(sym);
       WriteRefusal(outPath, sym, "CustomRatesUpdate failed, err="+
                    IntegerToString(GetLastError())); return; }

   // ---- read them back at the fixture timeframe -------------------
   MqlRates back[];
   int got = CopyRates(sym, tf, 0, nBars, back);
   if(got != nBars)
     { CustomSymbolDelete(sym);
       WriteRefusal(outPath, sym, "readback bar count "+IntegerToString(got)+
                    " != "+IntegerToString(nBars)+
                    " (timeframe generation perturbed the fixture)");
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
     { CustomSymbolDelete(sym);
       WriteRefusal(outPath, sym, "roundtrip dataset hash "+roundtripSha+
                    " != manifest dataset_hash "+datasetHash+
                    " (custom symbol does not faithfully hold the fixture)");
       return; }

   // ---- success: the custom symbol provably equals the fixture ----
   string doc = "{\"fixture_file_sha256\":" + DslCanonEscape(fixtureSha) +
                ",\"manifest_dataset_hash\":" + DslCanonEscape(datasetHash) +
                ",\"n_bars\":" + IntegerToString(got) +
                ",\"refused\":false" +
                ",\"roundtrip_sha256\":" + DslCanonEscape(roundtripSha) +
                ",\"symbol\":" + DslCanonEscape(sym) +
                ",\"timeframe\":" + DslCanonEscape(tfStr) + "}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[import] cannot write ", outPath);
   Print("[import] ", sym, ": ", got, " bars, dataset hash MATCHES manifest ",
         datasetHash, " -> ", outPath);
  }
//+------------------------------------------------------------------+
