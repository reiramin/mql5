//+------------------------------------------------------------------+
//|  DslParityRunner.mq5 — bundle -> per-bar positions (OWNER-PENDING)|
//|                                                                  |
//|  STATUS: SOURCE-ONLY, NOT COMPILED. Written on Mac; the owner     |
//|  compiles + runs this in MT5 to produce the MQL5 side of the      |
//|  cross-engine parity (README.md). No result is claimed here.      |
//|                                                                  |
//|  Loads an executable bundle (JSON) + an offline OHLC symbol,      |
//|  evaluates the generic runtime over the CLOSED bars, and writes   |
//|  the per-bar desired-position vector to a file. The owner then    |
//|  compares it to artifacts/dsl_parity/<fixture>/expected_trace.json|
//|  ("positions" — EXACT match; logical values carry no tolerance).  |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

#include "../Include/DslJson.mqh"
#include "../Include/DslBundle.mqh"
#include "../Include/DslRuntime.mqh"

input string InpBundleFile = "dsl_parity\\canonical_ema_rsi_atr\\bundle.json";
input string InpSymbol     = "";     // empty = chart symbol (offline import)
input int    InpBars       = 400;    // bars (match the fixture's row count)
input string InpOutFile    = "dsl_parity_positions.csv";

// ---- read an entire file from MQL5\Files into a string ----
bool ReadTextFile(const string path, string &out)
  {
   int h = FileOpen(path, FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) { out=""; return false; }
   out="";
   while(!FileIsEnding(h)) out += FileReadString(h) + "\n";
   FileClose(h);
   return true;
  }

// ---- copy a built-in indicator buffer into a CHRONOLOGICAL array
//      (index 0 = oldest bar), NaN where CopyBuffer/EMPTY_VALUE fails,
//      mirroring the Python warmup NaN contract ----
bool CopyChrono(int handle, int buffer, int bars, double &dst[])
  {
   ArrayResize(dst, bars);
   double raw[]; ArraySetAsSeries(raw, true);
   if(handle==INVALID_HANDLE) { for(int i=0;i<bars;i++) dst[i]=(double)"nan"; return false; }
   if(CopyBuffer(handle, buffer, 0, bars, raw) < bars) return false;
   double znan=0.0; znan=znan/znan;
   for(int i=0;i<bars;i++)
     {
      double v = raw[bars-1-i];              // reverse: series -> chrono
      dst[i] = (v==EMPTY_VALUE) ? znan : v;
     }
   return true;
  }

// price column (open/high/low/close) into a chronological array
void CopyPriceChrono(const string sym, ENUM_TIMEFRAMES tf, int col,
                     int bars, double &dst[])
  {
   ArrayResize(dst, bars);
   MqlRates r[]; ArraySetAsSeries(r, false);   // r[0] = oldest
   int got = CopyRates(sym, tf, 0, bars, r);
   for(int i=0;i<bars;i++)
     {
      if(i>=got) { dst[i]=0.0; continue; }
      dst[i] = (col==0)?r[i].open:(col==1)?r[i].high:(col==2)?r[i].low:r[i].close;
     }
  }

