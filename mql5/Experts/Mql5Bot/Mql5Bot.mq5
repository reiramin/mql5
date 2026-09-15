//+------------------------------------------------------------------+
//|                                                 Mql5Bot.mq5     |
//|              Full-featured Expert Advisor framework for MT5      |
//|                                                                  |
//|  - 5 strategies (EMA crossover, RSI reversal, Donchian breakout, |
//|    Bollinger reversal, MACD momentum)                            |
//|  - risk engine on the injected SSymbolSpec: sizing modes, margin |
//|    checks, daily loss limit, drawdown kill switch, spread guard  |
//|  - persistent fail-safe state (S2): kill switch, day-start       |
//|    equity and equity peak survive restarts; explicit reset only  |
//|  - post-fill SL enforcement (S1): verify -> modify -> close      |
//|  - Sleep-free execution (S3): single attempts + RetryQueue on    |
//|    OnTimer with exponential backoff                              |
//|  - stable magic identity (S5): FNV-1a MagicMap per strategy id   |
//|  - restart recovery (S6): ticket registry adoption, orphan       |
//|    pending cancellation, per-position management flags           |
//|  - ATR trailing stop, breakeven, partial scale-out               |
//|  - file logging + HTTP telemetry (WebRequest)                    |
//|                                                                  |
//|  The Python twin of every strategy lives in python/mql5bot/ —    |
//|  validate parameter sets there before going live.                |
//+------------------------------------------------------------------+
#property copyright "mql5bot contributors"
#property link      "https://github.com/raminhdev/mql5bot"
// EA METADATA version (MQL5 Market format xxx.yyy) — a separate
// version plane from the repository/package release "1.0.0" and from
// MQL5BOT_VERSION (telemetry identity), per docs/DECISIONS.md.
#property version   "1.00"

#include <Mql5Bot/Config.mqh>
#include <Mql5Bot/Logger.mqh>
#include <Mql5Bot/Allocation.mqh>
#include <Mql5Bot/Session.mqh>
#include <Mql5Bot/SymbolSpec.mqh>
#include <Mql5Bot/StateStore.mqh>
#include <Mql5Bot/MagicMap.mqh>
#include <Mql5Bot/RiskManager.mqh>
#include <Mql5Bot/RetryQueue.mqh>
#include <Mql5Bot/TradeManager.mqh>
#include <Mql5Bot/PositionGuard.mqh>
#include <Mql5Bot/SlGuard.mqh>
#include <Mql5Bot/SignalEngine.mqh>
#include <Mql5Bot/Telemetry.mqh>

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group "=== Strategy ==="
input ENUM_MQL5BOT_STRATEGY InpStrategy      = STRAT_EMA_CROSSOVER;  // Strategy
input int                     InpFastEma     = 10;                   // EMA fast period
input int                     InpSlowEma     = 30;                   // EMA slow period
input int                     InpRsiPeriod   = 14;                   // RSI period
input double                  InpRsiOversold = 30.0;                 // RSI oversold
input double                  InpRsiOverbought = 70.0;               // RSI overbought
input int                     InpDonchianPeriod = 20;                // Donchian period
input int                     InpBollingerPeriod = 20;               // Bollinger period
input double                  InpBollingerDev  = 2.0;                // Bollinger deviations
input int                     InpMacdFast   = 12;                    // MACD fast
input int                     InpMacdSlow   = 26;                    // MACD slow
input int                     InpMacdSignal = 9;                     // MACD signal
input double                  InpSlAtr      = 2.5;                   // Stop-loss (ATR x)
input double                  InpTpAtr      = 4.0;                   // Take-profit (ATR x)

input group "=== Risk & money management ==="
input ENUM_SIZING_MODE        InpSizingMode = SIZING_RISK_PERCENT_EQ; // Sizing mode
input double                  InpRiskPercent = 1.0;                  // Risk % of equity per trade
input double                  InpFixedLots   = 0.01;                 // Fixed lots (fixed-lot mode)
input double                  InpFixedMoney  = 100.0;                // Fixed risk money (fixed-money mode)
input double                  InpKellyWinRate = 0.55;                // Kelly: win rate (0..1)
input double                  InpKellyPayoff  = 1.5;                 // Kelly: payoff ratio
input double                  InpMaxLots     = 10.0;                 // Max lots per trade
input string                  InpAllocationFile = "in/allocation.json"; // Meta Layer allocation (sizing scale only)
input double                  InpBaseGateWeight = 1.0;                // Base gate weight when allocation is stale/missing
input double                  InpDailyLossPct = 0.0;                 // Daily loss limit % (0=off)
input double                  InpMaxDrawdownPct = 0.0;               // Max drawdown kill-switch % (0=off)
input double                  InpMaxSpreadPoints = 0.0;              // Max spread in points (0=off)
input int                     InpMaxBars     = 0;                    // Max bars per trade (0=off)

