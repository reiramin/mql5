//+------------------------------------------------------------------+
//|                                      Mql5Bot/SymbolSpec.mqh      |
//| Canonical broker symbol specification + pure normalisers.        |
//|                                                                  |
//| SPEC §3.3/§3.10: every broker fact is queried at runtime into a  |
//| single injectable SSymbolSpec; ALL risk/execution math consumes  |
//| the struct (never scattered SymbolInfo* calls), so the same      |
//| arithmetic is unit-testable with synthetic specs and stays       |
//| byte-parallel to the canonical Python model                      |
//| (python/mql5bot/symbolspec.py — the MQL5 port target).           |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_SYMBOLSPEC_MQH
#define MQL5BOT_SYMBOLSPEC_MQH

#include <Mql5Bot/Config.mqh>

//+------------------------------------------------------------------+
//| Broker specification snapshot                                    |
//+------------------------------------------------------------------+
struct SSymbolSpec
  {
   string            name;                 // SYMBOL
   int               digits;               // SYMBOL_DIGITS
   double            point;                // SYMBOL_POINT
   double            tickSize;             // SYMBOL_TRADE_TICK_SIZE (price step)
   double            tickValueProfit;      // SYMBOL_TRADE_TICK_VALUE_PROFIT (account/deposit ccy, per 1.0 lot)
   double            tickValueLoss;        // SYMBOL_TRADE_TICK_VALUE_LOSS   (account/deposit ccy, per 1.0 lot)
   double            contractSize;         // SYMBOL_TRADE_CONTRACT_SIZE
   double            volumeMin;            // SYMBOL_VOLUME_MIN
   double            volumeMax;            // SYMBOL_VOLUME_MAX
   double            volumeStep;           // SYMBOL_VOLUME_STEP
   double            volumeLimit;          // SYMBOL_VOLUME_LIMIT (0 = none)
   double            stopsLevelPoints;     // SYMBOL_TRADE_STOPS_LEVEL (in points)
   double            freezeLevelPoints;    // SYMBOL_TRADE_FREEZE_LEVEL (in points)
   long              fillingMode;          // SYMBOL_FILLING_MODE bitmask
   long              executionMode;        // SYMBOL_TRADE_EXEMODE (FILL-MODE-1)
   long              orderMode;            // SYMBOL_ORDER_MODE bitmask
   long              tradeMode;            // SYMBOL_TRADE_MODE
   long              expirationMode;       // SYMBOL_EXPIRATION_MODE bitmask
   long              accountMarginMode;    // ACCOUNT_MARGIN_MODE
   string            currencyProfit;       // SYMBOL_CURRENCY_PROFIT
   string            currencyDeposit;      // account deposit currency
   string            reason;               // last build/validation failure

                     SSymbolSpec()
     {
      name             = "";
      digits           = 0;
      point            = 0.0;
      tickSize         = 0.0;
      tickValueProfit  = 0.0;
      tickValueLoss    = 0.0;
      contractSize     = 0.0;
      volumeMin        = 0.0;
      volumeMax        = 0.0;
      volumeStep       = 0.0;
      volumeLimit      = 0.0;
      stopsLevelPoints = 0.0;
      freezeLevelPoints= 0.0;
      fillingMode      = 0;
      executionMode    = 0;
      orderMode        = 0;
      tradeMode        = 0;
      expirationMode   = 0;
      accountMarginMode= 0;
      currencyProfit   = "";
      currencyDeposit  = "";
      reason           = "";
     }
  };

