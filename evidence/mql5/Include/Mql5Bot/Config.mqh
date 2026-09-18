//+------------------------------------------------------------------+
//|                                            Mql5Bot/Config.mqh    |
//|        Shared types, enums and constants for the mql5bot EA      |
//+------------------------------------------------------------------+
#property copyright "mql5bot contributors"
// NOTE: MQL5 Market metadata format (xxx.yyy) — this is EA METADATA,
// a separate version plane from the repository/package release
// version "1.0.0" and from MQL5BOT_VERSION below (docs/DECISIONS.md).
#property version   "1.00"

#ifndef MQL5BOT_CONFIG_MQH
#define MQL5BOT_CONFIG_MQH

//--- Bot version ---------------------------------------------------+
#define MQL5BOT_VERSION      "1.0.0"
#define MQL5BOT_NAME         "mql5bot"
#define MQL5BOT_WEBENDPOINT  "https://httpbin.org/post"

//--- Position-direction vocabulary mapping ---------------------------+
//| AEGIS project terminology is LONG/SHORT; the MQL5 language only   |
//| defines ENUM_POSITION_TYPE = {POSITION_TYPE_BUY, POSITION_TYPE_   |
//| SELL} (official MQL5 reference, Position Properties). These       |
//| defines are the single explicit mapping between the two; they     |
//| preserve the project vocabulary at every call site.               |
//|                                                                   |
//| Four DISTINCT direction concepts — never conflated:               |
//|   signal direction    int  -1 / 0 / +1      (SBotSignal.direction)|
//|   position direction  ENUM_POSITION_TYPE    (these defines)       |
//|   order direction     ENUM_ORDER_TYPE       (ORDER_TYPE_BUY/SELL) |
//|   deal direction      ENUM_DEAL_TYPE        (history only)        |
//+-------------------------------------------------------------------+
#define POSITION_TYPE_LONG   POSITION_TYPE_BUY
#define POSITION_TYPE_SHORT  POSITION_TYPE_SELL

//--- Strategy selection --------------------------------------------+
enum ENUM_MQL5BOT_STRATEGY
  {
   STRAT_EMA_CROSSOVER       = 0, // EMA crossover
   STRAT_RSI_REVERSAL        = 1, // RSI reversal
   STRAT_DONCHIAN_BREAKOUT   = 2, // Donchian breakout
   STRAT_BOLLINGER_REVERSAL  = 3, // Bollinger reversal
   STRAT_MACD_MOMENTUM       = 4  // MACD momentum
  };

//--- Entry execution style ------------------------------------------+
enum ENUM_MQL5BOT_ENTRY_MODE
  {
   ENTRY_MARKET  = 0, // market orders
   ENTRY_PENDING = 1  // pending stop orders
  };

//--- Session day-of-week bitmask (MQL5: 0=Sunday .. 6=Saturday) ------+
#define SESSION_SUNDAY     0x01
#define SESSION_MONDAY     0x02
#define SESSION_TUESDAY    0x04
#define SESSION_WEDNESDAY  0x08
#define SESSION_THURSDAY   0x10
#define SESSION_FRIDAY     0x20
#define SESSION_SATURDAY   0x40
#define SESSION_WEEKDAYS   0x3E

//--- Strategy parameters shared by SignalEngine and strategies ------+
struct SBotParams
  {
   int      fastEma;
   int      slowEma;
   int      rsiPeriod;
   double   rsiOversold;
   double   rsiOverbought;
   int      donchianPeriod;
   int      bollingerPeriod;
   double   bollingerDev;
   int      macdFast;
   int      macdSlow;
   int      macdSignal;
   double   slAtr;              // stop-loss distance in ATR multiples
   double   tpAtr;              // take-profit distance in ATR multiples
  };

//--- One evaluation of the active strategy --------------------------+
struct SBotSignal
  {
   int      direction;          // -1 sell, 0 flat, +1 buy
   double   slPrice;            // absolute stop-loss (0 = unset)
   double   tpPrice;            // absolute take-profit (0 = unset)
   bool     valid;
  };

//--- Normalised volume helper ----------------------------------------+
double NormalizeLots(double lots, double step, double minLots, double maxLots)
  {
   if(step <= 0.0)
      step = 0.01;
   double steps = MathRound(lots / step);
   double norm  = steps * step;
   if(norm < minLots)
      norm = minLots;
   if(norm > maxLots)
      norm = maxLots;
   return norm;
  }

