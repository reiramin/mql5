//+------------------------------------------------------------------+
//|                                      Mql5Bot/SignalEngine.mqh    |
//|    Five strategy engines, evaluated once per closed bar. The     |
//|    engine only ever looks at completed (shift >= 1) bars.        |
//|                                                                  |
//|    Strategies (mirror of python/mql5bot/strategies.py):          |
//|      EMA_CROSSOVER      trend: fast vs slow EMA position         |
//|      RSI_REVERSAL       mean reversion on RSI extreme escapes    |
//|      DONCHIAN_BREAKOUT  close beyond previous N-bar channel      |
//|      BOLLINGER_REVERSAL fade closes outside the bands            |
//|      MACD_MOMENTUM      MACD line vs signal line position        |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_SIGNALENGINE_MQH
#define MQL5BOT_SIGNALENGINE_MQH

#include <Mql5Bot/Config.mqh>

// status of the previous signal — used for crossover detection
struct SPrevSignalState
  {
   int   emaDir;        // +1/-1/0
   bool  rsiInOversold; // RSI was below the oversold line
   bool  rsiInOverbought;
   double fastEmaPrev;
   double slowEmaPrev;
   double macdLinePrev;
   double macdSignalPrev;
  };

class CSignalEngine
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;
   SBotParams        m_params;
   SPrevSignalState  m_state;
   bool              m_initialized;

   int               m_hFast, m_hSlow, m_hRsi, m_hBoll, m_hMacd, m_hAtr;

   // IEEE-754 NaN sentinel (Reality Gate warmup contract, DECISIONS.md
   // 2026-09-07). Runtime 0/0 yields a quiet NaN with no compiler
   // diagnostics; a compile-time 0.0/0.0 constant is not used because
   // constant folding diagnostics are compiler-version dependent.
   static double     NaNValue()
     {
      double zero = 0.0;
      return zero / zero;
     }

   // Warmup contract (deterministic NaN propagation, mirrors the Python
   // strategies' NaN-guarded semantics): an unavailable or uninitialized
   // indicator value must NEVER reach a comparator as a number.
   //   INVALID_HANDLE      -> NaN (handle creation failed -> Init failed,
   //                          but Evaluate may still be reached in tests)
   //   CopyBuffer <= 0     -> NaN (data not yet calculated / no history)
   //   EMPTY_VALUE         -> NaN (uninitialized buffer slot; official MQL5
   //                          docs: built-in indicators report EMPTY_VALUE
   //                          == DBL_MAX for bars they cannot compute,
   //                          e.g. RSI(14) bars 0..13). Passing DBL_MAX
   //                          through would trip the overbought/oversold
   //                          comparators and mint phantom signals.
   double            GetValue(int handle, int buffer, int shift)
     {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(handle == INVALID_HANDLE)
         return NaNValue();
      if(CopyBuffer(handle, buffer, shift, 1, buf) <= 0)
         return NaNValue();
      if(buf[0] == EMPTY_VALUE)
         return NaNValue();
      return buf[0];
     }

   double            EMA(int handle, int shift)      { return GetValue(handle, 0, shift); }
   double            RSI(int shift)                  { return GetValue(m_hRsi, 0, shift); }
   double            BollUpper(int shift)            { return GetValue(m_hBoll, 1, shift); }
   double            BollLower(int shift)            { return GetValue(m_hBoll, 2, shift); }
   double            MacdLine(int shift)             { return GetValue(m_hMacd, 0, shift); }
   double            MacdSignal(int shift)           { return GetValue(m_hMacd, 1, shift); }

   bool              IsNaN(double v)                 { return v != v; }

   // current close (completed bar)
   double            Close(int shift)                { return iClose(m_symbol, m_tf, shift); }

   void              FillPriceLevels(int dir, double atr, SBotSignal &sig)
     {
      sig.direction = dir;
      sig.slPrice   = 0.0;
      sig.tpPrice   = 0.0;
      if(dir == 0 || atr <= 0.0)
         return;
      double point  = SymbolInfoDouble(m_symbol, SYMBOL_POINT);
      double spread = (SymbolInfoDouble(m_symbol, SYMBOL_ASK) -
                       SymbolInfoDouble(m_symbol, SYMBOL_BID)) / point;
      double fill   = (dir > 0) ? SymbolInfoDouble(m_symbol, SYMBOL_ASK)
                                : SymbolInfoDouble(m_symbol, SYMBOL_BID);
      sig.slPrice   = fill - dir * m_params.slAtr * atr;
      sig.tpPrice   = fill + dir * m_params.tpAtr * atr;
      // never place stops inside the spread
      if(dir > 0)
        {
         double minSl = fill - spread - point;
         if(sig.slPrice > minSl) sig.slPrice = minSl;
        }
      else
        {
         double minSl = fill + spread + point;
         if(sig.slPrice < minSl) sig.slPrice = minSl;
        }
     }

   //-----------------------------------------------------------------
   // 1. EMA crossover — position held while fast/slow are aligned
   //-----------------------------------------------------------------
   SBotSignal        EvaluateEmaCrossover()
     {
      SBotSignal sig;
      ZeroMemory(sig);
      sig.direction = 0;
      double fast = EMA(m_hFast, 1);
      double slow = EMA(m_hSlow, 1);
      if(IsNaN(fast) || IsNaN(slow))
         return sig;
      if(fast > slow) sig.direction = 1;
      else if(fast < slow) sig.direction = -1;
      FillPriceLevels(sig.direction, GetValue(m_hAtr, 0, 1), sig);
      sig.valid = true;
      return sig;
     }

   //-----------------------------------------------------------------
   // 2. RSI reversal — enter on RSI escaping oversold/overbought,
   //    hold through the neutral band, stand aside at the extreme
   //-----------------------------------------------------------------
   SBotSignal        EvaluateRsiReversal()
     {
      SBotSignal sig;
      ZeroMemory(sig);
      sig.direction = 0;
      double r = RSI(1);
      double rPrev = RSI(2);
      if(IsNaN(r) || IsNaN(rPrev))
         return sig;

      bool nowOversold   = (r  < m_params.rsiOversold);
      bool prevOversold  = (rPrev < m_params.rsiOversold);
      bool nowOverbought = (r  > m_params.rsiOverbought);
      bool prevOverbought= (rPrev > m_params.rsiOverbought);

      // cross up out of oversold -> buy
      if(prevOversold && !nowOversold)
         m_state.emaDir = 1;               // reuse as rsi desired dir
      // cross down out of overbought -> sell
      else if(prevOverbought && !nowOverbought)
         m_state.emaDir = -1;

      if(!nowOversold && !nowOverbought)
        {
         // inside neutral band: keep the last direction
         sig.direction = m_state.emaDir;
        }
      else
        {
         sig.direction = 0;                // still at the extreme: stand aside
        }
      FillPriceLevels(sig.direction, GetValue(m_hAtr, 0, 1), sig);
      sig.valid = true;
      return sig;
     }

   //-----------------------------------------------------------------
   // 3. Donchian breakout — close above/below previous N-bar channel
   //-----------------------------------------------------------------
   SBotSignal        EvaluateDonchian()
     {
      SBotSignal sig;
      ZeroMemory(sig);
      sig.direction = 0;
      int n = m_params.donchianPeriod;
      // Warmup contract: the channel reads shifts 2..N+1. Until that many
      // bars exist, iHigh/iLow return 0 for out-of-range bars, which would
      // fabricate a zero-width channel and mint a phantom breakout
      // (Reality Gate, DECISIONS.md 2026-09-07). Signal stays invalid.
      if(Bars(m_symbol, m_tf) < n + 2)
         return sig;
      double close = Close(1);
      double upper = 0.0, lower = DBL_MAX;
      // channel over the previous N completed bars (shift 2..N+1)
      for(int i = 2; i < n + 2; i++)
        {
         double h = iHigh(m_symbol, m_tf, i);
         double l = iLow(m_symbol, m_tf, i);
         if(h > upper) upper = h;
         if(l < lower) lower = l;
        }
      if(lower == DBL_MAX)
         return sig;
      if(close > upper)      m_state.emaDir = 1;
      else if(close < lower) m_state.emaDir = -1;
      sig.direction = m_state.emaDir;
      FillPriceLevels(sig.direction, GetValue(m_hAtr, 0, 1), sig);
      sig.valid = true;
      return sig;
     }

   //-----------------------------------------------------------------
   // 4. Bollinger reversal — fade closes outside the bands
   //-----------------------------------------------------------------
   SBotSignal        EvaluateBollinger()
     {
      SBotSignal sig;
      ZeroMemory(sig);
      sig.direction = 0;
      double close = Close(1);
      double upper = BollUpper(1);
      double lower = BollLower(1);
      if(IsNaN(upper) || IsNaN(lower))
         return sig;
      if(close < lower)      sig.direction = 1;
      else if(close > upper) sig.direction = -1;
      FillPriceLevels(sig.direction, GetValue(m_hAtr, 0, 1), sig);
      sig.valid = true;
      return sig;
     }

   //-----------------------------------------------------------------
   // 5. MACD momentum — position aligned with MACD vs signal line
   //-----------------------------------------------------------------
   SBotSignal        EvaluateMacd()
     {
      SBotSignal sig;
      ZeroMemory(sig);
      sig.direction = 0;
      double line = MacdLine(1);
      double s    = MacdSignal(1);
      if(IsNaN(line) || IsNaN(s))
         return sig;
      if(line > s) sig.direction = 1;
      else if(line < s) sig.direction = -1;
      FillPriceLevels(sig.direction, GetValue(m_hAtr, 0, 1), sig);
      sig.valid = true;
      return sig;
     }

