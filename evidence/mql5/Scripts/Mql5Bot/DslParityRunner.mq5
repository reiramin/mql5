//+------------------------------------------------------------------+
//|  DslParityRunner.mq5 — bundle -> canonical parity trace (batch)   |
//|                                                                  |
//|  STATUS: compile-observed on Windows; the PARITY RESULT is        |
//|  OWNER-PENDING until tools/run_dsl_parity.ps1 +                   |
//|  tools/compare_dsl_parity.py report 14/14 EXACT.                  |
//|                                                                  |
//|  Input is ONLY the committed fixture files copied under           |
//|  MQL5\Files\<InpFixtureRoot>\<fixture>\ (bundle.json + ohlc.csv,  |
//|  the EXACT bytes Python evaluated — sha256-pinned by              |
//|  artifacts/dsl_parity/manifest.json). No CopyRates, no chart, no  |
//|  live history, no FILE_COMMON: import/alignment drift is          |
//|  impossible by construction.                                      |
//|                                                                  |
//|  Series are built by DslBuildSeriesFromArrays — the SAME          |
//|  canonical functions the EA path uses (DslIndicators.mqh mirrors  |
//|  of python/mql5bot/indicators.py), never iMA/iRSI/iATR handles    |
//|  whose seeding differs.                                           |
//|                                                                  |
//|  BATCH mode (default): iterates the fixture names listed in       |
//|  InpFixtureList (one per line) and writes, per fixture,           |
//|  MQL5\Files\<InpOutDir>\<fixture>.json holding the FULL canonical |
//|  parity trace                                                     |
//|      bundle_hash / ohlc_sha256 / n_bars / positions / events /    |
//|      exit_geometry / position_hash (+ spec_hash, strategy_id,     |
//|      strategy_version)                                            |
//|  — position_hash is sha256 over the canonical JSON of the         |
//|  position list, the same algorithm as dsl/parity.py. Output is    |
//|  deterministic, LF-only, and carries NO timestamps.               |
//|  A REFUSED bundle (e.g. tampered bundle_hash) writes              |
//|  {"error":...,"fixture":...,"refused":true} instead — the         |
//|  comparator requires that refusal for the tampered fixture.       |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslCanon.mqh>
#include <Mql5Bot/DslBundle.mqh>
#include <Mql5Bot/DslIndicators.mqh>
#include <Mql5Bot/DslRuntime.mqh>
#include <Mql5Bot/DslSeries.mqh>    // SAME series builder as the EA path

input string InpFixtureRoot = "Mql5Bot\\dsl_parity";      // fixture tree root (under MQL5\Files)
input string InpFixtureList = "Mql5Bot\\dsl_parity\\fixtures.txt"; // batch list (one fixture per line)
input string InpFixture     = "";                          // single-fixture mode when list is empty
input string InpOutDir      = "Mql5Bot\\dsl_parity_out";   // per-fixture <name>.json output dir

// ---- read a whole file (relative to MQL5\Files) as raw bytes ----
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

// ---- write text EXACTLY as UTF-8/LF bytes (FILE_BIN: no CRLF
//      translation, byte-deterministic on every OS) ----
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

// ---- fixture CSV ("<ts>,open,high,low,close,volume") -> chrono arrays
bool ParseOhlcCsv(const string text, datetime &times[], double &open[],
                  double &high[], double &low[], double &close[])
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
      if(StringSplit(line, ',', cols) < 5) return false;
      // "2020-01-01 05:00:00+00:00" -> "2020.01.01 05:00:00" (UTC)
      string ts = StringSubstr(cols[0], 0, 19);
      StringReplace(ts, "-", ".");
      ArrayResize(times, n+1); ArrayResize(open, n+1);
      ArrayResize(high, n+1);  ArrayResize(low, n+1);
      ArrayResize(close, n+1);
      times[n] = StringToTime(ts);
      open[n]  = StringToDouble(cols[1]);
      high[n]  = StringToDouble(cols[2]);
      low[n]   = StringToDouble(cols[3]);
      close[n] = StringToDouble(cols[4]);
      n++;
     }
   return (n > 0);
  }

