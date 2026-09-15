//+------------------------------------------------------------------+
//|                                        Mql5Bot/RiskManager.mqh   |
//| Risk engine: sizing on the INJECTED SSymbolSpec (SPEC §3.10),    |
//| daily-loss / drawdown limits, persistent fail-safe state machine |
//| (SPEC §3.5/§8.C):                                                |
//|                                                                  |
//|   ENGINE_NORMAL -> ENGINE_NO_NEW_TRADES (daily limit, guard      |
//|   incidents) -> ENGINE_HALT (drawdown kill switch, manual trip)  |
//|                                                                  |
//| State, day-start equity and the equity peak are adopted from the |
//| StateStore after restart — a restart NEVER resets the daily loss |
//| or forgets the DD peak (SPEC DoD #13/#14).                       |
//|                                                                  |
//| Sizing modes: FixedLot, RiskPercentOfEquity (default),           |
//| RiskPercentOfBalance, FixedMoney, Kelly (capped at 0.25, only    |
//| when explicitly selected). Volume floors to the broker step      |
//| (never rounds up), honours min/max/limit, checks margin via      |
//| OrderCalcMargin and reduces (or rejects) when insufficient.      |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_RISKMANAGER_MQH
#define MQL5BOT_RISKMANAGER_MQH

#include <Mql5Bot/Config.mqh>
#include <Mql5Bot/SymbolSpec.mqh>
#include <Mql5Bot/StateStore.mqh>

enum ENUM_SIZING_MODE
  {
   SIZING_FIXED_LOT        = 0, // fixed lots (risk reported, not enforced)
   SIZING_RISK_PERCENT_EQ  = 1, // risk % of equity (default)
   SIZING_RISK_PERCENT_BAL = 2, // risk % of balance
   SIZING_FIXED_MONEY      = 3, // fixed money per trade (deposit currency)
   SIZING_KELLY            = 4  // capped Kelly (<= 0.25), explicit opt-in
  };

#define KELLY_CAP 0.25