public:
                     CSignalEngine() : m_initialized(false) {}

   bool              Init(string symbol, ENUM_TIMEFRAMES tf, SBotParams &params)
     {
      m_symbol = symbol;
      m_tf     = tf;
      m_params = params;
      ZeroMemory(m_state);

      m_hFast = iMA(symbol, tf, params.fastEma, 0, MODE_EMA, PRICE_CLOSE);
      m_hSlow = iMA(symbol, tf, params.slowEma, 0, MODE_EMA, PRICE_CLOSE);
      m_hRsi  = iRSI(symbol, tf, params.rsiPeriod, PRICE_CLOSE);
      m_hBoll = iBands(symbol, tf, params.bollingerPeriod, 0,
                       params.bollingerDev, PRICE_CLOSE);
      m_hMacd = iMACD(symbol, tf, params.macdFast, params.macdSlow,
                      params.macdSignal, PRICE_CLOSE);
      m_hAtr  = iATR(symbol, tf, 14);

      m_initialized = (m_hFast != INVALID_HANDLE && m_hSlow != INVALID_HANDLE &&
                       m_hRsi != INVALID_HANDLE && m_hBoll != INVALID_HANDLE &&
                       m_hMacd != INVALID_HANDLE && m_hAtr != INVALID_HANDLE);
      if(!m_initialized)
         Print("[mql5bot] SignalEngine: one or more indicators failed to load");
      return m_initialized;
     }

   void              Deinit()
     {
      IndicatorRelease(m_hFast);
      IndicatorRelease(m_hSlow);
      IndicatorRelease(m_hRsi);
      IndicatorRelease(m_hBoll);
      IndicatorRelease(m_hMacd);
      IndicatorRelease(m_hAtr);
      m_initialized = false;
     }

   bool              IsReady() const { return m_initialized; }

   // Called on every closed bar (the EA invokes this once per new bar).
   SBotSignal        Evaluate(ENUM_MQL5BOT_STRATEGY strategy)
     {
      SBotSignal sig;
      ZeroMemory(sig);
      switch(strategy)
        {
         case STRAT_EMA_CROSSOVER:      return EvaluateEmaCrossover();
         case STRAT_RSI_REVERSAL:       return EvaluateRsiReversal();
         case STRAT_DONCHIAN_BREAKOUT:  return EvaluateDonchian();
         case STRAT_BOLLINGER_REVERSAL: return EvaluateBollinger();
         case STRAT_MACD_MOMENTUM:      return EvaluateMacd();
        }
      return sig;
     }
  };

#endif // MQL5BOT_SIGNALENGINE_MQH
//+------------------------------------------------------------------+
