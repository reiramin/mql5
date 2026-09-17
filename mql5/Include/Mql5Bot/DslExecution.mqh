//+------------------------------------------------------------------+
//| DslExecution.mqh — generic bundle adapter for the EA surface     |
//|                                                                  |
//| The EA pulls chart history into chronological arrays and hands   |
//| them to DslBuildSeriesFromArrays (DslSeries.mqh) — the SAME       |
//| canonical series builder the parity runner uses, so the EA path  |
//| and the fixture-parity path compute indicators identically       |
//| (never iMA/iRSI/iATR handles).                                    |
//+------------------------------------------------------------------+
#ifndef MQL5BOT_DSL_EXECUTION_MQH
#define MQL5BOT_DSL_EXECUTION_MQH

#include <Mql5Bot/Config.mqh>
#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslBundle.mqh>
#include <Mql5Bot/DslSeries.mqh>

// EA-side wrapper: pull the chart history into chronological arrays
// and hand them to the SAME canonical builder the parity runner uses.
bool DslBuildSeries(CDslJson &json,const int spec,const string symbol,
                    const ENUM_TIMEFRAMES tf,const int bars,CDslRuntime &rt)
  {
   MqlRates rates[]; ArraySetAsSeries(rates,false);   // rates[0] = oldest
   int got=CopyRates(symbol,tf,0,bars,rates);
   if(got<bars) return false;                 // insufficient history: refuse
   datetime times[];
   double open[],high[],low[],close[];
   ArrayResize(times,got); ArrayResize(open,got); ArrayResize(high,got);
   ArrayResize(low,got);   ArrayResize(close,got);
   for(int i=0;i<got;i++)
     {
      times[i]=rates[i].time; open[i]=rates[i].open; high[i]=rates[i].high;
      low[i]=rates[i].low;    close[i]=rates[i].close;
     }
   string err="";
   return DslBuildSeriesFromArrays(json,spec,times,open,high,low,close,
                                   rt,err);
  }

bool DslSignalFromPosition(const int position,const double entry,
                           const double atr,const SDslExitGeometry &geometry,
                           SBotSignal &signal)
  {
   ZeroMemory(signal);
   if(position==0 || entry<=0.0 || atr<=0.0) return false;
   double slDist=geometry.slAtr>0.0 ? geometry.slAtr*atr :
                 (geometry.slModel=="points" ? geometry.slValue*_Point :
                  (geometry.slModel=="percent" ? entry*geometry.slValue/100.0 : 0.0));
   double tpDist=geometry.tpAtr>0.0 ? geometry.tpAtr*atr :
                 (geometry.tpModel=="points" ? geometry.tpValue*_Point :
                  (geometry.tpModel=="percent" ? entry*geometry.tpValue/100.0 : 0.0));
   if(slDist<=0.0) return false;
   signal.direction=position;
   signal.slPrice=(position>0)?entry-slDist:entry+slDist;
   signal.tpPrice=(tpDist>0.0)?((position>0)?entry+tpDist:entry-tpDist):0.0;
   signal.valid=true;
   return true;
  }

#endif