input group "=== Exits ==="
input double                  InpTrailAtr    = 0.0;                  // ATR trailing stop (0=off)
input double                  InpBreakevenAtr = 0.0;                 // Breakeven trigger (ATR, 0=off)
input double                  InpBreakevenOffset = 0.0;              // Breakeven offset (points)
input double                  InpPartialAtr  = 0.0;                  // Partial close trigger (ATR, 0=off)
input double                  InpPartialFraction = 0.5;              // Partial close fraction

input group "=== Execution ==="
input ENUM_MQL5BOT_ENTRY_MODE InpEntryMode  = ENTRY_MARKET;         // Entry mode
input int                     InpPendingOffsetPoints = 10;           // Pending order offset (points)
input int                     InpPendingExpireBars = 6;              // Pending expiry (bars)
input int                     InpDeviation   = 30;                   // Max price deviation (points)
input int                     InpMaxRetries  = 3;                    // Order retries (RetryQueue cap)
input bool                    InpAllowShort  = true;                 // Allow short trades
input long                    InpMagic       = 20240904;             // Legacy magic (registry off)

input group "=== Identity & state ==="
input bool                    InpUseMagicRegistry = true;            // FNV-1a magic from strategy id
input bool                    InpResetKillSwitch  = false;           // Explicit kill-switch reset

input group "=== Session filter ==="
input bool                    InpUseSession  = false;                // Enable session filter
input int                     InpSessionStartHour = 8;               // Session start hour (server)
input int                     InpSessionStartMin  = 0;               // Session start minute
input int                     InpSessionEndHour   = 17;              // Session end hour
input int                     InpSessionEndMin    = 0;               // Session end minute
input int                     InpSessionDays      = SESSION_WEEKDAYS; // Days bitmask (0=Sun .. 6=Sat)

input group "=== Logging & telemetry ==="
input int                     InpLogLevel    = 2;                    // 0=off 1=error 2=info 3=debug
input bool                    InpTelemetry   = false;                // Enable HTTP telemetry
input string                  InpWebhookUrl  = MQL5BOT_WEBENDPOINT;  // Webhook URL (add to allowed list)

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CLogger         g_log;
CSessionFilter  g_session;
CRiskManager    g_risk;
CTradeManager   g_trade;
CPositionGuard  g_guard;
CAllocation     g_alloc;          // Meta Layer allocation (sizing only)
CSignalEngine   g_signal;
CTelemetry      g_tele;
CSlGuard        g_slguard;
CStateStore     g_store;
CMagicMap       g_magicMap;

SSymbolSpec     g_spec;
long            g_magic         = 0;
string          g_strategyId    = "ema_crossover";
ENUM_MQL5BOT_STRATEGY g_strategy = STRAT_EMA_CROSSOVER;
SBotParams      g_params;
SBotSignal      g_lastSignal;

datetime        g_lastBarTime   = 0;
datetime        g_lastHeartbeat = 0;
bool            g_dailyHit      = false;
bool            g_drawdownHit   = false;
ulong           g_managedTicket = 0;
int             g_lastDayKey    = 0;
bool            g_orphanScanDone = false;
int             g_tickCounter   = 0;
string          g_symbol        = _Symbol;
ENUM_TIMEFRAMES g_tf            = _Period;

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
string TfToString(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M1:  return "M1";
      case PERIOD_M2:  return "M2";
      case PERIOD_M3:  return "M3";
      case PERIOD_M4:  return "M4";
      case PERIOD_M5:  return "M5";
      case PERIOD_M6:  return "M6";
      case PERIOD_M10: return "M10";
      case PERIOD_M12: return "M12";
      case PERIOD_M15: return "M15";
      case PERIOD_M20: return "M20";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H2:  return "H2";
      case PERIOD_H3:  return "H3";
      case PERIOD_H4:  return "H4";
      case PERIOD_H6:  return "H6";
      case PERIOD_H8:  return "H8";
      case PERIOD_H12: return "H12";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN1";
      default:         return "?";
     }
  }

string StrategyIdFromEnum(ENUM_MQL5BOT_STRATEGY s)
  {
   switch(s)
     {
      case STRAT_EMA_CROSSOVER:     return "ema_crossover";
      case STRAT_RSI_REVERSAL:      return "rsi_reversal";
      case STRAT_DONCHIAN_BREAKOUT: return "donchian_breakout";
      case STRAT_BOLLINGER_REVERSAL:return "bollinger_reversal";
      case STRAT_MACD_MOMENTUM:     return "macd_momentum";
     }
   return "unknown";
  }

int CountBotPositions()
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == g_symbol &&
         PositionGetInteger(POSITION_MAGIC) == g_magic)
         count++;
     }
   return count;
  }

