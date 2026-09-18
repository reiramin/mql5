//+------------------------------------------------------------------+
//|                                      Mql5Bot/PositionGuard.mqh   |
//|     Exit management: ATR trailing stop, breakeven and partial    |
//|     scale-out — applied on closed bars, never intrabar           |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_POSITIONGUARD_MQH
#define MQL5BOT_POSITIONGUARD_MQH

#include <Mql5Bot/Config.mqh>

class CPositionGuard
  {
private:
   int               m_atrPeriod;
   int               m_atrHandle;
   double            m_trailAtr;        // 0 = off
   double            m_breakevenAtr;    // 0 = off
   double            m_breakevenOffsetPoints;
   double            m_partialAtr;      // 0 = off
   double            m_partialFraction; // 0.5
   int               m_barsInitiated;   // bars since last partial/breakeven step
   double            m_lastKnownAtr;

   double            GetATR(string symbol, ENUM_TIMEFRAMES tf, int shift)
     {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(m_atrHandle == INVALID_HANDLE)
         return 0.0;
      if(CopyBuffer(m_atrHandle, 0, shift, 1, buf) <= 0)
         return 0.0;
      return buf[0];
     }

public:
                     CPositionGuard() :
                        m_atrPeriod(14), m_atrHandle(INVALID_HANDLE),
                        m_trailAtr(0.0), m_breakevenAtr(0.0),
                        m_breakevenOffsetPoints(0.0), m_partialAtr(0.0),
                        m_partialFraction(0.5), m_barsInitiated(0),
                        m_lastKnownAtr(0.0) {}
                    ~CPositionGuard()
     {
      if(m_atrHandle != INVALID_HANDLE)
         IndicatorRelease(m_atrHandle);
     }

   bool              Init(string symbol, ENUM_TIMEFRAMES tf,
                         double trailAtr, double breakevenAtr,
                         double breakevenOffsetPoints,
                         double partialAtr, double partialFraction,
                         int atrPeriod = 14)
     {
      m_atrPeriod           = atrPeriod;
      m_trailAtr            = trailAtr;
      m_breakevenAtr        = breakevenAtr;
      m_breakevenOffsetPoints = breakevenOffsetPoints;
      m_partialAtr          = partialAtr;
      m_partialFraction     = MathMax(0.1, MathMin(0.9, partialFraction));
      m_atrHandle = iATR(symbol, tf, m_atrPeriod);
      if(m_atrHandle == INVALID_HANDLE)
        {
         Print("[mql5bot] PositionGuard: iATR failed");
         return false;
        }
      return true;
     }

   double            ATR(string symbol, ENUM_TIMEFRAMES tf, int shift = 1)
     {
      double v = GetATR(symbol, tf, shift);
      if(v > 0.0)
         m_lastKnownAtr = v;
      return (v > 0.0) ? v : m_lastKnownAtr;
     }

   void              OnPositionOpened()
     {
      m_barsInitiated = 0;
     }

   //-----------------------------------------------------------------
   // Decide the exit action on a new closed bar. Modifies the input
   // prices. Returns a bitmask:
   //   EXIT_CLOSE_FULL   close the whole position
   //   EXIT_CLOSE_PARTIAL close `fraction` of it (SL then moves to BE)
   //   EXIT_MODIFY_SLTP  adjust SL/TP via ModifySLTP
   //-----------------------------------------------------------------
#define EXIT_NONE          0
#define EXIT_CLOSE_FULL    1
#define EXIT_CLOSE_PARTIAL 2
#define EXIT_MODIFY_SLTP   4

   int               Review(string symbol, ENUM_TIMEFRAMES tf,
                           ulong ticket, double &sl, double &tp,
                           bool partialAlreadyDone = false)
     {
      if(!PositionSelectByTicket(ticket))
         return EXIT_NONE;
      long dir       = PositionGetInteger(POSITION_TYPE);
      double entry   = PositionGetDouble(POSITION_PRICE_OPEN);
      double current = PositionGetDouble(POSITION_PRICE_CURRENT);
      double atr     = ATR(symbol, tf, 1);
      if(atr <= 0.0)
         return EXIT_NONE;

      double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
      double spread = (SymbolInfoDouble(symbol, SYMBOL_ASK) -
                       SymbolInfoDouble(symbol, SYMBOL_BID)) / point;
      int action = EXIT_NONE;
      m_barsInitiated++;

      if(dir == POSITION_TYPE_LONG)
        {
         double profitDist = current - entry;
         //--- trailing stop (never loosened)
         if(m_trailAtr > 0.0)
           {
            double trail = current - m_trailAtr * atr;
            if(trail > sl)
              {
               sl = trail;
               action |= EXIT_MODIFY_SLTP;
              }
           }
         //--- breakeven
         if(m_breakevenAtr > 0.0 && profitDist >= m_breakevenAtr * atr)
           {
            double be = entry + m_breakevenOffsetPoints * point + spread;
            if(be > sl)
              {
               sl = be;
               action |= EXIT_MODIFY_SLTP;
              }
           }
         //--- partial scale-out (fires once per position; the persisted
         //    partialAlreadyDone flag survives restarts — S2 rebuild)
         if(m_partialAtr > 0.0 && !partialAlreadyDone && m_barsInitiated > 1 &&
            profitDist >= m_partialAtr * atr)
           {
            sl = entry + spread;
            tp = 0.0;   // clear TP after partial to avoid 0-lot TP errors
            m_barsInitiated = -100000; // disarm
            action |= EXIT_MODIFY_SLTP;
            return action | EXIT_CLOSE_PARTIAL;
           }
        }
      else
        {
         double profitDist = entry - current;
         if(m_trailAtr > 0.0)
           {
            double trail = current + m_trailAtr * atr;
            if(trail < sl)
              {
               sl = trail;
               action |= EXIT_MODIFY_SLTP;
              }
           }
         if(m_breakevenAtr > 0.0 && profitDist >= m_breakevenAtr * atr)
           {
            double be = entry - m_breakevenOffsetPoints * point - spread;
            if(be < sl)
              {
               sl = be;
               action |= EXIT_MODIFY_SLTP;
              }
           }
         if(m_partialAtr > 0.0 && !partialAlreadyDone && m_barsInitiated > 1 &&
            profitDist >= m_partialAtr * atr)
           {
            sl = entry - spread;
            tp = 0.0;
            m_barsInitiated = -100000;
            action |= EXIT_MODIFY_SLTP;
            return action | EXIT_CLOSE_PARTIAL;
           }
        }
      return action;
     }

   double            PartialFraction() const { return m_partialFraction; }
  };

#endif // MQL5BOT_POSITIONGUARD_MQH
//+------------------------------------------------------------------+
