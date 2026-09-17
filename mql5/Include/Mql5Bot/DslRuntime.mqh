//+------------------------------------------------------------------+
//|  DslRuntime.mqh — generic DSL signal evaluation (OWNER-PENDING)   |
//|                                                                  |
//|  STATUS: SOURCE-ONLY, NOT COMPILED. Written on Mac; owner compiles|
//|  and verifies against artifacts/dsl_parity/ (README.md).          |
//|                                                                  |
//|  Mirror of python/mql5bot/dsl/runtime.py. Interprets the bundle   |
//|  spec as DATA into a desired position in {-1,0,+1} per CLOSED bar:|
//|   * everything is computed from CLOSED bars (shift >= 1 style);    |
//|     the EA acts one bar later, so lookahead is impossible.        |
//|   * NaN comparisons are FALSE; a NaN bar emits 0 while carrying    |
//|     state; before the first valid bar state is 0.                 |
//|   * mode "instant": +1 where long fires, -1 where short fires.     |
//|   * mode "state": entries flip a persisted state until the        |
//|     opposite entry / an explicit exit / a NaN re-arm.             |
//|   * filters only FLATTEN bars — they never create a position.     |
//|  Exit geometry (SL/TP/trail/breakeven) is RETURNED for the owner  |
//|  to map onto SBotSignal via the existing FillPriceLevels; Risk    |
//|  remains the final veto (authority model unchanged).              |
//+------------------------------------------------------------------+
#ifndef DSL_RUNTIME_MQH
#define DSL_RUNTIME_MQH

#include "DslJson.mqh"

#define DSL_MAX_SERIES   64      // distinct indicator outputs per strategy

// ---- a named, precomputed series (values are SERIES-indexed: [0]=oldest
//      .. [n-1]=newest closed bar; NaN where undefined during warmup) ----
struct SDslSeries
  {
   string            name;      // "ema_f" or "bb__upper"
   double            v[];       // length == bar count
  };

// ---- exit geometry returned to the owner's SBotSignal mapping ----
struct SDslExitGeometry
  {
   double            slAtr;     // ATR multiple, or <0 when not an ATR model
   double            tpAtr;
   double            trailAtr;
   double            breakevenAtr;
   int               timeBars;  // <=0 when unset
   string            slModel;   // "atr" | "points" | "percent"
   double            slValue;   // raw value in the model's units
   string            tpModel;
   double            tpValue;
  };

