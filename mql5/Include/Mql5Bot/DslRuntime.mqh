//+------------------------------------------------------------------+
//|  DslRuntime.mqh — generic DSL signal evaluation                   |
//|                                                                  |
//|  STATUS: compile-observed on Windows; MQL5<->Python PARITY is     |
//|  OWNER-PENDING until tools/run_dsl_parity.ps1 reports 14/14 EXACT.|
//|                                                                  |
//|  Mirror of python/mql5bot/dsl/runtime.py. Interprets the bundle   |
//|  spec as DATA into a desired position in {-1,0,+1} per CLOSED bar:|
//|   * everything is computed from CLOSED bars; the EA acts one bar   |
//|     later, so lookahead is impossible (closed-bar contract).       |
//|   * NaN comparisons are FALSE; a NaN bar emits 0 while carrying    |
//|     state; before the first valid bar state is 0.                 |
//|   * mode "instant": +1 where long fires, -1 where short fires.     |
//|   * mode "state": entries flip a persisted state until the        |
//|     opposite entry / an explicit exit.                            |
//|   * filters only FLATTEN bars — they never create a position.     |
//|     IMPLEMENTED (exactly what the committed parity fixtures       |
//|     exercise): market trading_days, session (market-level first,  |
//|     else filter-level, UTC only), then cooldown over the ORIGINAL |
//|     pre-cooldown vector.                                          |
//|     REFUSED fail-closed (no committed fixture verifies them):     |
//|     max_spread_points, max_atr_pct, regime.forbidden — a spec     |
//|     using any of them does not run here until it ships WITH a     |
//|     verified parity fixture.                                      |
//|   * any unrecognized condition/operand or unresolved reference    |
//|     FAILS the evaluation — unsupported features are refused,      |
//|     never approximated.                                           |
//|  Exit geometry (SL/TP/trail/breakeven) is RETURNED for the owner  |
//|  to map onto SBotSignal via the existing FillPriceLevels; Risk    |
//|  remains the final veto (authority model unchanged).              |
//+------------------------------------------------------------------+
#ifndef DSL_RUNTIME_MQH
#define DSL_RUNTIME_MQH

#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslIndicators.mqh>

#define DSL_MAX_SERIES   64      // distinct indicator outputs per strategy

