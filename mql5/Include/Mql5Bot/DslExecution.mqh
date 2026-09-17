//+------------------------------------------------------------------+
//| DslExecution.mqh — generic bundle adapter for the EA surface     |
//+------------------------------------------------------------------+
#ifndef MQL5BOT_DSL_EXECUTION_MQH
#define MQL5BOT_DSL_EXECUTION_MQH

#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslBundle.mqh>
#include <Mql5Bot/DslRuntime.mqh>

bool DslCopyChrono(const int handle,const int buffer,const int bars,double &dst[])
  {
   ArrayResize(dst,bars);
   double raw[]; ArraySetAsSeries(raw,true);
   if(handle==INVALID_HANDLE || CopyBuffer(handle,buffer,0,bars,raw)<bars)
     {
      double z=0.0; z=z/z;
      for(int i=0;i<bars;i++) dst[i]=z;
      return false;
     }
   double z=0.0; z=z/z;
   for(int i=0;i<bars;i++)
     {
      double v=raw[bars-1-i];
      dst[i]=(v==EMPTY_VALUE)?z:v;
     }
   return true;
  }

void DslCopyPrice(const string symbol,const ENUM_TIMEFRAMES tf,const int col,
                  const int bars,double &dst[])
  {
   ArrayResize(dst,bars);
   MqlRates rates[]; ArraySetAsSeries(rates,false);
   int got=CopyRates(symbol,tf,0,bars,rates);
   for(int i=0;i<bars;i++)
     {
      if(i>=got){dst[i]=0.0;continue;}
      dst[i]=(col==0)?rates[i].open:(col==1)?rates[i].high:
             (col==2)?rates[i].low:rates[i].close;
     }
  }

bool DslBuildSeries(CDslJson &json,const int spec,const string symbol,
                    const ENUM_TIMEFRAMES tf,const int bars,CDslRuntime &rt)
  {
   string names[4]={"open","high","low","close"};
   for(int k=0;k<4;k++)
     {
      double p[]; DslCopyPrice(symbol,tf,k,bars,p);
      if(!rt.RegisterSeries(names[k],p)) return false;
     }
   int inds=json.Member(spec,"indicators");
   for(int c=json.FirstChild(inds);c>=0;c=json.NextSibling(c))
     {
      string id=json.GetStr(c,"id","");
      string kind=json.GetStr(c,"kind","");
      int period=(int)json.GetNum(c,"period",14);
      int handle=INVALID_HANDLE;
      double values[];
      if(kind=="EMA") handle=iMA(symbol,tf,period,0,MODE_EMA,PRICE_CLOSE);
      else if(kind=="SMA") handle=iMA(symbol,tf,period,0,MODE_SMA,PRICE_CLOSE);
      else if(kind=="RSI") handle=iRSI(symbol,tf,period,PRICE_CLOSE);
      else if(kind=="ATR") handle=iATR(symbol,tf,period);
      else if(kind=="BBANDS")
        {
         handle=iBands(symbol,tf,period,0,json.GetNum(c,"dev",2.0),PRICE_CLOSE);
         double mid[],up[],lo[];
         if(!DslCopyChrono(handle,0,bars,mid) ||
            !DslCopyChrono(handle,1,bars,up) || !DslCopyChrono(handle,2,bars,lo)) return false;
         if(!rt.RegisterSeries(id,mid) || !rt.RegisterSeries(id+"__mid",mid) ||
            !rt.RegisterSeries(id+"__upper",up) || !rt.RegisterSeries(id+"__lower",lo)) return false;
         continue;
        }
      else if(kind=="MACD")
        {
         handle=iMACD(symbol,tf,(int)json.GetNum(c,"fast",12),
                      (int)json.GetNum(c,"slow",26),(int)json.GetNum(c,"signal",9),PRICE_CLOSE);
         double line[],signal[];
         if(!DslCopyChrono(handle,0,bars,line) || !DslCopyChrono(handle,1,bars,signal)) return false;
         if(!rt.RegisterSeries(id,line) || !rt.RegisterSeries(id+"__line",line) ||
            !rt.RegisterSeries(id+"__signal",signal)) return false;
         continue;
        }
      else
         return false;
      if(handle==INVALID_HANDLE || !DslCopyChrono(handle,0,bars,values) ||
         !rt.RegisterSeries(id,values)) return false;
     }
   return true;
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
