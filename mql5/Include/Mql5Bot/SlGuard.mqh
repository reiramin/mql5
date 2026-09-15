//+------------------------------------------------------------------+
//|                                          Mql5Bot/SlGuard.mqh     |
//| Post-fill stop-loss enforcement (SPEC §3.2 — non-negotiable):    |
//|                                                                  |
//| After any successful position open (or after adopting a position |
//| on restart) the guard verifies that the position really carries  |
//| a valid SL (present, on the correct side, respecting the broker  |
//| stops level). If not: attempt one modify, re-verify, and if the  |
//| remediation still fails: close the position. A position the      |
//| guard can neither protect nor close escalates to the caller      |
//| (EA -> CRITICAL log + alert + ENGINE_HALT).                      |
//|                                                                  |
//| No Sleep: verification is pumped from OnTimer; trade operations  |
//| go through CTradeManager which may hand them to the RetryQueue.  |
//| The pure verdict function (SlVerdict) is unit-testable without a |
//| broker.                                                          |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_SLGUARD_MQH
#define MQL5BOT_SLGUARD_MQH

#include <Mql5Bot/Config.mqh>
#include <Mql5Bot/SymbolSpec.mqh>
#include <Mql5Bot/TradeManager.mqh>

//--- Pure SL verdict -------------------------------------------------------+
enum ENUM_SL_VERDICT
  {
   SL_VERDICT_OK         = 0,
   SL_VERDICT_MISSING    = 1, // sl <= 0 or NaN
   SL_VERDICT_WRONG_SIDE = 2, // buy SL above entry / sell SL below entry
   SL_VERDICT_TOO_CLOSE  = 3, // inside the broker stops level
   SL_VERDICT_NOT_FOUND  = 4  // position parameters unusable
  };

// Deterministic, broker-free SL check used by tests and the pump.
ENUM_SL_VERDICT SlVerdict(const SSymbolSpec &spec, const long dir,
                          const double entry, const double sl)
  {
   if(dir != POSITION_TYPE_BUY && dir != POSITION_TYPE_SELL)
      return SL_VERDICT_NOT_FOUND;
   if(entry <= 0.0)
      return SL_VERDICT_NOT_FOUND;
   if(sl != sl || sl <= 0.0)
      return SL_VERDICT_MISSING;
   double minStop = SpecMinStopDistance(spec);
   double eps = (spec.tickSize > 0.0) ? spec.tickSize * 0.5 : 0.0;
   if(dir == POSITION_TYPE_BUY)
     {
      if(sl >= entry)
         return SL_VERDICT_WRONG_SIDE;
      if(minStop > 0.0 && (entry - sl) < minStop - eps)
         return SL_VERDICT_TOO_CLOSE;
     }
   else
     {
      if(sl <= entry)
         return SL_VERDICT_WRONG_SIDE;
      if(minStop > 0.0 && (sl - entry) < minStop - eps)
         return SL_VERDICT_TOO_CLOSE;
     }
   return SL_VERDICT_OK;
  }

//+------------------------------------------------------------------+
//| Orchestrating guard                                              |
//+------------------------------------------------------------------+
#define SLG_MAX_ITEMS   8
#define SLG_MAX_PUMPS_PER_TICK 3

class CSlGuard
  {
private:
   struct SVerifyItem
     {
      ulong    magic;
      string   symbol;
      datetime since;        // only positions opened >= this time are ours
      double   desiredSl;    // 0 = unknown -> position must be closed
      double   desiredTp;
      ulong    ticket;       // resolved on first pump
      long     dir;
      int      pumps;        // number of pump visits
      int      phase;        // 0 new, 1 modify issued, 2 close issued
      bool     active;
                    SVerifyItem()
       {
        magic = 0; symbol = "";
        since = 0; desiredSl = 0.0; desiredTp = 0.0;
        ticket = 0; dir = 0; pumps = 0; phase = 0; active = false;
       }
     };

   SVerifyItem       m_items[SLG_MAX_ITEMS];
   int               m_findSlot()
     {
      for(int i = 0; i < SLG_MAX_ITEMS; i++)
         if(!m_items[i].active)
            return i;
      return -1;
     }

     bool              FindPosition(ulong &ticket, long &dir, double &entry,
                                  double &sl, double &tp) const
     {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong t = PositionGetTicket(i);
         if(t == 0)
            continue;
         string symbol = PositionGetString(POSITION_SYMBOL);
         // resolve candidate against every active item
         for(int k = 0; k < SLG_MAX_ITEMS; k++)
           {
            if(!m_items[k].active)
               continue;
            if(symbol != m_items[k].symbol)
               continue;
            if(PositionGetInteger(POSITION_MAGIC) != m_items[k].magic)
               continue;
            if(m_items[k].ticket != 0)
              {
               if(m_items[k].ticket != t)
                  continue;              // item is bound to another ticket
              }
            else if((datetime)PositionGetInteger(POSITION_TIME) < m_items[k].since)
               continue;                 // opened before this item: not ours
            ticket = t;
            dir    = (long)PositionGetInteger(POSITION_TYPE);
            entry  = PositionGetDouble(POSITION_PRICE_OPEN);
            sl     = PositionGetDouble(POSITION_SL);
            tp     = PositionGetDouble(POSITION_TP);
            return true;
           }
        }
      return false;
     }