// Register every indicator output the bundle declares. Baseline kinds
// only (README): EMA/SMA/RSI/ATR/BBANDS/MACD/DONCHIAN/HIGHEST/LOWEST.
bool BuildSeries(CDslJson &json, int spec, const string sym,
                 ENUM_TIMEFRAMES tf, int bars, CDslRuntime &rt)
  {
   // price columns first (operands may reference {"price":"close"} etc.)
   string cols[4] = {"open","high","low","close"};
   for(int k=0;k<4;k++)
     { double p[]; CopyPriceChrono(sym,tf,k,bars,p); rt.RegisterSeries(cols[k], p); }

   int inds = json.Member(spec, "indicators");
   int c = json.FirstChild(inds);
   while(c>=0)
     {
      string id   = json.GetStr(c,"id","");
      string kind = json.GetStr(c,"kind","");
      int period  = (int)json.GetNum(c,"period",14);
      int handle  = INVALID_HANDLE;
      double buf[];
      if(kind=="EMA")      handle=iMA(sym,tf,period,0,MODE_EMA,PRICE_CLOSE);
      else if(kind=="SMA") handle=iMA(sym,tf,period,0,MODE_SMA,PRICE_CLOSE);
      else if(kind=="RSI") handle=iRSI(sym,tf,period,PRICE_CLOSE);
      else if(kind=="ATR") handle=iATR(sym,tf,period);
      else if(kind=="BBANDS")
        {
         double dev=json.GetNum(c,"dev",2.0);
         handle=iBands(sym,tf,period,0,dev,PRICE_CLOSE);
         double mid[],up[],lo[];
         CopyChrono(handle,0,bars,mid); CopyChrono(handle,1,bars,up); CopyChrono(handle,2,bars,lo);
         rt.RegisterSeries(id,mid); rt.RegisterSeries(id+"__mid",mid);
         rt.RegisterSeries(id+"__upper",up); rt.RegisterSeries(id+"__lower",lo);
         c=json.NextSibling(c); continue;
        }
      else if(kind=="MACD")
        {
         int f=(int)json.GetNum(c,"fast",12),s=(int)json.GetNum(c,"slow",26),sg=(int)json.GetNum(c,"signal",9);
         handle=iMACD(sym,tf,f,s,sg,PRICE_CLOSE);
         double line[],sig[];
         CopyChrono(handle,0,bars,line); CopyChrono(handle,1,bars,sig);
         rt.RegisterSeries(id,line); rt.RegisterSeries(id+"__line",line);
         rt.RegisterSeries(id+"__signal",sig);
         c=json.NextSibling(c); continue;
        }
      // DONCHIAN / HIGHEST / LOWEST are manual (no single built-in);
      // owner computes them over CopyRates high/low here mirroring
      // indicators.donchian/highest/lowest, then RegisterSeries.
      else if(kind=="DONCHIAN" || kind=="HIGHEST" || kind=="LOWEST")
        {
         Print("[dsl] TODO(owner): compute ",kind," manually and register");
         c=json.NextSibling(c); continue;
        }
      if(handle==INVALID_HANDLE) { Print("[dsl] handle failed for ",kind); return false; }
      if(!CopyChrono(handle,0,bars,buf)) { Print("[dsl] CopyBuffer failed ",id); return false; }
      rt.RegisterSeries(id,buf);
      c=json.NextSibling(c);
     }
   return true;
  }

void OnStart()
  {
   string sym = (InpSymbol=="") ? _Symbol : InpSymbol;
   ENUM_TIMEFRAMES tf = _Period;

   string text;
   if(!ReadTextFile(InpBundleFile, text))
     { Print("[dsl] cannot read bundle: ", InpBundleFile); return; }

   CDslJson json;
   if(!json.Parse(text)) { Print("[dsl] JSON parse error: ", json.Error()); return; }

   CDslBundleLoader loader;
   if(!loader.Load(json)) { Print("[dsl] REFUSED: ", loader.Error()); return; }
   int spec = loader.Spec();

   CDslRuntime rt;
   if(!BuildSeries(json, spec, sym, tf, InpBars, rt))
     { Print("[dsl] series build failed: ", rt.Error()); return; }
   rt.Bind(&json, spec);

   int pos[];
   if(!rt.DesiredPositions(pos)) { Print("[dsl] eval failed: ", rt.Error()); return; }

   int h = FileOpen(InpOutFile, FILE_WRITE|FILE_CSV|FILE_ANSI);
   if(h==INVALID_HANDLE) { Print("[dsl] cannot write ", InpOutFile); return; }
   FileWrite(h, "bar", "position");
   for(int i=0;i<ArraySize(pos);i++) FileWrite(h, i, pos[i]);
   FileClose(h);
   Print("[dsl] wrote ", ArraySize(pos), " positions -> ", InpOutFile,
         " (compare to expected_trace.json[positions]; EXACT match)");
  }
//+------------------------------------------------------------------+