int CurrentExposure()
  {
   int dir = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == g_symbol &&
         PositionGetInteger(POSITION_MAGIC) == g_magic)
        {
         long type = PositionGetInteger(POSITION_TYPE);
         dir += (type == POSITION_TYPE_LONG) ? 1 : -1;
        }
     }
   if(dir > 0) return 1;
   if(dir < 0) return -1;
   return 0;
  }

// close every position of our magic on the chart symbol
void CloseAllPositions(string reason)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == g_symbol &&
         PositionGetInteger(POSITION_MAGIC) == g_magic)
        {
         if(g_trade.ClosePosition(t, 0.0))
            g_log.Info("closed position #" + IntegerToString(t) + " (" + reason + ")");
         else if(g_trade.HasQueuedWork())
            g_log.Info("close #" + IntegerToString(t) + " queued (" + reason + ")");
        }
     }
  }

// Rebuild the ticket registry from reality: prune gone positions, adopt
// unknown positions of our magic (S2/S6 recovery).
void SyncRecords()
  {
   for(int i = g_store.Count() - 1; i >= 0; i--)
     {
      STicketRec rec = g_store.RecordAt(i);
      if(!PositionSelectByTicket(rec.ticket))
         g_store.RemoveByTicket(rec.ticket);   // closed by SL/TP/manual
     }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic) continue;
      if(g_store.HasTicket(t))
         continue;
      STicketRec rec;
      rec.ticket     = t;
      rec.strategyId = g_strategyId;
      rec.symbol     = g_symbol;
      rec.type       = (long)PositionGetInteger(POSITION_TYPE);
      rec.entry      = PositionGetDouble(POSITION_PRICE_OPEN);
      rec.openTime   = (datetime)PositionGetInteger(POSITION_TIME);
      rec.lots       = PositionGetDouble(POSITION_VOLUME);
      rec.partialDone = false;
      rec.beDone     = false;
      g_store.Upsert(rec);
      g_log.Warn("adopted unknown position #" + IntegerToString(t) +
                 " (restart recovery)");
     }
  }

// Enqueue SL verification for every managed position that is not secured.
// desired SL comes from the active strategy signal, or a structural ATR
// fallback; if neither is available the guard closes the position (a bare
// position is never acceptable — SPEC §3.2).
void ProtectManagedPositions()
  {
   for(int i = 0; i < g_store.Count(); i++)
     {
      STicketRec rec = g_store.RecordAt(i);
      if(rec.ticket == 0)
         continue;
      if(!PositionSelectByTicket(rec.ticket))
         continue;
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(SlVerdict(g_spec, (long)PositionGetInteger(POSITION_TYPE),
                   PositionGetDouble(POSITION_PRICE_OPEN), sl) == SL_VERDICT_OK)
         continue;
      if(g_slguard.CoversTicket(g_magic, rec.symbol, rec.ticket, rec.openTime))
         continue;
      double desiredSl = 0.0, desiredTp = 0.0;
      long dir = (long)PositionGetInteger(POSITION_TYPE);
      if(g_lastSignal.valid && g_lastSignal.slPrice > 0.0)
        {
         int sigDir = g_lastSignal.direction;
         if((sigDir > 0 && dir == POSITION_TYPE_LONG) ||
            (sigDir < 0 && dir == POSITION_TYPE_SHORT))
           {
            desiredSl = g_lastSignal.slPrice;
            desiredTp = g_lastSignal.tpPrice;
           }
        }
      if(desiredSl <= 0.0)
        {
         double atr = g_guard.ATR(rec.symbol, g_tf, 1);
         if(atr > 0.0)
           {
            double fallbackDist = SpecEnforceMinStop(2.0 * atr, g_spec);
            desiredSl = (dir == POSITION_TYPE_LONG)
                        ? rec.entry - fallbackDist
                        : rec.entry + fallbackDist;
            desiredTp = 0.0;
           }
        }
      g_slguard.Enqueue(g_magic, rec.symbol, 0, desiredSl, desiredTp, rec.ticket);
     }
  }

// May the daily-loss / guard pause clear at day rollover?
bool AllManagedSecured()
  {
   for(int i = 0; i < g_store.Count(); i++)
     {
      STicketRec rec = g_store.RecordAt(i);
      if(!PositionSelectByTicket(rec.ticket))
         continue;
      double sl = PositionGetDouble(POSITION_SL);
      if(SlVerdict(g_spec, (long)PositionGetInteger(POSITION_TYPE),
                   PositionGetDouble(POSITION_PRICE_OPEN), sl) != SL_VERDICT_OK)
         return false;
     }
   return g_slguard.ActiveCount() == 0;
  }