//--- Retryable trade server return codes -----------------------------+
//| Transient server conditions only — one explicit real MQL5 code    |
//| per AEGIS retry class (SPEC §8.D; official values per the MQL5    |
//| reference "Trade Operation Result Codes"):                        |
//|   REQUOTE       10004  broker offers a new price -> reprice+retry |
//|   PRICE_CHANGED 10020  price moved during processing -> retry     |
//|   PRICE_OFF     10021  "there are no quotes to process the        |
//|                        request" -> wait for quotes, retry          |
//|   TIMEOUT       10012  server response timeout -> retry           |
//| Codes that DO NOT EXIST in MQL5 and were removed at the first     |
//| real compile (docs/DECISIONS.md): TRADE_RETCODE_RETRY (real 10006 |
//| is REJECT — a refusal, never retryable) and TRADE_RETCODE_NO_     |
//| QUOTES (real 10018 is MARKET_CLOSED — the no-quotes condition is  |
//| PRICE_OFF). Rejects, market-closed, invalid volume/price/stops,   |
//| no-money, invalid-fill etc. stay FATAL: fail-safe = never retry   |
//| blindly what we do not understand.                                |
//+--------------------------------------------------------------------+
bool IsRetryableRetcode(uint retcode)
  {
   switch(retcode)
     {
      case TRADE_RETCODE_REQUOTE:       // 10004
      case TRADE_RETCODE_PRICE_CHANGED: // 10020
      case TRADE_RETCODE_PRICE_OFF:     // 10021
      case TRADE_RETCODE_TIMEOUT:       // 10012
         return true;
     }
   return false;
  }

//--- Engine fail-safe state machine (SPEC §3.5, §8.C) -------------------+
enum ENUM_ENGINE_STATE
  {
   ENGINE_NORMAL        = 0, // trading allowed (within limits)
   ENGINE_NO_NEW_TRADES = 1, // manage open positions only
   ENGINE_HALT          = 2  // close everything and stay down
  };

//--- Retcode classification (SPEC §8.D) ----------------------------------+
bool IsSuccessRetcode(uint retcode)
  {
   return (retcode == TRADE_RETCODE_DONE ||
           retcode == TRADE_RETCODE_DONE_PARTIAL ||
           retcode == TRADE_RETCODE_PLACED);
  }

// Fatal = neither success nor retryable. Unknown codes default to fatal:
// never retry blindly what we do not understand (fail-safe principle).
bool IsFatalRetcode(uint retcode)
  {
   return (!IsSuccessRetcode(retcode) && !IsRetryableRetcode(retcode) &&
           retcode != TRADE_RETCODE_REQUOTE);
  }

//--- Human readable retcode (subset) ----------------------------------+
string RetcodeToString(uint retcode)
  {
   switch(retcode)
     {
      case TRADE_RETCODE_DONE:            return "DONE";
      case TRADE_RETCODE_DONE_PARTIAL:    return "DONE_PARTIAL";
      case TRADE_RETCODE_PLACED:          return "PLACED";
      case TRADE_RETCODE_INVALID_VOLUME:  return "INVALID_VOLUME";
      case TRADE_RETCODE_INVALID_PRICE:   return "INVALID_PRICE";
      case TRADE_RETCODE_INVALID_STOPS:   return "INVALID_STOPS";
      case TRADE_RETCODE_MARKET_CLOSED:   return "MARKET_CLOSED";
      case TRADE_RETCODE_NO_MONEY:        return "NO_MONEY";
      case TRADE_RETCODE_PRICE_CHANGED:   return "PRICE_CHANGED";
      case TRADE_RETCODE_PRICE_OFF:       return "PRICE_OFF";
      case TRADE_RETCODE_REQUOTE:         return "REQUOTE";
      case TRADE_RETCODE_TIMEOUT:         return "TIMEOUT";
      case TRADE_RETCODE_INVALID_FILL:    return "INVALID_FILL";
      case TRADE_RETCODE_TOO_MANY_REQUESTS: return "TOO_MANY_REQUESTS";
      default:                            return "UNKNOWN";
     }
  }

#endif // MQL5BOT_CONFIG_MQH
//+------------------------------------------------------------------+