public:
                     CSlGuard()
     {
      for(int i = 0; i < SLG_MAX_ITEMS; i++)
         m_items[i].active = false;
     }

   int               ActiveCount() const
     {
      int n = 0;
      for(int i = 0; i < SLG_MAX_ITEMS; i++)
         if(m_items[i].active)
            n++;
      return n;
     }

   // Register a fresh open (ticket==0: found by magic+symbol+time window)
   // or an adopted position (ticket!=0: resolved directly). desiredSl <= 0
   // means the position cannot be protected -> close path.
   bool              Enqueue(const ulong magic, const string symbol,
                             const datetime since, const double desiredSl,
                             const double desiredTp, const ulong ticket = 0)
     {
      int slot = m_findSlot();
      if(slot < 0)
        {
         Print("[mql5bot] SlGuard queue full — escalation required");
         return false;
        }
      m_items[slot].magic      = magic;
      m_items[slot].symbol     = symbol;
      m_items[slot].since      = since;
      m_items[slot].desiredSl  = desiredSl;
      m_items[slot].desiredTp  = desiredTp;
      m_items[slot].ticket     = ticket;
      m_items[slot].dir        = 0;
      m_items[slot].pumps      = 0;
      m_items[slot].phase      = 0;
      m_items[slot].active     = true;
      return true;
     }

   // Pump verification once per OnTimer. Outcomes:
   //   secured++   position now carries a valid SL (or vanished with a
   //               valid SL protection already issued)
   //   closed++    guard had to close the position (caller: CRITICAL)
   //   escalated++ guard could neither secure nor close (caller: HALT)
   void              Pump(CTradeManager &trade, const SSymbolSpec &spec,
                          int &secured, int &closed, int &escalated)
     {
      secured = 0;
      closed  = 0;
      escalated = 0;
      int processed = 0;
      for(int i = 0; i < SLG_MAX_ITEMS && processed < SLG_MAX_PUMPS_PER_TICK; i++)
        {
         if(!m_items[i].active)
            continue;
         processed++;

         ulong ticket = m_items[i].ticket;
         long dir = 0;
         double entry = 0.0, sl = 0.0, tp = 0.0;

         if(ticket == 0)
           {
            // not resolved yet: search by magic/symbol/time window
            if(!FindPosition(ticket, dir, entry, sl, tp))
              {
               m_items[i].pumps++;
               if(m_items[i].pumps > 10)
                 {
                  // no position ever appeared (e.g. order never filled)
                  PrintFormat("[mql5bot] SlGuard: no position appeared for %s (pumps=%d)",
                              m_items[i].symbol, m_items[i].pumps);
                  m_items[i].active = false;
                 }
               continue;
              }
            m_items[i].ticket = ticket;
            m_items[i].dir    = dir;
           }
         else
           {
            if(!PositionSelectByTicket(ticket))
              {
               // gone: closed by SL/TP/stop-out or manually — nothing to do
               m_items[i].active = false;
               secured++;          // not left unprotected
               continue;
              }
            dir   = (long)PositionGetInteger(POSITION_TYPE);
            entry = PositionGetDouble(POSITION_PRICE_OPEN);
            sl    = PositionGetDouble(POSITION_SL);
            tp    = PositionGetDouble(POSITION_TP);
           }

         ENUM_SL_VERDICT v = SlVerdict(spec, dir, entry, sl);
         if(v == SL_VERDICT_OK)
           {
            m_items[i].active = false;
            secured++;
            continue;
           }

         m_items[i].pumps++;
         if(m_items[i].desiredSl <= 0.0)
           {
            // cannot protect: close is the only safe remediation
            if(m_items[i].phase == 0)
              {
               trade.ClosePosition(ticket, 0.0);
               m_items[i].phase = 2;
              }
            else if(m_items[i].pumps > 15)
              {
               m_items[i].active = false;
               escalated++;
              }
            continue;
           }

         // phase 0: issue one modify with the desired SL
         if(m_items[i].phase == 0)
           {
            if(m_items[i].pumps >= 1)
              {
               trade.ModifySLTP(ticket, m_items[i].desiredSl,
                                m_items[i].desiredTp);
               m_items[i].phase = 1;
              }
            continue;
           }

         // phase 1: modify issued; give retries several pumps to land, then close
         if(m_items[i].phase == 1)
           {
            if(m_items[i].pumps >= 8)
              {
               PrintFormat("[mql5bot] SlGuard: SL remediation failed on #%I64u — closing",
                           ticket);
               trade.ClosePosition(ticket, 0.0);
               m_items[i].phase = 2;
              }
            continue;
           }

         // phase 2: close issued — wait until the position is gone
         if(m_items[i].phase == 2)
           {
            if(!PositionSelectByTicket(ticket))
              {
               m_items[i].active = false;
               closed++;
              }
            else if(m_items[i].pumps > 20)
              {
               PrintFormat("[mql5bot] SlGuard: ESCALATION — cannot close #%I64u without SL",
                           ticket);
               m_items[i].active = false;
               escalated++;
              }
           }
        }
     }

   // Is this position already covered by an active item? Covers both
   // ticket-bound items (adopted / protection path) and unbound items
   // (fresh entries found by magic+symbol+time window), so the EA never
   // enqueues two guard items for the same position.
   bool              CoversTicket(const ulong magic, const string symbol,
                                  const ulong ticket, const datetime openTime) const
     {
      for(int i = 0; i < SLG_MAX_ITEMS; i++)
        {
         if(!m_items[i].active)
            continue;
         if(m_items[i].ticket != 0)
           {
            if(m_items[i].ticket == ticket)
               return true;
            continue;
           }
         if(m_items[i].magic == magic && m_items[i].symbol == symbol &&
            m_items[i].since <= openTime)
            return true;
        }
      return false;
     }
  };

#endif // MQL5BOT_SLGUARD_MQH
//+------------------------------------------------------------------+