// cancel orphaned pending orders of our magic after a restart
void CancelOrphanPendings()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != g_symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != g_magic) continue;
      long type = (long)OrderGetInteger(ORDER_TYPE);
      if(type != ORDER_TYPE_BUY_STOP && type != ORDER_TYPE_SELL_STOP)
         continue;
      MqlTradeRequest req;
      ZeroMemory(req);
      req.action = TRADE_ACTION_REMOVE;
      req.order  = t;
      MqlTradeResult res;
      ZeroMemory(res);
      if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE)
         g_log.Info("cancelled orphan pending #" + IntegerToString(t));
      else if(IsRetryableRetcode(res.retcode))
        {
         // single-shot cancel failed on a transient server condition:
         // hand it to the bounded RetryQueue (attempt cap, backoff) —
         // an orphan pending must never be silently abandoned
         g_trade.QueueCancelByTicket(t);
         g_log.Warn("orphan pending cancel queued for retry #"
                    + IntegerToString(t) + " ("
                    + RetcodeToString(res.retcode) + ")");
        }
      else
         g_log.Warn("orphan pending cancel failed #" + IntegerToString(t) +
                    " (" + RetcodeToString(res.retcode) + ")");
     }
   g_orphanScanDone = true;
  }

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_strategy = InpStrategy;
   g_strategyId = StrategyIdFromEnum(g_strategy);

   //--- input validation (SPEC §8.A: INIT_PARAMETERS_INCORRECT) -------
   if(InpSlAtr <= 0.0 || InpTpAtr <= 0.0)
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: SL/TP ATR multiples must be > 0");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpRsiPeriod < 2 || InpRsiOversold <= 0.0 || InpRsiOverbought >= 100.0 ||
      InpRsiOversold >= InpRsiOverbought)
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: invalid RSI settings");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpDonchianPeriod < 2 || InpBollingerPeriod < 2 || InpBollingerDev <= 0.0 ||
      InpMacdFast >= InpMacdSlow || InpMacdSignal < 1)
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: invalid indicator settings");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpFastEma >= InpSlowEma || InpFastEma < 1)
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: fast EMA must be < slow EMA");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpRiskPercent <= 0.0 || InpMaxLots <= 0.0 || InpMaxRetries < 0 ||
      InpMaxRetries > 10 || InpMaxSpreadPoints < 0.0)
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: invalid risk parameters");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpDeviation < 0 || InpPendingOffsetPoints < 0 || InpPendingExpireBars < 1 ||
      InpTrailAtr < 0.0 || InpBreakevenAtr < 0.0 || InpBreakevenOffset < 0.0 ||
      InpPartialAtr < 0.0 || InpPartialFraction <= 0.0 ||
      InpPartialFraction >= 1.0 || InpMaxBars < 0)
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: invalid execution/exit parameters");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpDailyLossPct < 0.0 || InpDailyLossPct >= 100.0 ||
      InpMaxDrawdownPct < 0.0 || InpMaxDrawdownPct >= 100.0)
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: limit percentages must be in [0,100)");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpSizingMode == SIZING_KELLY &&
      (InpKellyWinRate <= 0.0 || InpKellyWinRate >= 1.0 || InpKellyPayoff <= 0.0))
     {
      Print("[mql5bot] INIT_PARAMETERS_INCORRECT: invalid Kelly inputs");
      return INIT_PARAMETERS_INCORRECT;
     }

   //--- logger
   g_log.Init("Mql5Bot\\Logs\\", "mql5bot_" + g_symbol + "_" + TfToString(g_tf), InpLogLevel);

   //--- environment validation: broker facts queried, never assumed ----
   if(!BuildSymbolSpec(g_symbol, g_spec))
     {
      g_log.Error("symbol spec build failed: " + g_spec.reason);
      return INIT_FAILED;
     }
   if(!MQL_TESTER && !MQL_OPTIMIZATION)
     {
      if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ||
         !MQLInfoInteger(MQL_TRADE_ALLOWED) ||
         AccountInfoInteger(ACCOUNT_TRADE_EXPERT) == 0)
        {
         g_log.Error("trading not enabled (terminal/EA/account)");
         return INIT_FAILED;
        }
     }

   //--- session filter
   g_session.Init(InpUseSession, InpSessionStartHour, InpSessionStartMin,
                  InpSessionEndHour, InpSessionEndMin, InpSessionDays);

   //--- params for the signal engine
   g_params.fastEma        = InpFastEma;
   g_params.slowEma        = InpSlowEma;
   g_params.rsiPeriod      = InpRsiPeriod;
   g_params.rsiOversold    = InpRsiOversold;
   g_params.rsiOverbought  = InpRsiOverbought;
   g_params.donchianPeriod = InpDonchianPeriod;
   g_params.bollingerPeriod= InpBollingerPeriod;
   g_params.bollingerDev   = InpBollingerDev;
   g_params.macdFast       = InpMacdFast;
   g_params.macdSlow       = InpMacdSlow;
   g_params.macdSignal     = InpMacdSignal;
   g_params.slAtr          = InpSlAtr;
   g_params.tpAtr          = InpTpAtr;

   //--- signal engine
   if(!g_signal.Init(g_symbol, g_tf, g_params))
      return INIT_FAILED;

   //--- position guard (ATR for management + adoption fallback)
   if(!g_guard.Init(g_symbol, g_tf, InpTrailAtr, InpBreakevenAtr,
                    InpBreakevenOffset, InpPartialAtr, InpPartialFraction))
      return INIT_FAILED;

   //--- risk engine + persisted state (S2)
   double riskValue = (InpSizingMode == SIZING_FIXED_LOT) ? InpFixedLots :
                      (InpSizingMode == SIZING_FIXED_MONEY) ? InpFixedMoney :
                      InpRiskPercent;
   g_risk.Init(InpSizingMode, riskValue, InpMaxLots, InpDailyLossPct,
               InpMaxDrawdownPct, InpMaxSpreadPoints,
               InpKellyWinRate, InpKellyPayoff);

   ENUM_ENGINE_STATE storedState = ENGINE_NORMAL;
   int storedReason = REASON_NONE;
   double dayStart = 0.0, peak = 0.0;
   int dayKey = 0;
   if(HotStateLoad(storedState, storedReason, dayKey, dayStart, peak))
     {
      g_log.Info(StringFormat("restored state: engine=%d reason=%d dayKey=%d",
                              (int)storedState, storedReason, dayKey));
     }
   else
     g_risk.ResetDayAndPeak();

   //--- explicit kill-switch reset (one-shot: false->true edge) --------
   bool resetArmed = (int)GlobalVariableGet(GV_RESET_ACK) == 1;
   if(InpResetKillSwitch)
     {
      if(!resetArmed)
        {
         g_log.Warn("EXPLICIT kill-switch reset requested");
         storedState = ENGINE_NORMAL;
         storedReason = REASON_NONE;
         GlobalVariableSet(GV_RESET_ACK, 1.0);
         g_risk.ResetDayAndPeak();
        }
     }
   else if(resetArmed)
      GlobalVariableSet(GV_RESET_ACK, 0.0);

   g_risk.AdoptState(storedState, storedReason, dayStart, peak);
   g_lastDayKey = CRiskManager::CurrentDayKey();
   g_dailyHit   = (storedState == ENGINE_NO_NEW_TRADES &&
                   storedReason == REASON_DAILY_LOSS);
   if(g_risk.State() != ENGINE_NORMAL)
      g_log.Warn("engine NOT in NORMAL state at startup: " +
                 StateReasonToString(storedReason));

   //--- magic identity (S5): FNV-1a registry or legacy input -----------
   string magicFile = "Mql5Bot\\State\\magicmap.txt";
   if(InpUseMagicRegistry)
     {
      g_magicMap.LoadFromFile(magicFile);
      g_magic = g_magicMap.Allocate(g_strategyId);
      if(g_magic < 0)
        {
         g_log.Error("magic allocation failed");
         return INIT_FAILED;
        }
      g_magicMap.SaveToFile(magicFile);
      g_log.Info("strategy id '" + g_strategyId + "' -> magic " +
                 IntegerToString(g_magic));
     }
   else
     {
      g_magic = InpMagic;
      g_log.Warn("using LEGACY input magic (registry disabled): " +
                 IntegerToString(g_magic));
     }

   //--- ticket registry (cold state)
   g_store.Load(STORE_STATE_FILE);

   //--- trade manager: Sleep-free, spec-injected
   g_trade.Init(g_magic, InpDeviation, InpMaxRetries,
                InpEntryMode == ENTRY_PENDING, InpPendingExpireBars, g_spec);

   //--- telemetry
   g_tele.Init(InpTelemetry, InpWebhookUrl, 2000);

   //--- Meta Layer allocation (sizing-only consumer; contract 1.1.1)
   g_alloc.Init(&g_log, InpAllocationFile);
   g_alloc.OnTimerPoll();

   g_log.Info(StringFormat("initialised: strategy=%s risk=%.2f%% sl=%.2f ATR tp=%.2f ATR",
                           g_strategyId, InpRiskPercent, InpSlAtr, InpTpAtr));
   EventSetTimer(1);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| OnDeinit                                                         |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_store.IsDirty())
      g_store.Save(STORE_STATE_FILE);
   g_log.Info("shutting down (reason " + IntegerToString(reason) + ")");
   g_signal.Deinit();
   g_log.Flush();
  }

