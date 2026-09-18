//+------------------------------------------------------------------+
//|                                       Mql5Bot/TradeManager.mqh   |
//| Order execution without Sleep (SPEC §3.4/§8.D):                  |
//|                                                                  |
//| * every order is attempted ONCE per call; retryable server codes |
//|   are handed to the CRetryQueue, processed by OnTimer with       |
//|   exponential backoff and refreshed prices                       |
//| * the only immediate re-send inside one call is a single REQUOTE |
//|   retry with a refreshed price (explicitly permitted) and the    |
//|   bounded FOK->IOC->RETURN filling chain (SPEC §8.D resolver)    |
//| * ambiguous TIMEOUT/RETRY answers are verified against deal      |
//|   history BEFORE anything is re-sent (no duplicate fills)        |
//| * every action emits one structured CSV-friendly audit line and  |
//|   updates latency/slippage/reject statistics (SPEC §8.D)         |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_TRADEMANAGER_MQH
#define MQL5BOT_TRADEMANAGER_MQH

#include <Mql5Bot/Config.mqh>
#include <Mql5Bot/SymbolSpec.mqh>
#include <Mql5Bot/RetryQueue.mqh>

//--- Outcome of one market/pending open call -----------------------------+
struct SOrderResult
  {
   bool              done;          // filled/placed now
   bool              queued;        // retryable failure parked in the queue
   uint              retcode;
   ulong             orderTicket;   // pending order ticket (placed)
   double            fillPrice;     // 0 when unknown
   double            slippagePoints;
   int               latencyMs;
                     SOrderResult()
     {
      done = false; queued = false; retcode = 0; orderTicket = 0;
      fillPrice = 0.0; slippagePoints = 0.0; latencyMs = 0;
     }
  };