class CRiskManager
  {
private:
   double            m_riskValue;       // % or money depending on mode
   double            m_maxLots;
   double            m_dailyLossPct;
   double            m_maxDrawdownPct;
   double            m_maxSpreadPoints;
   double            m_kellyWinRate;
   double            m_kellyPayoff;
   ENUM_SIZING_MODE  m_mode;

   double            m_dayStartEquity;
   double            m_peakEquity;
   bool              m_limitsInitialized;
   ENUM_ENGINE_STATE m_state;           // persisted fail-safe state
   int               m_stateReason;     // ENUM_STATE_REASON

   double            KellyFraction(const double winRate, const double payoff) const
     {
      if(winRate <= 0.0 || winRate >= 1.0 || payoff <= 0.0)
         return 0.0;
      double k = winRate - (1.0 - winRate) / payoff;
      return (k > 0.0) ? k : 0.0;
     }

public:
                     CRiskManager() :
                        m_riskValue(1.0), m_maxLots(100.0),
                        m_dailyLossPct(0.0), m_maxDrawdownPct(0.0),
                        m_maxSpreadPoints(0.0), m_kellyWinRate(0.0),
                        m_kellyPayoff(0.0), m_mode(SIZING_RISK_PERCENT_EQ),
                        m_dayStartEquity(0.0), m_peakEquity(0.0),
                        m_limitsInitialized(false),
                        m_state(ENGINE_NORMAL), m_stateReason(REASON_NONE) {}

   void              Init(const ENUM_SIZING_MODE mode, const double riskValue,
                          const double maxLots, const double dailyLossPct,
                          const double maxDrawdownPct, const double maxSpreadPoints,
                          const double kellyWinRate, const double kellyPayoff)
     {
      m_mode              = mode;
      m_riskValue         = riskValue;
      m_maxLots           = maxLots;
      m_dailyLossPct      = dailyLossPct;
      m_maxDrawdownPct    = maxDrawdownPct;
      m_maxSpreadPoints   = maxSpreadPoints;
      m_kellyWinRate      = kellyWinRate;
      m_kellyPayoff       = kellyPayoff;
      m_state             = ENGINE_NORMAL;
      m_stateReason       = REASON_NONE;
     }

   // Adopt persisted state after restart (S2). Values come from the
   // StateStore; equity-derived values are refreshed by CheckLimits.
   void              AdoptState(const ENUM_ENGINE_STATE state, const int reason,
                                const double dayStartEquity, const double peakEquity)
     {
      m_state       = state;
      m_stateReason = reason;
      if(dayStartEquity > 0.0)
         m_dayStartEquity = dayStartEquity;
      if(peakEquity > 0.0)
         m_peakEquity = peakEquity;
      m_limitsInitialized = true;
     }

   //--- fail-safe state machine ---------------------------------------
   ENUM_ENGINE_STATE State() const { return m_state; }
   int               StateReason() const { return m_stateReason; }
   bool              IsKillSwitch() const { return m_state != ENGINE_NORMAL; }
   bool              AllowsNewTrades() const { return m_state == ENGINE_NORMAL; }

   void              SetState(const ENUM_ENGINE_STATE state, const int reason)
     {
      m_state       = state;
      m_stateReason = (state == ENGINE_NORMAL) ? REASON_NONE : reason;
      // persist immediately (GlobalVariables; file save is the caller's job)
      HotStateSave(m_state, m_stateReason, CurrentDayKey(),
                   m_dayStartEquity, m_peakEquity);
     }

   void              TripKillSwitch(const int reason)
     { SetState(ENGINE_HALT, reason); }

   void              ResetDayAndPeak()
     {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity <= 0.0)
         equity = AccountInfoDouble(ACCOUNT_BALANCE);
      m_dayStartEquity    = equity;
      m_peakEquity        = equity;
      m_limitsInitialized = true;
      HotStateSave(m_state, m_stateReason, CurrentDayKey(),
                   m_dayStartEquity, m_peakEquity);
     }

   // call once per day rollover (server time)
   void              OnNewDay()
     {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity <= 0.0)
         equity = AccountInfoDouble(ACCOUNT_BALANCE);
      m_dayStartEquity = equity;
      if(equity > m_peakEquity)
         m_peakEquity = equity;
      // daily-loss pause expires at the reset boundary (never the kill
      // switch — that one needs an explicit reset)
      if(m_state == ENGINE_NO_NEW_TRADES && m_stateReason == REASON_DAILY_LOSS)
         SetState(ENGINE_NORMAL, REASON_NONE);
      HotStateSave(m_state, m_stateReason, CurrentDayKey(),
                   m_dayStartEquity, m_peakEquity);
     }

   static int        CurrentDayKey()
     {
      MqlDateTime st;
      TimeToStruct(TimeCurrent(), st);
      return st.year * 10000 + st.mon * 100 + st.day;
     }

   double            DayStartEquity() const { return m_dayStartEquity; }
   double            PeakEquity() const { return m_peakEquity; }

   // Check equity-based limits; returns true when trading must stop.
   // Daily-loss breach -> caller pauses (NO_NEW_TRADES); drawdown breach
   // sets ENGINE_HALT right here (persisted).
   bool              CheckLimits(bool &dailyHit, bool &drawdownHit)
     {
      dailyHit    = false;
      drawdownHit = false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity <= 0.0)
         equity = AccountInfoDouble(ACCOUNT_BALANCE);
      if(m_dailyLossPct > 0.0 && m_limitsInitialized &&
         equity <= m_dayStartEquity * (1.0 - m_dailyLossPct / 100.0))
         dailyHit = true;
      if(m_maxDrawdownPct > 0.0 && m_limitsInitialized &&
         equity <= m_peakEquity * (1.0 - m_maxDrawdownPct / 100.0))
        {
         drawdownHit = true;
         SetState(ENGINE_HALT, REASON_MAX_DRAWDOWN);
        }
      if(equity > m_peakEquity)
        {
         m_peakEquity = equity;
         HotStateSave(m_state, m_stateReason, CurrentDayKey(),
                      m_dayStartEquity, m_peakEquity);
        }
      return dailyHit || drawdownHit;
     }

   //--------------------------------------------------------------------
   // Position sizing on the injected symbol spec.
   //   price   = expected fill price
   //   slPrice = proposed stop price (absolute)
   // Returns 0.0 when the order must NOT be sent (reason in outReason).
   //--------------------------------------------------------------------
   double            GetLots(const SSymbolSpec &spec, const double price,
                             const double slPrice, string &outReason)
     {
      outReason = "";
      if(m_riskValue <= 0.0 && m_mode != SIZING_FIXED_LOT)
        {
         outReason = "risk value <= 0";
         return 0.0;
        }
      if(slPrice <= 0.0)
        {
         outReason = "missing stop";          // SPEC §3.2
         return 0.0;
        }
      double stopDist = MathAbs(price - slPrice);
      double conv = ProfitToDeposit(spec);
      if(conv <= 0.0)
        {
         outReason = "profit->deposit conversion unavailable";
         return 0.0;
        }
      // enforce broker stops level & tick grid so the risk math matches
      // the stop that will actually be sent
      double distance = SpecEnforceMinStop(stopDist, spec);
      double lossPl = SpecLossPerLot(distance, spec, conv);
      if(lossPl <= 0.0)
        {
         outReason = "loss per lot <= 0";
         return 0.0;
        }

      //---- budget ------------------------------------------------------
      double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      double budget  = 0.0;
      double rawLots = 0.0;
      if(m_mode == SIZING_FIXED_LOT)
        {
         rawLots = m_riskValue;
         budget  = rawLots * lossPl;
        }
      else if(m_mode == SIZING_RISK_PERCENT_EQ)
        {
         budget = equity * m_riskValue / 100.0;
         rawLots = budget / lossPl;
        }
      else if(m_mode == SIZING_RISK_PERCENT_BAL)
        {
         budget = balance * m_riskValue / 100.0;
         rawLots = budget / lossPl;
        }
      else if(m_mode == SIZING_FIXED_MONEY)
        {
         budget = m_riskValue;
         rawLots = budget / lossPl;
        }
      else if(m_mode == SIZING_KELLY)
        {
         double k = KellyFraction(m_kellyWinRate, m_kellyPayoff);
         if(k <= 0.0)
           {
            outReason = "kelly <= 0 (no edge)";
            return 0.0;
           }
         budget = equity * MathMin(k, KELLY_CAP);
         rawLots = budget / lossPl;
        }
      if(budget <= 0.0 || rawLots <= 0.0)
        {
         outReason = "budget <= 0";
         return 0.0;
        }

      //---- normalisation (never round UP) ------------------------------
      if(rawLots < spec.volumeMin)
        {
         // forcing the broker minimum would overshoot the risk budget
         outReason = "below broker minimum volume";
         return 0.0;
        }
      double effectiveCap = m_maxLots;
      if(spec.volumeMax < effectiveCap)
         effectiveCap = spec.volumeMax;
      if(spec.volumeLimit > 0.0 && spec.volumeLimit < effectiveCap)
         effectiveCap = spec.volumeLimit;
      if(effectiveCap < spec.volumeMin)
        {
         outReason = "effective cap below broker minimum";
         return 0.0;
        }
      double lots = SpecNormalizeVolume(MathMin(rawLots, effectiveCap), spec);
      if(lots <= 0.0)
        {
         outReason = "volume normalisation failed";
         return 0.0;
        }

      //---- margin check (query, never assume — SPEC §3.3) ---------------
      long dir = (price < slPrice) ? POSITION_TYPE_LONG : POSITION_TYPE_SHORT;
      double margin = 0.0;
      if(!OrderCalcMargin((dir == POSITION_TYPE_LONG) ? ORDER_TYPE_BUY
                                                      : ORDER_TYPE_SELL,
                          spec.name, lots, price, margin) || margin <= 0.0)
        {
         outReason = "OrderCalcMargin failed";
         return 0.0;
        }
      double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(margin > freeMargin)
        {
         // linear scaling keeps the margin check exact after ONE step
         double scaled = lots * freeMargin / margin;
         if(scaled < spec.volumeMin)
           {
            outReason = "margin rejects even minimum volume";
            return 0.0;
           }
         lots = SpecNormalizeVolume(MathMin(scaled, effectiveCap), spec);
         if(lots <= 0.0 || !OrderCalcMargin((dir == POSITION_TYPE_LONG)
                                              ? ORDER_TYPE_BUY
                                              : ORDER_TYPE_SELL,
                                            spec.name, lots, price, margin))
           {
            outReason = "margin check failed after scaling";
            return 0.0;
           }
            if(margin > freeMargin)
              {
               // safety net (non-linear margin curves): walk down, bounded
               int guard = 0;
               while(margin > freeMargin && lots >= spec.volumeMin &&
                     guard < 500)
                 {
                  lots = SpecNormalizeVolume(lots - spec.volumeStep, spec);
                  if(lots < spec.volumeMin)
                     break;
                  // Margin is UNKNOWN if this call fails: veto the size
                  // immediately — never keep stepping with a stale value
                  // and never let a broker-calculation failure pass as a
                  // successful margin calculation (Risk contract, SPEC
                  // §3.3; warning-83 fix 2026-09-08).
                  if(!OrderCalcMargin((dir == POSITION_TYPE_LONG) ? ORDER_TYPE_BUY
                                                                  : ORDER_TYPE_SELL,
                                      spec.name, lots, price, margin))
                    {
                     outReason = "OrderCalcMargin failed during step-down";
                     return 0.0;
                    }
                  guard++;
                 }
            if(margin > freeMargin || lots < spec.volumeMin)
              {
               outReason = "margin rejection";
               return 0.0;
              }
           }
        }
      return lots;
     }

   // Risk-money actually exposed at `lots` for reporting.
   double            RiskMoneyAt(const SSymbolSpec &spec, const double lots,
                                 const double price, const double slPrice) const
     {
      if(lots <= 0.0 || slPrice <= 0.0)
         return 0.0;
      double conv = ProfitToDeposit(spec);
      if(conv <= 0.0)
         return 0.0;
      double distance = SpecEnforceMinStop(MathAbs(price - slPrice), spec);
      return lots * SpecLossPerLot(distance, spec, conv);
     }

   // Profit-currency -> deposit-currency conversion, queried at runtime.
   // Conservative: uses the ask (worse) rate. Returns 0 when unavailable
   // (callers must fail safe, never assume 1.0).
   static double     ProfitToDeposit(const SSymbolSpec &spec)
     {
      if(spec.currencyProfit == spec.currencyDeposit)
         return 1.0;
      string direct = spec.currencyProfit + spec.currencyDeposit;
      if(SymbolInfoDouble(direct, SYMBOL_BID) > 0.0)
         return SymbolInfoDouble(direct, SYMBOL_ASK);   // deposit per profit
      string inverse = spec.currencyDeposit + spec.currencyProfit;
      if(SymbolInfoDouble(inverse, SYMBOL_BID) > 0.0)
        {
         double ask = SymbolInfoDouble(inverse, SYMBOL_ASK);
         return (ask > 0.0) ? 1.0 / ask : 0.0;
        }
      return 0.0;
     }

   // spread guard: block entries when the spread is too wide
   bool              IsSpreadOK(const string symbol) const
     {
      if(m_maxSpreadPoints <= 0.0)
         return true;
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      if(point <= 0.0)
         return false;
      double spread = (SymbolInfoDouble(symbol, SYMBOL_ASK) -
                       SymbolInfoDouble(symbol, SYMBOL_BID)) / point;
      return spread <= m_maxSpreadPoints;
     }

   double            DailyLossPct()  const { return m_dailyLossPct; }
   double            MaxDrawdownPct() const { return m_maxDrawdownPct; }
   double            RiskValue()     const { return m_riskValue; }
  };

#endif // MQL5BOT_RISKMANAGER_MQH
//+------------------------------------------------------------------+