//+------------------------------------------------------------------+
//| OnTimer — retry queue, guard pump, recovery, limits, heartbeat   |
//|           + allocation hot-reload poll (SPEC: in/allocation.json)|
//+------------------------------------------------------------------+
void OnTimer()
  {
   g_alloc.OnTimerPoll();      // mtime-poll the Meta allocation
   g_tickCounter++;

   //--- retry queue (S3) — bounded work per tick
   g_trade.ProcessQueue(8);

   //--- restart recovery (S2/S6): cancel orphan pendings once
   if(!g_orphanScanDone)
      CancelOrphanPendings();

   //--- ticket registry sync + SL protection
   SyncRecords();
   ProtectManagedPositions();

   //--- kill switch enforcement: while HALT keep closing everything
   //    (bounded cadence — the RetryQueue already backs off per attempt)
   if(g_risk.State() == ENGINE_HALT && (g_tickCounter % 10) == 0)
     {
      if(CountBotPositions() > 0)
         CloseAllPositions("kill_switch_halt");
     }

   //--- day rollover (server time)
   if(CRiskManager::CurrentDayKey() != g_lastDayKey)
     {
      g_lastDayKey = CRiskManager::CurrentDayKey();
      g_dailyHit   = false;
      g_risk.OnNewDay();
      // guard/daily pauses may clear at the reset boundary once every
      // managed position is secured
      if(g_risk.State() == ENGINE_NO_NEW_TRADES &&
         (g_risk.StateReason() == REASON_DAILY_LOSS ||
          g_risk.StateReason() == REASON_SL_GUARD) &&
         AllManagedSecured())
         g_risk.SetState(ENGINE_NORMAL, REASON_NONE);
      g_log.Info("new trading day — daily limits reset");
     }

   //--- equity limits (daily/drawdown) + SL-guard pump
   bool dailyHit = false, drawdownHit = false;
   g_risk.CheckLimits(dailyHit, drawdownHit);
   g_drawdownHit = drawdownHit;
   if(drawdownHit)
     {
      g_log.Error("MAX DRAWDOWN LIMIT HIT — kill switch engaged (persisted)");
      g_tele.Alert("critical", "max drawdown limit hit — trading disabled");
      CloseAllPositions("drawdown_kill");
     }
   else if(dailyHit && !g_dailyHit && g_risk.State() == ENGINE_NORMAL)
     {
      // a daily breach pauses a NORMAL engine; it never softens an active
      // guard pause or the kill switch (those have their own stricter gates)
      g_dailyHit = true;
      g_log.Error("DAILY LOSS LIMIT HIT — trading paused for today (persisted)");
      g_tele.Alert("warning", "daily loss limit hit");
      g_risk.SetState(ENGINE_NO_NEW_TRADES, REASON_DAILY_LOSS);
      CloseAllPositions("daily_loss_limit");
     }

   int secured = 0, closed = 0, escalated = 0;
   g_slguard.Pump(g_trade, g_spec, secured, closed, escalated);
   if(escalated > 0)
     {
      g_log.Error("SL GUARD ESCALATION — position could not be secured or closed");
      g_tele.Alert("critical", "SL guard escalation — engine halted");
      g_risk.TripKillSwitch(REASON_SL_GUARD);
     }
   if(closed > 0)
     {
      g_log.Error("SL GUARD — position closed because SL could not be secured");
      g_tele.Alert("critical", "SL remediation failed — position closed");
      if(g_risk.State() == ENGINE_NORMAL)
         g_risk.SetState(ENGINE_NO_NEW_TRADES, REASON_SL_GUARD);
     }

   //--- periodic state file flush (bounded write rate)
   if(g_store.IsDirty() && (g_tickCounter % 5) == 0)
      g_store.Save(STORE_STATE_FILE);

   //--- telemetry heartbeat (every 60 s)
   if(g_tele.IsEnabled() && TimeCurrent() - g_lastHeartbeat >= 60)
     {
      g_lastHeartbeat = TimeCurrent();
      double dailyPnl = AccountInfoDouble(ACCOUNT_EQUITY) -
                        g_risk.DayStartEquity();
      g_tele.Heartbeat(g_symbol, TfToString(g_tf),
                       AccountInfoDouble(ACCOUNT_EQUITY),
                       AccountInfoDouble(ACCOUNT_BALANCE),
                       dailyPnl);
     }
  }