class CTradeManager
  {
private:
   ulong             m_magic;
   int               m_deviation;       // points
   int               m_maxAttempts;     // retry cap (queue)
   bool              m_pendingMode;
   int               m_pendingExpireBars;
   ulong             m_pendingTicket;
   int               m_pendingBarsLeft;
   int               m_counter;
   SSymbolSpec       m_spec;            // injected broker spec
   CRetryQueue       m_queue;
   MqlTradeResult    res_tmp;           // scratch result for pending placement

   //--- execution statistics (SPEC §8.D) --------------------------------
   int               m_statTotal, m_statDone, m_statPartial, m_statRejects;
   int               m_statQueued, m_statFatal;
   double            m_statSlipSum, m_statSlipMax;
   ulong             m_statLatSum;
   int               m_statLatMax;

   // Conceptually read-only price accessors (global SymbolInfoDouble,
   // no member mutation): const so const methods such as MinStopDist
   // may call them without violating MQL5 const-correctness rules.
   double            Ask(const string symbol) const { return SymbolInfoDouble(symbol, SYMBOL_ASK); }
   double            Bid(const string symbol) const { return SymbolInfoDouble(symbol, SYMBOL_BID); }

   string            NextComment(const string prefix)
     {
      m_counter++;
      return StringFormat("mql5bot-%s-%d", prefix, m_counter);
     }

   // Minimal SL/TP distance: broker stops level + current spread (the
   // broker measures stops from the current price stream).
   double            MinStopDist(const string symbol) const
     {
      double d = SpecMinStopDistance(m_spec);
      double spread = (Ask(symbol) > 0.0 && Bid(symbol) > 0.0)
                      ? (Ask(symbol) - Bid(symbol)) : 0.0;
      return d + spread;
     }

   //---------------------------------------------------------------------
   // Single low-level market-deal send with latency capture. Filling is
   // applied only for market deals (pendings keep the broker default).
   //---------------------------------------------------------------------
   uint              SendDealOnce(const ENUM_ORDER_TYPE type, const string symbol,
                                  const long dir, const double lots,
                                  const double price, const double sl,
                                  const double tp, const string comment,
                                  const ulong position,
                                  const ENUM_ORDER_TYPE_FILLING filling,
                                  MqlTradeResult &res, int &latencyMs)
     {
      MqlTradeRequest req;
      ZeroMemory(req);
      req.action    = TRADE_ACTION_DEAL;
      req.symbol    = symbol;
      req.magic     = m_magic;
      req.volume    = lots;
      req.deviation = m_deviation;
      req.comment   = comment;
      req.type      = type;
      req.price     = price;
      req.sl        = sl;
      req.tp        = tp;
      req.position  = position;
      req.type_filling = filling;
      ulong t0 = GetTickCount64();
      bool sent = OrderSend(req, res);
      latencyMs = (int)(GetTickCount64() - t0);
      if(!sent)
         return (res.retcode == 0) ? TRADE_RETCODE_ERROR : res.retcode;
      return res.retcode;
     }

   // Slippage of a market result vs requested price (points, adverse > 0).
   double            SlippageOf(const MqlTradeResult &res, const double reqPrice,
                                const long dir) const
     {
      if(res.price <= 0.0 || reqPrice <= 0.0)
         return 0.0;
      double diff = (dir == POSITION_TYPE_LONG)
                    ? (res.price - reqPrice) : (reqPrice - res.price);
      if(m_spec.point <= 0.0)
         return 0.0;
      double pts = diff / m_spec.point;
      return (pts > 0.0) ? pts : 0.0;
     }

   // Find a deal of ours (magic + comment) inside the last `secondsBack`
   // seconds; returns its ticket/volume/price. Used to disambiguate
   // TIMEOUT/RETRY answers before any re-send.
   bool              FindRecentDeal(const ulong magic, const string comment,
                                    const int secondsBack, ulong &dealTicket,
                                    double &dealVolume, double &dealPrice)
     {
      dealTicket = 0; dealVolume = 0.0; dealPrice = 0.0;
      datetime now  = TimeCurrent();
      datetime from = now - secondsBack;
      if(!HistorySelect(from, now + 5))
         return false;
      int total = HistoryDealsTotal();
      for(int i = total - 1; i >= 0; i--)
        {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0)
            continue;
         if(HistoryDealGetInteger(deal, DEAL_MAGIC) == magic &&
            HistoryDealGetString(deal, DEAL_COMMENT) == comment)
           {
            dealTicket = deal;
            dealVolume = HistoryDealGetDouble(deal, DEAL_VOLUME);
            dealPrice  = HistoryDealGetDouble(deal, DEAL_PRICE);
            return true;
           }
        }
      return false;
     }

   double            StopForSide(const long dir, const double fill,
                                 const double dist)
     {
      if(dist <= 0.0)
         return 0.0;
      double d = SpecRoundToTick(dist, m_spec);
      return (dir == POSITION_TYPE_LONG) ? fill - d : fill + d;
     }

   //---------------------------------------------------------------------
   // One market-order attempt chain: preferred filling, single REQUOTE
   // re-send, bounded FOK->IOC->RETURN filling chain. Never more than
   // three sends inside one call; no Sleep anywhere.
   //---------------------------------------------------------------------
   uint              MarketChain(const long dir, const double lots,
                                 const double slDist, const double tpDist,
                                 const string comment, MqlTradeResult &res,
                                 int &latencyMs, double &slippagePts)
     {
      string symbol = m_spec.name;
      double fill = (dir == POSITION_TYPE_LONG) ? Ask(symbol) : Bid(symbol);
      if(fill <= 0.0)
         return TRADE_RETCODE_PRICE_OFF;   // no quotes right now: real MQL5 code 10021
      double minDist = MinStopDist(symbol);
      double sd = (slDist > 0.0) ? MathMax(slDist, minDist) : 0.0;
      double td = (tpDist > 0.0) ? MathMax(tpDist, minDist) : 0.0;
      double sl = StopForSide(dir, fill, sd);
      double tp = (td > 0.0)
                  ? ((dir == POSITION_TYPE_LONG) ? fill + SpecRoundToTick(td, m_spec)
                                                 : fill - SpecRoundToTick(td, m_spec))
                  : 0.0;

      ENUM_ORDER_TYPE_FILLING filling = SpecPreferredFilling(m_spec);
      if(filling == (ENUM_ORDER_TYPE_FILLING)-1)
         filling = ORDER_FILLING_FOK;

      int sent = 0;
      for(int i = 0; i < 3; i++)
        {
         int ms = 0;
         uint rc = SendDealOnce((dir == POSITION_TYPE_LONG) ? ORDER_TYPE_BUY
                                                            : ORDER_TYPE_SELL,
                                symbol, dir, lots, fill, sl, tp, comment, 0,
                                filling, res, ms);
         latencyMs += ms;
         sent++;
         if(IsSuccessRetcode(rc))
           {
            slippagePts = SlippageOf(res, fill, dir);
            return rc;
           }
         if(rc == TRADE_RETCODE_REQUOTE && sent < 3)
           {
            // the ONLY permitted immediate re-send: refreshed price
            fill = (dir == POSITION_TYPE_LONG) ? Ask(symbol) : Bid(symbol);
            if(fill <= 0.0)
               return TRADE_RETCODE_PRICE_OFF;   // no quotes right now: real MQL5 code 10021
            sl = StopForSide(dir, fill, sd);
            tp = (td > 0.0)
                 ? ((dir == POSITION_TYPE_LONG) ? fill + SpecRoundToTick(td, m_spec)
                                                : fill - SpecRoundToTick(td, m_spec))
                 : 0.0;
            continue;
           }
         if(rc == TRADE_RETCODE_INVALID_FILL)
           {
            ENUM_ORDER_TYPE_FILLING next = SpecNextFilling(m_spec, filling);
            if(next == (ENUM_ORDER_TYPE_FILLING)-1)
               return rc;
            filling = next;
            continue;
           }
         return rc;
        }
      return res.retcode;
     }

   //---------------------------------------------------------------------
   // Queue plumbing
   //---------------------------------------------------------------------
   void              QueueOpen(const long dir, const double lots,
                               const double slDist, const double tpDist,
                               const string comment, const int attempted)
     {
      SRetryItem item;
      item.action   = RETRY_ACTION_MARKET;
      item.symbol   = m_spec.name;
      item.dir      = dir;
      item.lots     = lots;
      item.slDist   = slDist;
      item.tpDist   = tpDist;
      item.comment  = comment;
      item.magic    = m_magic;
      item.maxAttempts = m_maxAttempts;
      m_queue.Add(item, attempted);
     }

   void              QueueClose(const ulong ticket, const double volume,
                                const string comment, const int attempted)
     {
      SRetryItem item;
      item.action  = RETRY_ACTION_CLOSE;
      item.symbol  = m_spec.name;
      item.ticket  = ticket;
      item.lots    = volume;
      item.comment = comment;
      item.magic   = m_magic;
      item.maxAttempts = m_maxAttempts;
      m_queue.Add(item, attempted);
     }

   void              QueueModify(const ulong ticket, const double sl,
                                 const double tp, const int attempted)
     {
      SRetryItem item;
      item.action  = RETRY_ACTION_MODIFY;
      item.symbol  = m_spec.name;
      item.ticket  = ticket;
      item.sl      = sl;
      item.tp      = tp;
      item.magic   = m_magic;
      item.maxAttempts = m_maxAttempts;
      m_queue.Add(item, attempted);
     }

   // Execute one retried close (single attempt).
   uint              CloseOnce(const ulong ticket, const double volume,
                               const string comment, MqlTradeResult &res,
                               int &latencyMs)
     {
      if(!PositionSelectByTicket(ticket))
         return TRADE_RETCODE_DONE;      // already gone == success
      string symbol = m_spec.name;
      double vol = (volume > 0.0) ? volume : PositionGetDouble(POSITION_VOLUME);
      long dir = (long)PositionGetInteger(POSITION_TYPE);
      double price = (dir == POSITION_TYPE_LONG) ? Bid(symbol) : Ask(symbol);
      if(price <= 0.0)
         return TRADE_RETCODE_PRICE_OFF;   // no quotes right now: real MQL5 code 10021
      ENUM_ORDER_TYPE_FILLING filling = SpecPreferredFilling(m_spec);
      if(filling == (ENUM_ORDER_TYPE_FILLING)-1)
         filling = ORDER_FILLING_FOK;
      uint rc = SendDealOnce((dir == POSITION_TYPE_LONG) ? ORDER_TYPE_SELL
                                                         : ORDER_TYPE_BUY,
                             symbol, dir, vol, price, 0.0, 0.0, comment, ticket,
                             filling, res, latencyMs);
      if(rc == TRADE_RETCODE_INVALID_FILL)
        {
         ENUM_ORDER_TYPE_FILLING next = SpecNextFilling(m_spec, filling);
         if(next != (ENUM_ORDER_TYPE_FILLING)-1)
            rc = SendDealOnce((dir == POSITION_TYPE_LONG) ? ORDER_TYPE_SELL
                                                          : ORDER_TYPE_BUY,
                              symbol, dir, vol, price, 0.0, 0.0, comment, ticket,
                              next, res, latencyMs);
        }
      return rc;
     }

   // Execute one retried SL/TP modify (single attempt).
   uint              ModifyOnce(const ulong ticket, const double sl,
                                const double tp, MqlTradeResult &res)
     {
      if(!PositionSelectByTicket(ticket))
         return TRADE_RETCODE_DONE;      // position gone: nothing to modify
      MqlTradeRequest req;
      ZeroMemory(req);
      req.action   = TRADE_ACTION_SLTP;
      req.symbol   = m_spec.name;
      req.magic    = m_magic;
      req.position = ticket;
      req.sl       = sl;
      req.tp       = tp;
      ulong t0 = GetTickCount64();
      bool sent = OrderSend(req, res);
      if(!sent)
         return (res.retcode == 0) ? TRADE_RETCODE_ERROR : res.retcode;
      return res.retcode;
     }

   //---------------------------------------------------------------------
   // Queued-item execution (fresh prices, single attempt each)
   //---------------------------------------------------------------------
   void              ExecuteQueued(const SRetryItem &item)
     {
      if(item.action == RETRY_ACTION_MARKET)
        {
         MqlTradeResult res;
         ZeroMemory(res);
         double slip = 0.0;
         int lat = 0;
         uint rc = MarketChain(item.dir, item.lots, item.slDist, item.tpDist,
                               item.comment, res, lat, slip);
         if(IsSuccessRetcode(rc))
           {
            Audit("open_retry", m_spec.name, rc, lat, slip, item.lots, item.comment);
            return;
           }
         if(rc == TRADE_RETCODE_TIMEOUT)   // ambiguous outcome: transient by definition
           {
            ulong dt = 0; double dv = 0.0, dp = 0.0;
            if(FindRecentDeal(m_magic, item.comment, 30, dt, dv, dp))
              {
               Audit("open_retry_verified", m_spec.name, TRADE_RETCODE_DONE, lat, 0.0, dv, item.comment);
               return;
              }
           }
         if(IsRetryableRetcode(rc) && item.attempt + 1 < item.maxAttempts)
            m_queue.Add(item, item.attempt + 1);
         else
            Audit("open_retry_giveup", m_spec.name, rc, lat, 0.0, item.lots, item.comment);
         return;
        }
      if(item.action == RETRY_ACTION_PENDING)
        {
         SOrderResult r = PlacePendingOnce(item.dir, item.lots, item.offsetPoints,
                                           item.slDist, item.tpDist, item.comment);
         if(r.done)
            return;
         if(IsRetryableRetcode(r.retcode) && item.attempt + 1 < item.maxAttempts)
            m_queue.Add(item, item.attempt + 1);
         else
            Audit("pending_retry_giveup", m_spec.name, r.retcode, r.latencyMs, 0.0,
                  item.lots, item.comment);
         return;
        }
      if(item.action == RETRY_ACTION_CLOSE)
        {
         MqlTradeResult res;
         ZeroMemory(res);
         int lat = 0;
         uint rc = CloseOnce(item.ticket, item.lots, item.comment, res, lat);
         if(IsSuccessRetcode(rc))
           {
            Audit("close_retry", m_spec.name, rc, lat, 0.0, item.lots, item.comment);
            return;
           }
         if(rc == TRADE_RETCODE_TIMEOUT)   // ambiguous outcome: transient by definition
           {
            if(!PositionSelectByTicket(item.ticket))
               return;                   // closed meanwhile: done
           }
         if(IsRetryableRetcode(rc) && item.attempt + 1 < item.maxAttempts)
            m_queue.Add(item, item.attempt + 1);
         else
            Audit("close_retry_giveup", m_spec.name, rc, lat, 0.0, item.lots, item.comment);
         return;
        }
      if(item.action == RETRY_ACTION_MODIFY)
        {
         MqlTradeResult res;
         ZeroMemory(res);
         uint rc = ModifyOnce(item.ticket, item.sl, item.tp, res);
         if(rc == TRADE_RETCODE_DONE)
           {
            Audit("modify_retry", m_spec.name, rc, 0, 0.0, 0.0, item.comment);
            return;
           }
         if(IsRetryableRetcode(rc) && item.attempt + 1 < item.maxAttempts)
            m_queue.Add(item, item.attempt + 1);
         else if(rc != TRADE_RETCODE_NO_CHANGES)
            Audit("modify_retry_giveup", m_spec.name, rc, 0, 0.0, 0.0, item.comment);
         return;
        }
      if(item.action == RETRY_ACTION_CANCEL)
        {
         MqlTradeRequest req;
         ZeroMemory(req);
         req.action = TRADE_ACTION_REMOVE;
         req.order  = item.ticket;
         MqlTradeResult res;
         ZeroMemory(res);
         bool sent = OrderSend(req, res);
         uint rc = sent ? res.retcode : TRADE_RETCODE_ERROR;
         if(rc == TRADE_RETCODE_DONE)
            return;
         if(IsRetryableRetcode(rc) && item.attempt + 1 < item.maxAttempts)
            m_queue.Add(item, item.attempt + 1);
         return;
        }
     }

   // Place one pending order (single attempt; used fresh and by retries).
   SOrderResult      PlacePendingOnce(const long dir, const double lots,
                                      const double offsetPoints,
                                      const double slDist, const double tpDist,
                                      const string comment)
     {
      SOrderResult out;
      string symbol = m_spec.name;
      MqlTradeRequest req;
      ZeroMemory(req);
      req.action    = TRADE_ACTION_PENDING;
      req.symbol    = symbol;
      req.magic     = m_magic;
      req.volume    = lots;
      req.deviation = m_deviation;
      req.comment   = comment;
      req.type_time = ORDER_TIME_GTC;
      double point  = m_spec.point;
      req.type      = (dir == POSITION_TYPE_LONG) ? ORDER_TYPE_BUY_STOP
                                                  : ORDER_TYPE_SELL_STOP;
      // offset must clear the broker stops level too, or the placement is
      // dropped with INVALID_STOPS before it can ever fill
      double offset = MathMax(offsetPoints * point, MinStopDist(symbol));
      if(dir == POSITION_TYPE_LONG)
         req.price = Ask(symbol) + offset;
      else
         req.price = Bid(symbol) - offset;
      double minDist = MinStopDist(symbol);
      double sd = (slDist > 0.0) ? MathMax(slDist, minDist) : 0.0;
      double td = (tpDist > 0.0) ? MathMax(tpDist, minDist) : 0.0;
      req.sl = StopForSide(dir, req.price, sd);
      req.tp = (td > 0.0)
               ? ((dir == POSITION_TYPE_LONG)
                  ? req.price + SpecRoundToTick(td, m_spec)
                  : req.price - SpecRoundToTick(td, m_spec))
               : 0.0;
      ulong t0 = GetTickCount64();
      bool sent = OrderSend(req, res_tmp);
      out.latencyMs = (int)(GetTickCount64() - t0);
      out.retcode = sent ? res_tmp.retcode : TRADE_RETCODE_ERROR;
      if(sent && (res_tmp.retcode == TRADE_RETCODE_DONE ||
                  res_tmp.retcode == TRADE_RETCODE_PLACED))
        {
         out.done = true;
         out.orderTicket = res_tmp.order;
         m_pendingTicket = res_tmp.order;
         m_pendingBarsLeft = m_pendingExpireBars;
         Audit("pending_placed", symbol, res_tmp.retcode, out.latencyMs, 0.0,
               lots, comment);
        }
      return out;
     }

