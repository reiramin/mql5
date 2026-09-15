//+------------------------------------------------------------------+
//|                                        Mql5Bot/RetryQueue.mqh    |
//| Sleep-free retry engine (SPEC §3.4, §8.A):                       |
//|                                                                  |
//| Retryable trade-server failures are enqueued here and processed  |
//| by OnTimer with exponential backoff, refreshed prices and a hard |
//| attempt cap. There are NO blocking retry loops anywhere in the   |
//| trade path. The only immediate re-send permitted is a single     |
//| REQUOTE retry with refreshed prices (handled by the caller).     |
//|                                                                  |
//| Bounded work per poll: ProcessDue() honours maxItems so one      |
//| timer tick can never spin unboundedly.                           |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_RETRYQUEUE_MQH
#define MQL5BOT_RETRYQUEUE_MQH

#include <Mql5Bot/Config.mqh>

#define RETRY_MAX_ITEMS     32
#define RETRY_DEFAULT_ATTEMPTS 4
#define RETRY_BACKOFF_MS    500.0    // attempt 0 -> ~0.5 s (next timer tick)
#define RETRY_BACKOFF_CAP_MS 10000.0 // never wait longer than 10 s

enum ENUM_RETRY_ACTION
  {
   RETRY_ACTION_NONE    = 0,
   RETRY_ACTION_MARKET  = 1,  // market order (fresh ask/bid)
   RETRY_ACTION_PENDING = 2,  // pending stop order
   RETRY_ACTION_CLOSE   = 3,  // close (full or partial volume)
   RETRY_ACTION_MODIFY  = 4,  // SL/TP modify
   RETRY_ACTION_CANCEL  = 5   // remove a pending order
  };

struct SRetryItem
  {
   int               action;       // ENUM_RETRY_ACTION
   string            symbol;
   long              dir;          // POSITION_TYPE_BUY/SELL for open/close
   double            lots;
   double            slDist;       // distance from entry price
   double            tpDist;
   double            offsetPoints; // pending offset
   double            sl;           // absolute prices for modify
   double            tp;
   string            comment;
   ulong             ticket;       // position ticket (close/modify) or 0
   ulong             magic;
   int               attempt;      // completed attempts so far
   int               maxAttempts;
   ulong             dueMs;        // GetTickCount64() threshold
   bool              active;

                     SRetryItem()
     {
      Reset();
     }
   void              Reset()
     {
      action = RETRY_ACTION_NONE;
      symbol = "";
      dir = 0;
      lots = 0.0;
      slDist = 0.0;
      tpDist = 0.0;
      offsetPoints = 0.0;
      sl = 0.0;
      tp = 0.0;
      comment = "";
      ticket = 0;
      magic = 0;
      attempt = 0;
      maxAttempts = RETRY_DEFAULT_ATTEMPTS;
      dueMs = 0;
      active = false;
     }
  };

// Pure backoff schedule: attempts 0,1,2,... -> 0.5 s, 1 s, 2 s ... capped.
ulong RetryBackoffMs(const int attempt)
  {
   double ms = RETRY_BACKOFF_MS * MathPow(2.0, MathMax(0, attempt));
   if(ms > RETRY_BACKOFF_CAP_MS)
      ms = RETRY_BACKOFF_CAP_MS;
   return (ulong)ms;
  }

class CRetryQueue
  {
private:
   SRetryItem        m_items[RETRY_MAX_ITEMS];

   int               FindSlot() const
     {
      for(int i = 0; i < RETRY_MAX_ITEMS; i++)
         if(!m_items[i].active)
            return i;
      return -1;
     }

   // same logical operation already queued? (action+symbol+ticket+comment)
   int               FindSame(const SRetryItem &item) const
     {
      for(int i = 0; i < RETRY_MAX_ITEMS; i++)
        {
         if(!m_items[i].active)
            continue;
         if(m_items[i].action == item.action &&
            m_items[i].symbol == item.symbol &&
            m_items[i].ticket == item.ticket &&
            m_items[i].comment == item.comment)
            return i;
        }
      return -1;
     }

public:
                     CRetryQueue()
     {
      for(int i = 0; i < RETRY_MAX_ITEMS; i++)
         m_items[i].Reset();
     }

   int               CountActive() const
     {
      int n = 0;
      for(int i = 0; i < RETRY_MAX_ITEMS; i++)
         if(m_items[i].active)
            n++;
      return n;
     }

   bool              IsEmpty() const { return CountActive() == 0; }

   // Enqueue (or refresh an existing identical entry, keeping its attempt
   // counter so a re-request never resets the cap). Schedule = now + backoff.
   bool              Add(const SRetryItem &item, const int attempted)
     {
      int same = FindSame(item);
      if(same >= 0)
        {
         m_items[same].attempt = attempted;
         m_items[same].dueMs   = GetTickCount64() +
                                 RetryBackoffMs(m_items[same].attempt);
         return true;
        }
      int slot = FindSlot();
      if(slot < 0)
        {
         Print("[mql5bot] RetryQueue full — dropping retry (failsafe: no resend)");
         return false;
        }
      m_items[slot] = item;
      m_items[slot].attempt = attempted;
      m_items[slot].active  = true;
      m_items[slot].dueMs   = GetTickCount64() + RetryBackoffMs(attempted);
      return true;
     }

   // Remove and return the next due item (earliest due first). Returns
   // false when nothing is due.
   bool              PopDue(SRetryItem &out, const ulong nowMs)
     {
      int best = -1;
      for(int i = 0; i < RETRY_MAX_ITEMS; i++)
        {
         if(!m_items[i].active)
            continue;
         if(m_items[i].dueMs > nowMs)
            continue;
         if(best < 0 || m_items[i].dueMs < m_items[best].dueMs)
            best = i;
        }
      if(best < 0)
         return false;
      out = m_items[best];
      m_items[best].active = false;
      return true;
     }

   void              ClearAll()
     {
      for(int i = 0; i < RETRY_MAX_ITEMS; i++)
         m_items[i].Reset();
     }
  };

#endif // MQL5BOT_RETRYQUEUE_MQH
//+------------------------------------------------------------------+