//+------------------------------------------------------------------+
//| Management of open positions (closed bars only)                  |
//+------------------------------------------------------------------+
void ManageOpenPositions()
  {
   int n = g_store.Count();
   if(n == 0)
      return;
   // earliest open record gets the full management treatment (trailing /
   // breakeven / partial) — matching the single-position model; every
   // record still gets the max-bars timeout.
   datetime earliest = 0;
   int manageIdx = -1;
   for(int i = 0; i < n; i++)
     {
      STicketRec rec = g_store.RecordAt(i);
      if(!PositionSelectByTicket(rec.ticket))
         continue;
      if(earliest == 0 || rec.openTime < earliest)
        {
         earliest = rec.openTime;
         manageIdx = i;
        }
     }
   if(manageIdx >= 0)
     {
      // restart the position guard's bar counter whenever the managed
      // position changes (fresh entry, restart adoption, or flip) so the
      // partial/breakeven delay measures bars of THIS position
      STicketRec rec = g_store.RecordAt(manageIdx);
      if(rec.ticket != g_managedTicket)
        {
         g_managedTicket = rec.ticket;
         g_guard.OnPositionOpened();
        }
     }
   for(int i = 0; i < n; i++)
     {
      STicketRec rec = g_store.RecordAt(i);
      if(!PositionSelectByTicket(rec.ticket))
         continue;

      //--- max-bars timeout (every managed position)
      if(InpMaxBars > 0)
        {
         int bars = iBarShift(rec.symbol, g_tf, rec.openTime, false);
         if(bars >= InpMaxBars)
           {
            if(g_trade.ClosePosition(rec.ticket, 0.0))
               g_log.Info(StringFormat("#%I64u closed: max bars timeout (%d)",
                                       rec.ticket, bars));
            continue;
           }
        }
      if(i != manageIdx)
         continue;

      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      int action = g_guard.Review(rec.symbol, g_tf, rec.ticket, sl, tp,
                                  rec.partialDone);
      if((action & EXIT_MODIFY_SLTP) != 0)
        {
         if(g_trade.ModifySLTP(rec.ticket, sl, tp))
            g_log.Info(StringFormat("#%I64u exits updated: sl=%.5f tp=%.5f",
                                    rec.ticket, sl, tp));
        }
      if((action & EXIT_CLOSE_PARTIAL) != 0)
        {
         double vol = PositionGetDouble(POSITION_VOLUME) *
                      g_guard.PartialFraction();
         if(g_trade.ClosePosition(rec.ticket, vol))
           {
            rec.partialDone = true;
            g_store.Upsert(rec);
            g_log.Info(StringFormat("#%I64u partial close %.2f lots (SL -> breakeven)",
                                    rec.ticket, vol));
            g_tele.Trade(g_symbol, "partial_close", rec.strategyId, vol,
                         SymbolInfoDouble(g_symbol, SYMBOL_BID), 0.0,
                         "scale-out");
           }
        }
      if((action & EXIT_CLOSE_FULL) != 0)
        {
         if(g_trade.ClosePosition(rec.ticket, 0.0))
            g_log.Info("#" + IntegerToString(rec.ticket) + " closed by guard");
        }
     }
  }

