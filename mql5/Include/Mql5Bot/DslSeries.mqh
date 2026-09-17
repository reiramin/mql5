//+------------------------------------------------------------------+
//| DslSeries.mqh — canonical series construction from OHLC arrays   |
//|                                                                  |
//| DslBuildSeriesFromArrays() is the SINGLE series-construction path |
//| shared by the EA (arrays from CopyRates, see DslExecution.mqh)    |
//| and the parity runner (arrays from the committed fixture CSV,     |
//| see Scripts/Mql5Bot/DslParityRunner.mq5): every indicator output  |
//| is computed by the canonical array ports in DslIndicators.mqh —   |
//| NEVER by iMA/iRSI/iATR handles, whose warmup/seed semantics       |
//| differ from python/mql5bot/indicators.py and would silently break |
//| the exact-parity contract.                                        |
//+------------------------------------------------------------------+
#ifndef MQL5BOT_DSL_SERIES_MQH
#define MQL5BOT_DSL_SERIES_MQH

#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslIndicators.mqh>
#include <Mql5Bot/DslRuntime.mqh>

// applied-price column selector; refuses anything else (never guesses)
bool DslAppliedColumn(const string applied, const double &open[],
                      const double &high[], const double &low[],
                      const double &close[], double &dst[])
  {
   if(applied=="close" || applied=="") { ArrayCopy(dst, close); return true; }
   if(applied=="open")  { ArrayCopy(dst, open);  return true; }
   if(applied=="high")  { ArrayCopy(dst, high);  return true; }
   if(applied=="low")   { ArrayCopy(dst, low);   return true; }
   return false;
  }

// positive shift delays by whole CLOSED bars (causal; mirrors
// runtime.compute_indicators: applied to the BARE id series only)
void DslApplyShift(const double &src[], const int shift, double &dst[])
  {
   int n = ArraySize(src);
   DslFillNaN(dst, n);
   if(shift < n)
      for(int i=shift;i<n;i++) dst[i]=src[i-shift];
  }

// Register price columns, bar times and every indicator output the
// bundle declares, computed with the CANONICAL ports
// (DslIndicators.mqh). Supported kinds mirror DslSupportedKinds():
// EMA/RSI/ATR (fixture-verified) + DONCHIAN/HIGHEST/LOWEST; anything
// else is refused here even if a tampered bundle slipped past the
// loader.
bool DslBuildSeriesFromArrays(CDslJson &json, const int spec,
                              const datetime &times[],
                              const double &open[], const double &high[],
                              const double &low[], const double &close[],
                              CDslRuntime &rt, string &err)
  {
   string cols[4] = {"open","high","low","close"};
   for(int k=0;k<4;k++)
     {
      double p[];
      if(k==0) ArrayCopy(p, open);
      else if(k==1) ArrayCopy(p, high);
      else if(k==2) ArrayCopy(p, low);
      else ArrayCopy(p, close);
      if(!rt.RegisterSeries(cols[k], p)) { err=rt.Error(); return false; }
     }
   if(!rt.RegisterTimes(times)) { err=rt.Error(); return false; }

   int inds = json.Member(spec, "indicators");
   int c = json.FirstChild(inds);
   while(c>=0)
     {
      string id   = json.GetStr(c,"id","");
      string kind = json.GetStr(c,"kind","");
      int period  = (int)json.GetNum(c,"period",14);
      int shift   = (int)json.GetNum(c,"shift",0);
      string applied = json.GetStr(c,"applied","close");
      double vals[], buf[];
      if(kind!="ATR" && kind!="DONCHIAN")
        {
         if(!DslAppliedColumn(applied, open, high, low, close, vals))
           { err="unsupported applied price '"+applied+"' for "+id;
             return false; }
        }
      bool ok=true;
      if(kind=="EMA")          DslEma(vals, period, buf);
      else if(kind=="RSI")     DslRsi(vals, period, buf);
      else if(kind=="HIGHEST") DslHighest(vals, period, buf);
      else if(kind=="LOWEST")  DslLowest(vals, period, buf);
      else if(kind=="ATR")     DslAtr(high, low, close, period, buf);
      else if(kind=="DONCHIAN")
        {
         double up[],lo[];
         DslDonchian(high, low, period, up, lo);
         ok = rt.RegisterSeries(id+"__upper",up) &&
              rt.RegisterSeries(id+"__lower",lo);
         ArrayCopy(buf, up);               // bare id -> upper channel
        }
      else
        { err="unsupported indicator kind '"+kind+"' — refused";
          return false; }
      if(!ok) { err=rt.Error(); return false; }
      if(shift>0)
        {
         double shifted[];
         DslApplyShift(buf, shift, shifted);   // bare id only (mirror)
         if(!rt.RegisterSeries(id, shifted)) { err=rt.Error(); return false; }
        }
      else if(!rt.RegisterSeries(id, buf)) { err=rt.Error(); return false; }
      c=json.NextSibling(c);
     }
   return true;
  }

#endif // MQL5BOT_DSL_SERIES_MQH