// ---- exit_geometry JSON — EXACT key/value mirror of runtime.
//      exit_params (raw number tokens from the bundle, so float text
//      is identical to the Python trace) ----
string GeoNumber(CDslJson &json, const int obj, const string key,
                 const string def)
  {
   int m = json.Member(obj, key);
   if(m < 0 || json.Type(m) != DSL_JSON_NUMBER) return def;
   return json.Raw(m);
  }

string BuildExitGeometry(CDslJson &json, const int spec)
  {
   int ex = json.Member(spec, "exit");
   string trail = GeoNumber(json, ex, "trail_atr", "0.0");
   string be    = GeoNumber(json, ex, "breakeven_atr", "0.0");
   // optional keys in canonical (sorted) order: breakeven_atr,
   // percent_sl, percent_tp, points_sl, points_tp, sl_atr, tp_atr,
   // trail_atr
   string percentSl="", percentTp="", pointsSl="", pointsTp="";
   string slAtr="", tpAtr="";
   int sl = json.Member(ex, "sl");
   if(sl >= 0)
     {
      string model = json.GetStr(sl, "model", "atr");
      if(model=="atr")          slAtr = GeoNumber(json, sl, "mult", "0.0");
      else if(model=="points") { slAtr="null"; pointsSl=GeoNumber(json, sl, "points", "0.0"); }
      else                     { slAtr="null"; percentSl=GeoNumber(json, sl, "pct", "0.0"); }
     }
   int tp = json.Member(ex, "tp");
   if(tp >= 0)
     {
      string model = json.GetStr(tp, "model", "atr");
      if(model=="atr")          tpAtr = GeoNumber(json, tp, "mult", "0.0");
      else if(model=="points") { tpAtr="null"; pointsTp=GeoNumber(json, tp, "points", "0.0"); }
      else                     { tpAtr="null"; percentTp=GeoNumber(json, tp, "pct", "0.0"); }
     }
   string out = "{\"breakeven_atr\":" + be;
   if(percentSl!="") out += ",\"percent_sl\":" + percentSl;
   if(percentTp!="") out += ",\"percent_tp\":" + percentTp;
   if(pointsSl!="")  out += ",\"points_sl\":" + pointsSl;
   if(pointsTp!="")  out += ",\"points_tp\":" + pointsTp;
   if(slAtr!="")     out += ",\"sl_atr\":" + slAtr;
   if(tpAtr!="")     out += ",\"tp_atr\":" + tpAtr;
   out += ",\"trail_atr\":" + trail + "}";
   return out;
  }

void WriteRefusal(const string outPath, const string fixture,
                  const string why)
  {
   string doc = "{\"error\":" + DslCanonEscape(why) +
                ",\"fixture\":" + DslCanonEscape(fixture) +
                ",\"refused\":true}\n";
   if(!WriteTextLF(outPath, doc))
      Print("[dsl] cannot write ", outPath);
   Print("[dsl] ", fixture, " REFUSED: ", why);
  }