class CDslRuntime
  {
private:
   CDslJson         *m_json;     // not owned
   int               m_spec;     // spec object node
   SDslSeries        m_series[]; // precomputed indicator outputs
   int               m_nSeries;
   int               m_bars;
   string            m_error;

   static double     NaNValue() { double z=0.0; return z/z; }
   static bool       IsNaN(double v) { return v != v; }

   int               FindSeries(const string name) const
     {
      for(int i=0;i<m_nSeries;i++) if(m_series[i].name==name) return i;
      return -1;
     }

   double            SeriesAt(const string name, int bar) const
     {
      int s = FindSeries(name);
      if(s<0 || bar<0 || bar>=m_bars) return NaNValue();
      return m_series[s].v[bar];
     }

   // crossover sign at bar: +1 if a crossed ABOVE b between bar-1..bar,
   // -1 if crossed BELOW, 0 otherwise. Mirrors indicators.crossover().
   int               CrossSign(const string aName, const string bName,
                               int bar) const
     {
      if(bar<1) return 0;
      double a0=SeriesAt(aName,bar), a1=SeriesAt(aName,bar-1);
      double b0=SeriesAt(bName,bar), b1=SeriesAt(bName,bar-1);
      if(IsNaN(a0)||IsNaN(a1)||IsNaN(b0)||IsNaN(b1)) return 0;
      double d0=a0-b0, d1=a1-b1;
      if(d1<=0.0 && d0>0.0) return 1;
      if(d1>=0.0 && d0<0.0) return -1;
      return 0;
     }

   // ---- operand evaluation: {ind|price|const|add|sub|mul|div} ----
   double            EvalOperand(int op, int bar) const
     {
      if(op<0) return NaNValue();
      if(m_json.Member(op,"ind")>=0)
         return SeriesAt(m_json.Str(m_json.Member(op,"ind")), bar);
      if(m_json.Member(op,"price")>=0)
         return SeriesAt(m_json.Str(m_json.Member(op,"price")), bar); // open/high/low/close precomputed
      if(m_json.Member(op,"const")>=0)
         return m_json.Num(m_json.Member(op,"const"));
      // arithmetic: exactly one of add/sub/mul/div with a 2-array
      string ops[4] = {"add","sub","mul","div"};
      for(int k=0;k<4;k++)
        {
         int arr = m_json.Member(op, ops[k]);
         if(arr>=0)
           {
            int a = m_json.FirstChild(arr);
            int b = m_json.NextSibling(a);
            double x = EvalOperand(a,bar), y = EvalOperand(b,bar);
            if(k==0) return x+y;
            if(k==1) return x-y;
            if(k==2) return x*y;
            return (y==0.0)?NaNValue():x/y;
           }
        }
      return NaNValue();
     }

   // ---- condition evaluation: returns 1 (true) / 0 (false, NaN-safe) --
   int               EvalCondition(int cond, int bar) const
     {
      if(cond<0) return 0;
      int m;
      if((m=m_json.Member(cond,"and"))>=0)
        {
         int c=m_json.FirstChild(m);
         while(c>=0){ if(!EvalCondition(c,bar)) return 0; c=m_json.NextSibling(c); }
         return 1;
        }
      if((m=m_json.Member(cond,"or"))>=0)
        {
         int c=m_json.FirstChild(m);
         while(c>=0){ if(EvalCondition(c,bar)) return 1; c=m_json.NextSibling(c); }
         return 0;
        }
      if((m=m_json.Member(cond,"not"))>=0)
         return EvalCondition(m,bar) ? 0 : 1;
      if((m=m_json.Member(cond,"cmp"))>=0)
        {
         double l=EvalOperand(m_json.Member(cond,"left"),bar);
         double r=EvalOperand(m_json.Member(cond,"right"),bar);
         if(IsNaN(l)||IsNaN(r)) return 0;
         string c=m_json.Str(m);
         if(c=="GT") return (l>r);
         if(c=="GE") return (l>=r);
         if(c=="LT") return (l<r);
         if(c=="LE") return (l<=r);
         if(c=="EQ") return (l==r);
         return (l!=r);
        }
      if((m=m_json.Member(cond,"cross"))>=0)
        {
         string a=m_json.Str(m_json.Member(m_json.Member(cond,"a"),"ind"));
         string b=m_json.Str(m_json.Member(m_json.Member(cond,"b"),"ind"));
         int s=CrossSign(a,b,bar);
         return (m_json.Str(m)=="ABOVE") ? (s>0) : (s<0);
        }
      bool rising = (m_json.Member(cond,"rising")>=0);
      bool falling = (m_json.Member(cond,"falling")>=0);
      if(rising || falling)
        {
         int key = rising?m_json.Member(cond,"rising"):m_json.Member(cond,"falling");
         int win = (int)m_json.GetNum(cond,"n",2);
         double cur = EvalOperand(key,bar);
         if(IsNaN(cur)) return 0;
         for(int k=1;k<win;k++)
           {
            double prev = EvalOperand(key,bar-k);
            if(bar-k<0 || IsNaN(prev)) return 0;
            if(rising  && !(cur>prev)) return 0;
            if(falling && !(cur<prev)) return 0;
            cur = prev;
           }
         return 1;
        }
      if((m=m_json.Member(cond,"within"))>=0)
        {
         double x=EvalOperand(m,bar);
         if(IsNaN(x)) return 0;
         double lo=m_json.GetNum(cond,"low",0), hi=m_json.GetNum(cond,"high",0);
         return (x>=lo && x<=hi);
        }
      return 0;   // unrecognized node -> false (fail closed)
     }

public:
                     CDslRuntime() : m_json(NULL), m_spec(-1),
                                     m_nSeries(0), m_bars(0) {}

   string            Error() const { return m_error; }

   // The owner precomputes each declared indicator output into a named
   // series (via iMA/iRSI/iATR/iBands/iMACD + manual SMA/HIGHEST/LOWEST/
   // DONCHIAN) and registers it here; price columns open/high/low/close
   // are registered the same way. This keeps EvalOperand platform-free.
   bool              RegisterSeries(const string name, const double &vals[])
     {
      if(m_nSeries>=DSL_MAX_SERIES){ m_error="too many series"; return false; }
      int n=ArraySize(vals);
      if(m_bars==0) m_bars=n;
      if(n!=m_bars){ m_error="series length mismatch"; return false; }
      ArrayResize(m_series,m_nSeries+1);
      m_series[m_nSeries].name=name;
      ArrayResize(m_series[m_nSeries].v,n);
      for(int i=0;i<n;i++) m_series[m_nSeries].v[i]=vals[i];
      m_nSeries++;
      return true;
     }

   void              Bind(CDslJson *json, int specObj)
     { m_json=json; m_spec=specObj; }

   // desired positions over all bars -> out[] in {-1,0,+1}. Mirrors
   // runtime.desired_positions() (entry modes + filters + cooldown).
   bool              DesiredPositions(int &out[])
     {
      if(m_json==NULL || m_spec<0){ m_error="not bound"; return false; }
      int entry = m_json.Member(m_spec,"entry");
      string mode = m_json.GetStr(entry,"mode","state");
      int longC   = m_json.Member(entry,"long");
      int shortC  = m_json.Member(entry,"short");
      int exLong  = m_json.Member(entry,"exit_long");
      int exShort = m_json.Member(entry,"exit_short");
      ArrayResize(out,m_bars);
      if(mode=="instant")
        {
         for(int i=0;i<m_bars;i++)
           {
            int d=0;
            if(longC>=0 && EvalCondition(longC,i)) d=1;
            else if(shortC>=0 && EvalCondition(shortC,i)) d=-1;
            out[i]=d;
           }
        }
      else // state
        {
         int state=0;
         for(int i=0;i<m_bars;i++)
           {
            if(longC>=0 && EvalCondition(longC,i)) state=1;
            else if(shortC>=0 && EvalCondition(shortC,i)) state=-1;
            else
              {
               if(state==1 && exLong>=0 && EvalCondition(exLong,i)) state=0;
               else if(state==-1 && exShort>=0 && EvalCondition(exShort,i)) state=0;
              }
            out[i]=state;
           }
        }
      ApplyFiltersAndCooldown(out);
      return true;
     }

   // Filters only FLATTEN (session/trading-days/cooldown shown; spread/
   // regime/volatility need their input series, mirrored from runtime.py
   // — owner wires them where those series are available).
   void              ApplyFiltersAndCooldown(int &out[])
     {
      int filters = m_json.Member(m_spec,"filters");
      int cooldown = (int)m_json.GetNum(filters,"cooldown_bars",0);
      if(cooldown>0)
        {
         int holdUntil=-1;
         for(int i=0;i<m_bars;i++)
           {
            bool isEntry = (out[i]!=0 && (i==0 || out[i-1]==0));
            if(out[i]!=0 && i<=holdUntil && i>0 && out[i-1]==0) out[i]=0;
            if(isEntry) holdUntil=i+cooldown;
           }
        }
      // NOTE: session / trading-day / spread / regime flattening must use
      // the bar timestamps + the owner's spread/regime feeds; implement
      // here mirroring runtime._apply_filters (never create a position).
     }

   // ---- exit geometry (mirrors runtime.exit_params) ----
   SDslExitGeometry  ExitGeometry()
     {
      SDslExitGeometry g;
      g.slAtr=-1; g.tpAtr=-1; g.trailAtr=0; g.breakevenAtr=0; g.timeBars=0;
      g.slModel=""; g.slValue=0; g.tpModel=""; g.tpValue=0;
      int ex = m_json.Member(m_spec,"exit");
      if(ex<0) return g;
      g.trailAtr     = m_json.GetNum(ex,"trail_atr",0);
      g.breakevenAtr = m_json.GetNum(ex,"breakeven_atr",0);
      g.timeBars     = (int)m_json.GetNum(ex,"time_bars",0);
      int sl=m_json.Member(ex,"sl");
      if(sl>=0)
        {
         g.slModel=m_json.GetStr(sl,"model","atr");
         if(g.slModel=="atr")  { g.slAtr=m_json.GetNum(sl,"mult",0); g.slValue=g.slAtr; }
         else if(g.slModel=="points") g.slValue=m_json.GetNum(sl,"points",0);
         else g.slValue=m_json.GetNum(sl,"pct",0);
        }
      int tp=m_json.Member(ex,"tp");
      if(tp>=0)
        {
         g.tpModel=m_json.GetStr(tp,"model","atr");
         if(g.tpModel=="atr")  { g.tpAtr=m_json.GetNum(tp,"mult",0); g.tpValue=g.tpAtr; }
         else if(g.tpModel=="points") g.tpValue=m_json.GetNum(tp,"points",0);
         else g.tpValue=m_json.GetNum(tp,"pct",0);
        }
      return g;
     }
  };

#endif // DSL_RUNTIME_MQH