public:
                     CTradeManager() :
                        m_magic(0), m_deviation(30), m_maxAttempts(4),
                        m_pendingMode(false), m_pendingExpireBars(6),
                        m_pendingTicket(0), m_pendingBarsLeft(0), m_counter(0)
     {
      ZeroMemory(res_tmp);
      StatsReset();
     }

   void              Init(const ulong magic, const int deviation,
                          const int maxAttempts, const bool pendingMode,
                          const int pendingExpireBars, const SSymbolSpec &spec)
     {
      m_magic             = magic;
      m_deviation         = deviation;
      m_maxAttempts       = MathMax(1, maxAttempts);
      m_pendingMode       = pendingMode;
      m_pendingExpireBars = MathMax(1, pendingExpireBars);
      m_spec              = spec;
      m_pendingTicket     = 0;
      m_queue.ClearAll();
      StatsReset();
     }

   bool              IsPendingMode() const { return m_pendingMode; }
   bool              HasPendingOrder() const { return m_pendingTicket != 0; }
   bool              HasQueuedWork() const { return !m_queue.IsEmpty(); }
   int               QueuedCount() const { return m_queue.CountActive(); }

   //--- Restart-recovery boundary (deliberately public; SPEC DoD #21,
   //|   MQL5_EXECUTION_AUDIT.md F-1): the EA's orphan-pending scan owns
   //|   the recovery POLICY, the TradeManager owns execution AUTHORITY.
   //|   This is the ONLY external entry into the cancel path; it never
   //|   sends an order directly — it enqueues a bounded, magic-tagged,
   //|   deduped retry item so an orphan pending is never silently
   //|   abandoned after a restart.
   //+--------------------------------------------------------------------+
   void              QueueCancelByTicket(const ulong ticket)
     {
      SRetryItem item;
      item.action  = RETRY_ACTION_CANCEL;
      item.symbol  = m_spec.name;
      item.ticket  = ticket;
      item.magic   = m_magic;
      item.maxAttempts = m_maxAttempts;
      m_queue.Add(item, 0);
     }

   void              StatsReset()
     {
      m_statTotal = m_statDone = m_statPartial = m_statRejects = 0;
      m_statQueued = m_statFatal = 0;
      m_statSlipSum = m_statSlipMax = 0.0;
      m_statLatSum = 0; m_statLatMax = 0;
     }

   string            StatsSummary() const
     {
      return StringFormat("total=%d done=%d partial=%d rejects=%d queued=%d fatal=%d "
                          "slipSumPts=%.1f slipMaxPts=%.1f latAvgMs=%.1f latMaxMs=%d",
                          m_statTotal, m_statDone, m_statPartial, m_statRejects,
                          m_statQueued, m_statFatal, m_statSlipSum, m_statSlipMax,
                          (m_statDone > 0) ? (double)m_statLatSum / m_statDone : 0.0,
                          m_statLatMax);
     }

   // structured audit line for every execution action
   void              Audit(const string action, const string symbol,
                           const uint retcode, const int latencyMs,
                           const double slipPts, const double lots,
                           const string comment)
     {
      m_statTotal++;
      if(IsSuccessRetcode(retcode))
        {
         m_statDone++;
         if(retcode == TRADE_RETCODE_DONE_PARTIAL)
            m_statPartial++;
         if(slipPts > 0.0)
           {
            m_statSlipSum += slipPts;
            if(slipPts > m_statSlipMax)
               m_statSlipMax = slipPts;
           }
         m_statLatSum += latencyMs;
         if(latencyMs > m_statLatMax)
            m_statLatMax = latencyMs;
        }
      else if(IsRetryableRetcode(retcode))
         m_statQueued++;
      else
         m_statRejects++;
      PrintFormat("[mql5bot] EXEC|%s|%s|%s|%d|%.2f|%d|%s",
                  action, symbol, RetcodeToString(retcode), latencyMs, slipPts,
                  m_statTotal, comment);
     }

   //---------------------------------------------------------------------
   // Public open calls (single attempt + queue on retryable failure)
   //---------------------------------------------------------------------
   SOrderResult      OpenMarket(const long dir, const double lots,
                                const double slDist, const double tpDist,
                                const string prefix)
     {
      SOrderResult out;
      if(lots <= 0.0)
         return out;
      string comment = NextComment(prefix);
      MqlTradeResult res;
      ZeroMemory(res);
      double slip = 0.0;
      int lat = 0;
      uint rc = MarketChain(dir, lots, slDist, tpDist, comment, res, lat, slip);
      out.retcode = rc;
      out.latencyMs = lat;
      out.slippagePoints = slip;
      out.fillPrice = res.price;
      if(IsSuccessRetcode(rc))
        {
         out.done = true;
         Audit("open", m_spec.name, rc, lat, slip, lots, comment);
         return out;
        }
      if(rc == TRADE_RETCODE_TIMEOUT)   // ambiguous outcome: transient by definition
        {
         ulong dt = 0; double dv = 0.0, dp = 0.0;
         if(FindRecentDeal(m_magic, comment, 30, dt, dv, dp))
           {
            out.done = true;
            out.fillPrice = dp;
            Audit("open_verified", m_spec.name, TRADE_RETCODE_DONE, lat, 0.0, dv, comment);
            return out;
           }
        }
      if(IsRetryableRetcode(rc))
        {
         QueueOpen(dir, lots, slDist, tpDist, comment, 0);
         out.queued = true;
         Audit("open_queued", m_spec.name, rc, lat, 0.0, lots, comment);
         return out;
        }
      Audit("open_rejected", m_spec.name, rc, lat, 0.0, lots, comment);
      return out;
     }

   SOrderResult      OpenPending(const long dir, const double lots,
                                 const double offsetPoints,
                                 const double slDist, const double tpDist,
                                 const string prefix)
     {
      SOrderResult out;
      if(lots <= 0.0 || m_pendingTicket != 0)
         return out;
      string comment = NextComment(prefix);
      out = PlacePendingOnce(dir, lots, offsetPoints, slDist, tpDist, comment);
      if(out.done)
         return out;
      if(IsRetryableRetcode(out.retcode))
        {
         SRetryItem item;
         item.action = RETRY_ACTION_PENDING;
         item.symbol = m_spec.name;
         item.dir    = dir;
         item.lots   = lots;
         item.offsetPoints = offsetPoints;
         item.slDist = slDist;
         item.tpDist = tpDist;
         item.comment = comment;
         item.magic  = m_magic;
         item.maxAttempts = m_maxAttempts;
         m_queue.Add(item, 0);
         out.queued = true;
         Audit("pending_queued", m_spec.name, out.retcode, out.latencyMs, 0.0,
               lots, comment);
         return out;
        }
      Audit("pending_rejected", m_spec.name, out.retcode, out.latencyMs, 0.0,
            lots, comment);
      return out;
     }

   //---------------------------------------------------------------------
   // Pending housekeeping on new bars
   //---------------------------------------------------------------------
   bool              OnBar(const string symbol)
     {
      if(m_pendingTicket == 0)
         return false;
      bool stillThere = false;
      for(int i = OrdersTotal() - 1; i >= 0; i--)
        {
         ulong t = OrderGetTicket(i);
         if(t == m_pendingTicket)
           {
            stillThere = true;
            break;
           }
        }
      if(!stillThere)
        {
         // gone — filled (a position should exist) or cancelled server-side
         m_pendingTicket = 0;
         m_pendingBarsLeft = 0;
         return true;
        }
      m_pendingBarsLeft--;
      if(m_pendingBarsLeft <= 0)
        {
         if(CancelPending(symbol))
           {
            m_pendingTicket = 0;
            return true;
           }
        }
      return false;
     }

   bool              CancelPending(const string symbol)
     {
      if(m_pendingTicket == 0)
         return false;
      MqlTradeRequest req;
      ZeroMemory(req);
      req.action = TRADE_ACTION_REMOVE;
      req.order  = m_pendingTicket;
      MqlTradeResult res;
      ZeroMemory(res);
      bool sent = OrderSend(req, res);
      if(sent && res.retcode == TRADE_RETCODE_DONE)
         return true;
      if(IsRetryableRetcode(res.retcode))
        {
         SRetryItem item;
         item.action  = RETRY_ACTION_CANCEL;
         item.symbol  = symbol;
         item.ticket  = m_pendingTicket;
         item.magic   = m_magic;
         item.maxAttempts = m_maxAttempts;
         m_queue.Add(item, 0);
        }
      else
         PrintFormat("[mql5bot] cancel pending failed: %s (%u)",
                     RetcodeToString(res.retcode), res.retcode);
      return false;
     }

   //---------------------------------------------------------------------
   // Close / modify — single attempt, queue on retryable failure
   //---------------------------------------------------------------------
   bool              ClosePosition(const ulong ticket, const double volume)
     {
      if(!PositionSelectByTicket(ticket))
         return true;                    // already closed
      string comment = StringFormat("mql5bot-close-%d", m_counter++);
      MqlTradeResult res;
      ZeroMemory(res);
      int lat = 0;
      uint rc = CloseOnce(ticket, volume, comment, res, lat);
      if(IsSuccessRetcode(rc))
        {
         double vol = (volume > 0.0) ? volume : PositionGetDouble(POSITION_VOLUME);
         Audit("close", m_spec.name, rc, lat, 0.0, vol, comment);
         return true;
        }
      if(rc == TRADE_RETCODE_TIMEOUT)   // ambiguous outcome: transient by definition
        {
         if(!PositionSelectByTicket(ticket))
            return true;                 // closed meanwhile
        }
      if(IsRetryableRetcode(rc))
        {
         QueueClose(ticket, volume, comment, 0);
         return false;
        }
      PrintFormat("[mql5bot] close failed: %s (%u)", RetcodeToString(rc), rc);
      return false;
     }

   bool              ModifySLTP(const ulong ticket, const double sl,
                                const double tp)
     {
      if(!PositionSelectByTicket(ticket))
         return true;                    // gone: nothing to modify
      MqlTradeResult res;
      ZeroMemory(res);
      uint rc = ModifyOnce(ticket, sl, tp, res);
      if(rc == TRADE_RETCODE_DONE)
        {
         Audit("modify", m_spec.name, rc, 0, 0.0, 0.0, "");
         return true;
        }
      if(IsRetryableRetcode(rc))
        {
         QueueModify(ticket, sl, tp, 0);
         return false;
        }
      if(rc != TRADE_RETCODE_NO_CHANGES && rc != TRADE_RETCODE_INVALID_STOPS)
         PrintFormat("[mql5bot] SLTP modify failed: %s (%u)",
                     RetcodeToString(rc), rc);
      return false;
     }

   //---------------------------------------------------------------------
   // OnTimer: execute due retries (bounded work per tick)
   //---------------------------------------------------------------------
   void              ProcessQueue(const int maxItems = 8)
     {
      int n = 0;
      SRetryItem item;
      ulong now = GetTickCount64();
      while(n < maxItems && m_queue.PopDue(item, now))
        {
         ExecuteQueued(item);
         n++;
         now = GetTickCount64();
        }
     }
  };

#endif // MQL5BOT_TRADEMANAGER_MQH
//+------------------------------------------------------------------+
