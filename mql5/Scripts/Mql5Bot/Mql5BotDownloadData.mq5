//+------------------------------------------------------------------+
//|                                       Mql5BotDownloadData.mq5    |
//|                                                                  |
//|  Exports bar history from MetaTrader 5 to a CSV file that the    |
//|  Python toolkit can load directly (mql5bot.data.load_csv).       |
//|                                                                  |
//|  Usage: attach to a chart (any symbol/timeframe) and set:        |
//|    InpBars     = number of bars to export                        |
//|    InpFileName = file name (created in the common Files folder)  |
//|                                                                  |
//|  Then in Python:                                                 |
//|    mql5bot backtest --data "<MT5 data>/MQL5/Files/<name>" ...    |
//+------------------------------------------------------------------+
#property copyright "mql5bot contributors"
// MetaEditor market-format metadata (xxx.yyy) for this executable —
// a separate plane from the repository/package release version
// "1.0.0" (docs/DECISIONS.md 2026-09-08); kept aligned with the EA.
#property version   "1.00"
#property script_show_inputs
#property strict

input int    InpBars     = 50000;              // Bars to export
input string InpFileName = "mql5bot_export.csv"; // Output file (Files folder)

//+------------------------------------------------------------------+
//| Script program start function                                    |
//+------------------------------------------------------------------+
void OnStart()
  {
   string symbol = Symbol();
   ENUM_TIMEFRAMES tf = Period();

   datetime from = 0;
   if(InpBars > 0)
     {
      from = iTime(symbol, tf, InpBars - 1);
      if(from == 0)   // not enough history loaded
        {
         // request as much as possible: copy everything available
         from = 0;
        }
     }

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, tf, from, InpBars > 0 ? InpBars : 0, rates);
   if(copied <= 0)
     {
      PrintFormat("DownloadData: CopyRates failed (%d)", GetLastError());
      return;
     }

   int handle = FileOpen(InpFileName, FILE_WRITE | FILE_CSV | FILE_ANSI, ';');
   if(handle == INVALID_HANDLE)
     {
      PrintFormat("DownloadData: cannot open %s (error %d)", InpFileName, GetLastError());
      return;
     }

   // header — column order is flexible for the Python loader,
   // but keep the canonical order anyway
   FileWrite(handle, "time", "open", "high", "low", "close", "volume");

   for(int i = copied - 1; i >= 0; i--)   // oldest first
     {
      FileWrite(handle,
                TimeToString(rates[i].time, TIME_DATE | TIME_SECONDS),
                DoubleToString(rates[i].open,  _Digits),
                DoubleToString(rates[i].high,  _Digits),
                DoubleToString(rates[i].low,   _Digits),
                DoubleToString(rates[i].close, _Digits),
                IntegerToString(rates[i].tick_volume));
     }

   FileClose(handle);
   PrintFormat("DownloadData: exported %d bars of %s %s -> %s",
               copied, symbol, EnumToString(tf), InpFileName);
  }
//+------------------------------------------------------------------+