//+------------------------------------------------------------------+
//| Runtime builder — never assume, always query (SPEC §3.3)         |
//+------------------------------------------------------------------+
bool BuildSymbolSpec(const string symbol, SSymbolSpec &out)
  {
   out.name = symbol;
   out.digits            = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   out.point             = SymbolInfoDouble(symbol, SYMBOL_POINT);
   out.tickSize          = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   out.tickValueProfit   = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   out.tickValueLoss     = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   out.contractSize      = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   out.volumeMin         = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   out.volumeMax         = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   out.volumeStep        = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   out.volumeLimit       = SymbolInfoDouble(symbol, SYMBOL_VOLUME_LIMIT);
   out.stopsLevelPoints  = (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   out.freezeLevelPoints = (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   out.fillingMode       = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   out.executionMode     = SymbolInfoInteger(symbol, SYMBOL_TRADE_EXEMODE);
   out.orderMode         = SymbolInfoInteger(symbol, SYMBOL_ORDER_MODE);
   out.tradeMode         = SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   out.expirationMode    = SymbolInfoInteger(symbol, SYMBOL_EXPIRATION_MODE);
   out.accountMarginMode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   out.currencyProfit    = SymbolInfoString(symbol, SYMBOL_CURRENCY_PROFIT);
   out.currencyDeposit   = AccountInfoString(ACCOUNT_CURRENCY);

   if(out.digits < 0)                { out.reason = "invalid digits";                 return false; }
   if(out.point <= 0.0)              { out.reason = "point <= 0";                     return false; }
   if(out.tickSize <= 0.0)           { out.reason = "tick_size <= 0";                 return false; }
   if(out.tickValueLoss <= 0.0)      { out.reason = "tick_value_loss <= 0";           return false; }
   if(out.tickValueProfit <= 0.0)    { out.reason = "tick_value_profit <= 0";         return false; }
   if(out.contractSize <= 0.0)       { out.reason = "contract_size <= 0";             return false; }
   if(out.volumeMin <= 0.0)          { out.reason = "volume_min <= 0";                return false; }
   if(out.volumeMax < out.volumeMin) { out.reason = "volume_max < volume_min";        return false; }
   if(out.volumeStep <= 0.0)         { out.reason = "volume_step <= 0";               return false; }
   if(out.currencyProfit == "" || out.currencyDeposit == "")
     { out.reason = "missing currency info";                                           return false; }
   out.reason = "";
   return true;
  }

//+------------------------------------------------------------------+
//| SPEC-WAIT-1 (owner decision 2026-10-12, CLAUDE.md exception 1.d): |
//| a live start on a symbol the terminal has not synchronized yet    |
//| (gate_run56: "symbol spec build failed: tick_value_loss <= 0"     |
//| while the broker connection was lost) waits in WAITING_SYMBOL     |
//| instead of failing init. Never in the Strategy Tester.            |
//+------------------------------------------------------------------+
#define SPEC_WAIT_READY   0
#define SPEC_WAIT_WAIT    1
#define SPEC_WAIT_GIVE_UP 2

// The build failures a not-yet-synchronized symbol produces.
bool SpecReasonIsUnsynced(const string reason)
  {
   if(reason == "point <= 0")
      return true;
   if(reason == "tick_size <= 0")
      return true;
   if(reason == "tick_value_loss <= 0")
      return true;
   if(reason == "tick_value_profit <= 0")
      return true;
   if(reason == "contract_size <= 0")
      return true;
   return false;
  }

// May a failed spec build wait for the symbol? Never in the tester.
bool SpecMayWait(const bool in_tester, const bool synchronized, const string reason)
  {
   if(in_tester)
      return false;
   if(!synchronized)
      return true;
   return SpecReasonIsUnsynced(reason);
  }

// One WAITING_SYMBOL step: ready, keep waiting, or give up (bounded).
int SpecWaitDecision(const bool built, const bool waitable, const int waited_s, const int limit_s)
  {
   if(built)
      return SPEC_WAIT_READY;
   if(!waitable)
      return SPEC_WAIT_GIVE_UP;
   if(waited_s >= limit_s)
      return SPEC_WAIT_GIVE_UP;
   return SPEC_WAIT_WAIT;
  }

//+------------------------------------------------------------------+
//| Pure normalisers (match python/mql5bot/symbolspec.py semantics)  |
//+------------------------------------------------------------------+

// Round a price onto the tick grid. Tick size, NOT digits: index/crypto
// CFDs can have a tick that is a multiple of the printed point.
double SpecRoundToTick(const double price, const SSymbolSpec &spec)
  {
   if(spec.tickSize <= 0.0)
      return 0.0;
   return MathRound(price / spec.tickSize) * spec.tickSize;
  }

// Whole ticks inside a distance (>=1 for any positive distance).
int SpecTicksOf(const double distance, const SSymbolSpec &spec)
  {
   if(spec.tickSize <= 0.0)
      return 0;
   if(distance <= 0.0)
      return 0;
   int ticks = (int)MathRound(distance / spec.tickSize);
   return (ticks >= 1) ? ticks : 1;
  }

double SpecMinStopDistance(const SSymbolSpec &spec)
  {
   return spec.stopsLevelPoints * spec.point;
  }

// Grow a stop distance so the broker stops level is satisfied and the
// result stays on the tick grid. Never shrinks a requested distance.
double SpecEnforceMinStop(const double distance, const SSymbolSpec &spec)
  {
   double d = distance;
   double minDist = SpecMinStopDistance(spec);
   if(d < minDist)
      d = minDist;
   return SpecRoundToTick(d, spec);
  }

// Normalise volume to the broker grid: FLOOR to the step (never round up —
// that would exceed the risk budget), then clamp into
// [volume_min, volume_max] and volume_limit when set. Returns 0.0 for
// non-positive input; returns volume_min only when the input is >= min
// (the caller decides whether forcing the minimum is acceptable).
double SpecNormalizeVolume(const double lots, const SSymbolSpec &spec)
  {
   if(spec.volumeStep <= 0.0 || spec.volumeMin <= 0.0)
      return 0.0;
   if(lots <= 0.0)
      return 0.0;
   double step  = spec.volumeStep;
   double floor = MathFloor(lots / step + 1e-9) * step;
   if(floor < spec.volumeMin)
      return spec.volumeMin;
   double cap = spec.volumeMax;
   if(spec.volumeLimit > 0.0 && spec.volumeLimit < cap)
      cap = spec.volumeLimit;
   if(floor > cap)
     {
      floor = MathFloor(cap / step + 1e-9) * step;
      if(floor < spec.volumeMin)
         return 0.0;                  // cap below minimum: nothing tradable
     }
   return floor;
  }

// Stop-loss loss per 1.0 lot in the ACCOUNT/DEPOSIT currency:
//   ticks(stopDistance) * tick_value_loss
// SYMBOL_TRADE_TICK_VALUE_LOSS is denominated by the terminal in the
// account/deposit currency (owner-verified for EURUSD/US30/XAUEUR in
// artifacts/owner_mt5_gate/broker_parity.json; BTC unverified). NO
// profit->deposit FX factor is applied and NO FX rate is ever derived
// from tick_value (P0-1, DECISIONS.md 2026-09-18). The runtime risk
// path (RiskManager.GetLots) additionally reconciles this against an
// independent OrderCalcProfit witness before sizing.
double SpecLossPerLot(const double stopDistance, const SSymbolSpec &spec)
  {
   if(spec.tickValueLoss <= 0.0)
      return 0.0;
   if(stopDistance <= 0.0)
      return 0.0;
   return (double)SpecTicksOf(stopDistance, spec) * spec.tickValueLoss;
  }

// Is this filling mode allowed for the symbol (SPEC §8.D; FILL-MODE-1)?
// ENUM_ORDER_TYPE_FILLING is an index (FOK 0, IOC 1, RETURN 2), while
// SYMBOL_FILLING_MODE is a flag mask (SYMBOL_FILLING_FOK 1, SYMBOL_FILLING_IOC
// 2): each order mode is tested against ITS flag, never the index as a bit.
// RETURN has no flag; the MQL5 reference enables it in every execution mode
// except Market execution (SYMBOL_TRADE_EXECUTION_MARKET).
// Kept one `if` + one `return` per line: tests/test_fill_mode.py executes
// these three functions from this source.
bool SpecIsFillingAllowed(const SSymbolSpec &spec, const ENUM_ORDER_TYPE_FILLING filling)
  {
   if(filling == ORDER_FILLING_FOK)
      return (spec.fillingMode & SYMBOL_FILLING_FOK) != 0;
   if(filling == ORDER_FILLING_IOC)
      return (spec.fillingMode & SYMBOL_FILLING_IOC) != 0;
   if(filling == ORDER_FILLING_RETURN)
      return spec.executionMode != (long)SYMBOL_TRADE_EXECUTION_MARKET;
   return false;
  }

// Is this order type allowed by the symbol's order-mode mask?
bool SpecIsOrderAllowed(const SSymbolSpec &spec, const ENUM_ORDER_TYPE type)
  {
   return (spec.orderMode & (long)type) != 0;
  }

// Preferred filling mode for market/limit execution: FOK -> IOC -> RETURN,
// first one the symbol allows. Returns -1 when none is allowed.
ENUM_ORDER_TYPE_FILLING SpecPreferredFilling(const SSymbolSpec &spec)
  {
   if(SpecIsFillingAllowed(spec, ORDER_FILLING_FOK))
      return ORDER_FILLING_FOK;
   if(SpecIsFillingAllowed(spec, ORDER_FILLING_IOC))
      return ORDER_FILLING_IOC;
   if(SpecIsFillingAllowed(spec, ORDER_FILLING_RETURN))
      return ORDER_FILLING_RETURN;
   return (ENUM_ORDER_TYPE_FILLING)-1;
  }

// Next allowed filling after `current` (used for the single INVALID_FILL
// re-send), strictly later in the FOK -> IOC -> RETURN order. Returns -1
// when no further mode is allowed.
ENUM_ORDER_TYPE_FILLING SpecNextFilling(const SSymbolSpec &spec,
                                        const ENUM_ORDER_TYPE_FILLING current)
  {
   if(current == ORDER_FILLING_FOK && SpecIsFillingAllowed(spec, ORDER_FILLING_IOC))
      return ORDER_FILLING_IOC;
   if(current != ORDER_FILLING_RETURN && SpecIsFillingAllowed(spec, ORDER_FILLING_RETURN))
      return ORDER_FILLING_RETURN;
   return (ENUM_ORDER_TYPE_FILLING)-1;
  }

string SpecFillingName(const ENUM_ORDER_TYPE_FILLING filling)
  {
   if(filling == ORDER_FILLING_FOK)
      return "FOK";
   if(filling == ORDER_FILLING_IOC)
      return "IOC";
   if(filling == ORDER_FILLING_RETURN)
      return "RETURN";
   return "NONE";
  }

// symbols whose chosen filling mode has been logged (once per symbol)
string g_specFillingLogged[];

// THE filling mode for every live market deal (TradeManager opens and
// closes, the demo probe orders): the first mode the broker allows, FOK when
// it allows none (the pre-FILL-MODE-1 fallback). Logged once per symbol.
ENUM_ORDER_TYPE_FILLING SpecChooseFilling(const SSymbolSpec &spec)
  {
   ENUM_ORDER_TYPE_FILLING filling = SpecPreferredFilling(spec);
   bool none = (filling == (ENUM_ORDER_TYPE_FILLING)-1);
   if(none)
      filling = ORDER_FILLING_FOK;
   int n = ArraySize(g_specFillingLogged);
   for(int i = 0; i < n; i++)
      if(g_specFillingLogged[i] == spec.name)
         return filling;
   ArrayResize(g_specFillingLogged, n + 1);
   g_specFillingLogged[n] = spec.name;
   PrintFormat("[mql5bot] FILLING|%s|%s|filling_mode_mask=%I64d|exemode=%I64d%s",
               spec.name, SpecFillingName(filling), spec.fillingMode,
               spec.executionMode,
               none ? "|none allowed: FOK fallback" : "");
   return filling;
  }

#endif // MQL5BOT_SYMBOLSPEC_MQH
//+------------------------------------------------------------------+