//+------------------------------------------------------------------+
//| New-bar entry & exit logic (runs once per completed bar)         |
//+------------------------------------------------------------------+
void OnNewBar()
  {
   //--- pending order housekeeping (fills / expiry)
   if(g_trade.HasPendingOrder())
      g_trade.OnBar(g_symbol);

   //--- recovery bookkeeping runs on every bar too
   SyncRecords();
   ManageOpenPositions();
   ProtectManagedPositions();

   //--- entry gates -------------------------------------------------
   if(!g_risk.AllowsNewTrades())
      return;
   if(g_dailyHit || g_drawdownHit)
      return;
   if(!g_risk.IsSpreadOK(g_symbol))
      return;
   if(g_trade.HasPendingOrder() || g_trade.HasQueuedWork())
      return;   // a pending entry / retry is already working

   long mode = SymbolInfoInteger(g_symbol, SYMBOL_TRADE_MODE);
   if(mode != SYMBOL_TRADE_MODE_FULL &&
      !(mode == SYMBOL_TRADE_MODE_LONGONLY || mode == SYMBOL_TRADE_MODE_SHORTONLY))
      return;

   //--- session filter
   if(!g_session.IsTradingTime(TimeCurrent()))
      return;

   g_lastSignal = g_signal.Evaluate(g_strategy);
   if(!g_lastSignal.valid)
      return;

   int desired = g_lastSignal.direction;
   if(desired < 0 && !InpAllowShort)
      desired = 0;
   else if(desired < 0 && mode == SYMBOL_TRADE_MODE_LONGONLY)
      desired = 0;
   else if(desired > 0 && mode == SYMBOL_TRADE_MODE_SHORTONLY)
      desired = 0;
   if(desired == 0)
      return;

   int exposure = CurrentExposure();
   if(exposure == desired)
      return;
   if(exposure != 0)
     {
      // flip: close current, let the next bar open the new direction
      g_log.Info("signal flipped — closing opposite position");
      CloseAllPositions("signal_flip");
      return;
     }

   //--- size by risk over the stop distance (injected spec + margin)
   double fill = (desired > 0) ? SymbolInfoDouble(g_symbol, SYMBOL_ASK)
                               : SymbolInfoDouble(g_symbol, SYMBOL_BID);
   if(fill <= 0.0)
      return;
   string sizeReason = "";
   double lots = g_risk.GetLots(g_spec, fill, g_lastSignal.slPrice, sizeReason);
   if(lots <= 0.0)
     {
      g_log.Debug("no size: " + sizeReason);
      return;
     }
   // Meta Layer allocation scale (contract 1.1.1): AFTER the Risk
   // Engine sized the trade, BEFORE any order — can ONLY reduce.
   double riskApproved = lots;
   lots = g_alloc.ScaleLots(g_strategyId, lots, InpBaseGateWeight);
   if(lots <= 0.0)
      return;
   // Re-normalize the meta-scaled size DOWN to the broker grid and
   // DROP the trade below the broker minimum: forcing volume_min here
   // would exceed the meta decision (SpecNormalizeVolume's min-bump
   // is a Risk-Engine sizing behavior, not a Meta behavior).  Margin
   // cannot be violated by this path: margin need is monotone in lots
   // and the final size is <= the risk-approved size the engine
   // already margin-checked.
   double metaLots = MathFloor(lots / g_spec.volumeStep + 1e-9)
                     * g_spec.volumeStep;
   if(metaLots < g_spec.volumeMin || metaLots > riskApproved)
     {
      g_log.Info("meta scale below broker minimum or above approval"
                 " - no trade");
      return;
     }
   lots = metaLots;
   double riskMoney = g_risk.RiskMoneyAt(g_spec, lots, fill, g_lastSignal.slPrice);

   double slDist = (g_lastSignal.slPrice > 0.0)
                   ? MathAbs(fill - g_lastSignal.slPrice) : 0.0;
   double tpDist = (g_lastSignal.tpPrice > 0.0)
                   ? MathAbs(fill - g_lastSignal.tpPrice) : 0.0;
   double slAbs = (desired > 0) ? fill - slDist : fill + slDist;
   double tpAbs = (desired > 0) ? fill + tpDist : fill - tpDist;

   bool ok = false;
   if(g_trade.IsPendingMode())
     {
      SOrderResult r = g_trade.OpenPending(desired > 0 ? POSITION_TYPE_LONG
                                                       : POSITION_TYPE_SHORT,
                                           lots, InpPendingOffsetPoints,
                                           slDist, tpDist,
                                           g_strategyId);
      ok = r.done || r.queued;
      if(r.queued)
         g_log.Info("pending order queued for retry (attempt cap " +
                    IntegerToString(InpMaxRetries) + ")");
     }
   else
     {
      SOrderResult r = g_trade.OpenMarket(desired > 0 ? POSITION_TYPE_LONG
                                                      : POSITION_TYPE_SHORT,
                                          lots, slDist, tpDist,
                                          g_strategyId);
      ok = r.done || r.queued;
      if(r.queued)
         g_log.Info("market order queued for retry (attempt cap " +
                    IntegerToString(InpMaxRetries) + ")");
     }

   if(ok)
     {
      //--- post-fill SL enforcement (S1): verify, remediate, close
      g_slguard.Enqueue(g_magic, g_symbol, TimeCurrent(), slAbs, tpAbs, 0);
      g_log.Info(StringFormat("ENTRY %s %.2f lots risk=%.2f (%.2f%%) sl=%.5f tp=%.5f",
                              (desired > 0) ? "BUY" : "SELL", lots, riskMoney,
                              g_risk.RiskValue(), g_lastSignal.slPrice,
                              g_lastSignal.tpPrice));
      g_tele.Trade(g_symbol, (desired > 0) ? "buy" : "sell", g_strategyId,
                   lots, fill, 0.0, "entry");
     }
  }

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick()
  {
   datetime barTime = iTime(g_symbol, g_tf, 0);
   if(barTime != g_lastBarTime)
     {
      if(g_lastBarTime != 0)      // skip the very first tick of the EA
         OnNewBar();
      g_lastBarTime = barTime;
     }
  }

//+------------------------------------------------------------------+
//| OnTradeTransaction — log fills/close PnL via deal history        |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
     {
      ulong deal = trans.deal;
      if(HistoryDealSelect(deal))
        {
         long magic = HistoryDealGetInteger(deal, DEAL_MAGIC);
         if(magic == g_magic)
           {
            double pnl    = HistoryDealGetDouble(deal, DEAL_PROFIT);
            double vol    = HistoryDealGetDouble(deal, DEAL_VOLUME);
            double price  = HistoryDealGetDouble(deal, DEAL_PRICE);
            string symbol = HistoryDealGetString(deal, DEAL_SYMBOL);
            g_log.Info(StringFormat("DEAL #%I64u %s vol=%.2f price=%.5f pnl=%.2f",
                                    deal, symbol, vol, price, pnl));
            if(pnl != 0.0)
               g_tele.Trade(symbol, "close", g_strategyId,
                            vol, price, pnl,
                            HistoryDealGetString(deal, DEAL_COMMENT));
           }
        }
     }
  }
//+------------------------------------------------------------------+