// process one fixture; returns true when a full trace was produced
bool RunFixture(const string fixture)
  {
   string dir     = InpFixtureRoot + "\\" + fixture;
   string outPath = InpOutDir + "\\" + fixture + ".json";

   uchar bundleBytes[];
   if(!ReadFileBytes(dir + "\\bundle.json", bundleBytes))
     { WriteRefusal(outPath, fixture, "cannot read bundle.json"); return false; }
   uchar ohlcBytes[];
   if(!ReadFileBytes(dir + "\\ohlc.csv", ohlcBytes))
     { WriteRefusal(outPath, fixture, "cannot read ohlc.csv"); return false; }

   // provenance: sha256 over the EXACT committed csv bytes — the
   // comparator binds this to the manifest pin, so a converted or
   // re-imported frame can never masquerade as the fixture
   string ohlcSha = DslSha256HexBytes(ohlcBytes);

   CDslJson json;
   if(!json.Parse(BytesToText(bundleBytes)))
     { WriteRefusal(outPath, fixture, "JSON parse error: "+json.Error());
       return false; }

   CDslBundleLoader loader;
   if(!loader.Load(json))                     // includes bundle_hash
     { WriteRefusal(outPath, fixture, loader.Error()); return false; }
   int spec = loader.Spec();

   datetime times[];
   double open[], high[], low[], close[];
   if(!ParseOhlcCsv(BytesToText(ohlcBytes), times, open, high, low, close))
     { WriteRefusal(outPath, fixture, "malformed ohlc.csv"); return false; }

   CDslRuntime rt;
   string err="";
   if(!DslBuildSeriesFromArrays(json, spec, times, open, high, low,
                                close, rt, err))
     { WriteRefusal(outPath, fixture, "series build refused: "+err);
       return false; }
   rt.Bind(&json, spec);

   int pos[];
   if(!rt.DesiredPositions(pos))
     { WriteRefusal(outPath, fixture, "eval refused: "+rt.Error());
       return false; }

   // ---- canonical position list + hash (parity.parity_trace) ----
   int n = ArraySize(pos);
   string posJson = "[";
   for(int i=0;i<n;i++)
     {
      if(i>0) posJson += ",";
      posJson += IntegerToString(pos[i]);
     }
   posJson += "]";
   string posHash = DslSha256Hex(posJson);

   // events: state transitions (bar, from, to)
   string events = "[";
   int prev = 0;
   bool first = true;
   for(int i=0;i<n;i++)
     {
      if(pos[i]!=prev)
        {
         if(!first) events += ",";
         first = false;
         events += "{\"bar\":" + IntegerToString(i) +
                   ",\"from\":" + IntegerToString(prev) +
                   ",\"to\":" + IntegerToString(pos[i]) + "}";
         prev = pos[i];
        }
     }
   events += "]";

   int root = json.Root;
   string trace = "{\"bundle_hash\":" + DslCanonEscape(
         json.GetStr(root,"bundle_hash","")) +
      ",\"events\":" + events +
      ",\"exit_geometry\":" + BuildExitGeometry(json, spec) +
      ",\"n_bars\":" + IntegerToString(n) +
      ",\"ohlc_sha256\":" + DslCanonEscape(ohlcSha) +
      ",\"position_hash\":\"" + posHash + "\"" +
      ",\"positions\":" + posJson +
      ",\"spec_hash\":" + DslCanonEscape(
         json.GetStr(json.Member(root,"identity"),"spec_hash","")) +
      ",\"strategy_id\":" + DslCanonEscape(
         json.GetStr(spec,"strategy_id","")) +
      ",\"strategy_version\":" + IntegerToString(
         (int)json.GetNum(spec,"version",0)) + "}\n";

   if(!WriteTextLF(outPath, trace))
     { Print("[dsl] cannot write ", outPath); return false; }
   Print("[dsl] ", fixture, ": ", n, " bars -> ", outPath,
         " | position_hash=", posHash);
   return true;
  }

void OnStart()
  {
   string fixtures[];
   int count = 0;
   if(InpFixtureList != "")
     {
      uchar listBytes[];
      if(!ReadFileBytes(InpFixtureList, listBytes))
        { Print("[dsl] cannot read fixture list: ", InpFixtureList);
          return; }
      string lines[];
      int nLines = StringSplit(BytesToText(listBytes), '\n', lines);
      for(int i=0;i<nLines;i++)
        {
         string name = lines[i];
         StringReplace(name, "\r", "");
         StringTrimLeft(name);
         StringTrimRight(name);
         if(StringLen(name)==0 || StringGetCharacter(name,0)=='#')
            continue;
         ArrayResize(fixtures, count+1);
         fixtures[count++] = name;
        }
     }
   else if(InpFixture != "")
     {
      ArrayResize(fixtures, 1);
      fixtures[0] = InpFixture;
      count = 1;
     }
   if(count==0)
     { Print("[dsl] no fixtures to run (empty list)"); return; }

   int traced=0, refused=0;
   for(int i=0;i<count;i++)
     {
      if(RunFixture(fixtures[i])) traced++;
      else refused++;
     }
   Print("[dsl] batch done: ", traced, " trace(s), ", refused,
         " refusal(s) of ", count, " fixture(s) -> ", InpOutDir,
         " (compare with tools/compare_dsl_parity.py; EXACT only)");
  }
//+------------------------------------------------------------------+