// ---- a named, precomputed series (values are CHRONOLOGICAL: [0]=oldest
//      .. [n-1]=newest closed bar; NaN where undefined during warmup) ----
struct SDslSeries
  {
   string            name;      // "ema_f" or "dc__upper"
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
   datetime          m_times[];  // bar timestamps (chronological)
   bool              m_haveTimes;
   string            m_error;
   bool              m_evalFailed;   // set on any refused construct

   static double     NaNValue() { double z=0.0; return z/z; }
   static bool       IsNaN(double v) { return v != v; }

   void              EvalFail(const string msg)
     {
      if(!m_evalFailed) m_error = msg;
      m_evalFailed = true;
     }

   int               FindSeries(const string name) const
     {
      for(int i=0;i<m_nSeries;i++) if(m_series[i].name==name) return i;
      return -1;
     }

   double            SeriesAt(const int s, const int bar) const
     {
      if(s<0 || bar<0 || bar>=m_bars) return NaNValue();
      return m_series[s].v[bar];
     }

   // crossover sign at bar over GENERIC operands (same operand grammar
   // as comparisons). Mirrors indicators.crossover(): the event is a
   // transition of the STRICT-above state, both samples must be valid:
   //   +1  entering above  (prev NOT above, now above)
   //   -1  leaving above   (prev above, now not above)
   int               CrossSign(const int aOp, const int bOp, const int bar)
     {
      if(bar < 1) return 0;              // first bar never fires
      double a0 = EvalOperand(aOp, bar),   a1 = EvalOperand(aOp, bar-1);
      double b0 = EvalOperand(bOp, bar),   b1 = EvalOperand(bOp, bar-1);
      if(IsNaN(a0)||IsNaN(b0)||IsNaN(a1)||IsNaN(b1)) return 0;
      bool above  = (a0 > b0);
      bool pAbove = (a1 > b1);
      if(above && !pAbove) return  1;
      if(!above && pAbove) return -1;
      return 0;
     }

   // ---- operand evaluation: {ind|price|const|add|sub|mul|div} ----
   double            EvalOperand(const int op, const int bar)
     {
      if(op<0) { EvalFail("missing operand"); return NaNValue(); }
      int m;
      if((m=m_json.Member(op,"ind"))>=0)
        {
         int s = FindSeries(m_json.Str(m));
         if(s<0)
           { EvalFail("indicator '"+m_json.Str(m)+"' not computed");
             return NaNValue(); }
         return SeriesAt(s, bar);
        }
      if((m=m_json.Member(op,"price"))>=0)
        {
         int s = FindSeries(m_json.Str(m));  // open/high/low/close
         if(s<0)
           { EvalFail("price column '"+m_json.Str(m)+"' not registered");
             return NaNValue(); }
         return SeriesAt(s, bar);
        }
      if((m=m_json.Member(op,"const"))>=0)
         return m_json.Num(m);
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
            return (y==0.0)?NaNValue():x/y;   // div0 -> NaN (cmp False)
           }
        }
      EvalFail("unrecognized operand node — refusing to approximate");
      return NaNValue();
     }

   // ---- condition evaluation: 1 (true) / 0 (false, NaN-safe) ------
   int               EvalCondition(const int cond, const int bar)
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
         if(c=="NE") return (l!=r);
         EvalFail("unrecognized cmp '"+c+"'");
         return 0;
        }
      if((m=m_json.Member(cond,"cross"))>=0)
        {
         // GENERIC operands, exactly like the Python runtime
         int s = CrossSign(m_json.Member(cond,"a"),
                           m_json.Member(cond,"b"), bar);
         string dir = m_json.Str(m);
         if(dir=="ABOVE") return (s>0);
         if(dir=="BELOW") return (s<0);
         EvalFail("unrecognized cross direction '"+dir+"'");
         return 0;
        }
      bool rising = (m_json.Member(cond,"rising")>=0);
      bool falling = (m_json.Member(cond,"falling")>=0);
      if(rising || falling)
        {
         // mirror runtime.eval_condition: the CURRENT value must be
         // strictly greater (rising) / smaller (falling) than EACH of
         // the previous n-1 values — not a monotonic chain
         int key = rising ? m_json.Member(cond,"rising")
                          : m_json.Member(cond,"falling");
         int win = (int)m_json.GetNum(cond,"n",2);
         double cur = EvalOperand(key,bar);
         if(IsNaN(cur)) return 0;
         for(int k=1;k<win;k++)
           {
            if(bar-k < 0) return 0;
            double prev = EvalOperand(key,bar-k);
            if(IsNaN(prev)) return 0;
            if(rising  && !(cur>prev)) return 0;
            if(falling && !(cur<prev)) return 0;
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
      EvalFail("unrecognized condition node — refusing to approximate");
      return 0;
     }

public:
                     CDslRuntime() : m_json(NULL), m_spec(-1),
                                     m_nSeries(0), m_bars(0),
                                     m_haveTimes(false),
                                     m_evalFailed(false) {}

   string            Error() const { return m_error; }

   // Register a named CHRONOLOGICAL series (price columns open/high/
   // low/close and every indicator output the bundle declares).
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

   // bar timestamps (chronological) — REQUIRED for session /
   // trading-day filters; refused when missing and needed
   bool              RegisterTimes(const datetime &times[])
     {
      int n=ArraySize(times);
      if(m_bars==0) m_bars=n;
      if(n!=m_bars){ m_error="times length mismatch"; return false; }
      ArrayResize(m_times,n);
      for(int i=0;i<n;i++) m_times[i]=times[i];
      m_haveTimes=true;
      return true;
     }

   void              Bind(CDslJson *json, int specObj)
     { m_json=json; m_spec=specObj; }

   // desired positions over all bars -> out[] in {-1,0,+1}. Mirrors
   // runtime.desired_positions() (entry modes + filters + cooldown).
   // false + Error() on ANY refused construct (fail closed).
   bool              DesiredPositions(int &out[])
     {
      if(m_json==NULL || m_spec<0){ m_error="not bound"; return false; }
      m_evalFailed=false;
      int entry = m_json.Member(m_spec,"entry");
      string mode = m_json.GetStr(entry,"mode","");
      if(mode!="state" && mode!="instant")
        { m_error="spec has no executable entry mode"; return false; }
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
      if(m_evalFailed) return false;         // refused construct
      if(!ApplyFilters(out)) return false;   // refused filter
      Cooldown(out);
      return !m_evalFailed;
     }

   // ---- filters: only ever FLATTEN bars (mirror _apply_filters) ----
   // Implemented: trading_days + session + cooldown (fixture-verified).
   // max_spread_points / max_atr_pct / regime.forbidden are REFUSED —
   // no committed fixture verifies them yet (fail closed, never
   // approximated).
   bool              ApplyFilters(int &out[])
     {
      int market  = m_json.Member(m_spec,"market");
      int filters = m_json.Member(m_spec,"filters");

      // 1. market-level trading_days (python dayofweek: Monday=0)
      int td = m_json.Member(market,"trading_days");
      if(td>=0 && m_json.Type(td)==DSL_JSON_ARRAY)
        {
         if(!m_haveTimes)
           { m_error="market.trading_days set but no bar times "
                     "registered — refusing to guess"; return false; }
         for(int i=0;i<m_bars;i++)
           {
            MqlDateTime dt;
            TimeToStruct(m_times[i], dt);
            int pyDow = (dt.day_of_week + 6) % 7;   // Sun=0 -> Mon=0
            bool allowed=false;
            int c=m_json.FirstChild(td);
            while(c>=0)
              {
               if((int)m_json.Num(c)==pyDow){ allowed=true; break; }
               c=m_json.NextSibling(c);
              }
            if(!allowed) out[i]=0;
           }
        }

      // 2. session: market-level first, else filter-level (python
      //    applies exactly ONE — the first non-null). Bar timestamps
      //    are the fixture's UTC index; a non-UTC tz is refused.
      int sess = m_json.Member(market,"session");
      if(m_json.Type(sess)!=DSL_JSON_OBJECT)
         sess = m_json.Member(filters,"session");
      if(m_json.Type(sess)==DSL_JSON_OBJECT)
        {
         if(!m_haveTimes)
           { m_error="session filter set but no bar times registered — "
                     "refusing to guess"; return false; }
         string tz = m_json.GetStr(sess,"tz","UTC");
         if(tz!="UTC")
           { m_error="session tz '"+tz+"' unsupported (UTC only) — "
                     "refusing to guess"; return false; }
         int startMin, endMin;
         if(!SessionMinutes(m_json.GetStr(sess,"start",""), startMin) ||
            !SessionMinutes(m_json.GetStr(sess,"end",""),   endMin))
           { m_error="malformed session HH:MM"; return false; }
         for(int i=0;i<m_bars;i++)
           {
            MqlDateTime dt;
            TimeToStruct(m_times[i], dt);
            int minutes = dt.hour*60 + dt.min;
            bool inside;
            if(startMin<=endMin)
               inside = (minutes>=startMin && minutes<endMin);
            else                                  // overnight session
               inside = (minutes>=startMin || minutes<endMin);
            if(!inside) out[i]=0;
           }
        }

      // 3-5. unverified filters: REFUSED until a committed parity
      //      fixture proves them (never a silent pass, never guessed)
      int msp = m_json.Member(filters,"max_spread_points");
      if(msp>=0 && m_json.Type(msp)==DSL_JSON_NUMBER)
        { m_error="filters.max_spread_points has no verified MQL5 "
                  "parity fixture — refusing to guess"; return false; }
      int map_ = m_json.Member(filters,"max_atr_pct");
      if(map_>=0 && m_json.Type(map_)==DSL_JSON_NUMBER)
        { m_error="filters.max_atr_pct has no verified MQL5 parity "
                  "fixture — refusing to guess"; return false; }
      int reg  = m_json.Member(filters,"regime");
      int forb = m_json.Member(reg,"forbidden");
      if(forb>=0 && m_json.Type(forb)==DSL_JSON_ARRAY &&
         m_json.FirstChild(forb)>=0)
        { m_error="filters.regime.forbidden has no verified MQL5 parity"
                  " fixture — refusing to guess"; return false; }
      return true;
     }

   // ---- cooldown: after an entry, suppress NEW entries for k bars.
   //      Mirrors runtime._cooldown EXACTLY: both the suppression test
   //      and the entry detection read the ORIGINAL (pre-cooldown)
   //      vector, never the partially-suppressed one.
   void              Cooldown(int &out[])
     {
      int filters = m_json.Member(m_spec,"filters");
      int cooldown = (int)m_json.GetNum(filters,"cooldown_bars",0);
      if(cooldown<=0) return;
      int orig[];
      ArrayResize(orig,m_bars);
      for(int i=0;i<m_bars;i++) orig[i]=out[i];
      int holdUntil=-1;
      for(int i=0;i<m_bars;i++)
        {
         if(orig[i]!=0 && i<=holdUntil && i>0 && orig[i-1]==0)
            out[i]=0;
         if(orig[i]!=0 && (i==0 || orig[i-1]==0))
            holdUntil=i+cooldown;
        }
     }

   static bool       SessionMinutes(const string hhmm, int &minutes)
     {
      string parts[];
      if(StringSplit(hhmm, ':', parts)!=2) return false;
      minutes = (int)StringToInteger(parts[0])*60
              + (int)StringToInteger(parts[1]);
      return true;
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
