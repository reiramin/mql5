//+------------------------------------------------------------------+
//|                               Mql5Bot/Mql5BotExportSymbolSpec.mq5|
//| Owner-run broker reality export (AEGIS Phase 3).                 |
//|                                                                  |
//| Dumps every broker fact the parity harness needs for the chart   |
//| symbol into MQL5\Files\Mql5Bot\broker_exports\<SYMBOL>.json:     |
//| tick size/value(P/L), contract size, volume min/max/step/limit,  |
//| stops/freeze levels, digits, point, currencies, trade/filling/   |
//| order/expiration modes, margin mode, static margin rates and an  |
//| OrderCalcMargin probe (1.0 lot at mid).                          |
//|                                                                  |
//| Run on the LIVE account of record, then commit the JSON under    |
//| data/broker_exports/ and re-run tools/broker_symbol_parity.py.   |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input string InpExportDir = "Mql5Bot\\broker_exports\\"; // relative to MQL5\Files
input int InpDenomProbeTicks = 100; // optional OrderCalcProfit denomination witness

//--- JSON string escaping (generic) ---------------------------------------
// Every string written into the export document passes through here, so a
// broker-supplied value can never break the document: SYMBOL_PATH, the
// account server and the currency names may legally contain characters
// that JSON requires to be escaped ("Forex\EURUSD" is the observed case --
// a raw backslash is an invalid JSON escape and made the whole export
// unparsable by tools/broker_symbol_parity.py).
// The backslash is replaced FIRST: it is the introducer of every sequence
// produced below, so escaping the finished document instead would corrupt
// JSON syntax itself. Escaping stays at the string-value level.
// MQL5 documents no "\b"/"\f" string escapes, so those two control codes are
// matched by hex value ("\x08"/"\x0C"); ordinary characters (including
// non-ASCII) are copied through untouched -- no encoding transformation at
// the string level, while the byte layer below writes them as UTF-8.
// Pinned by tests/test_broker_symbol_parity.py (escape table + JSON
// round-trip of the escaped representation).
string JsonEscape(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", "\\n");
   StringReplace(s, "\r", "\\r");
   StringReplace(s, "\t", "\\t");
   StringReplace(s, "\x08", "\\b");
   StringReplace(s, "\x0C", "\\f");
   //--- any remaining control character (U+0000..U+001F) may not appear
   //--- raw inside a JSON string literal at all -> \u00xx.  The five named
   //--- ones above are already gone, so those are no-ops here.
   for(int c = 0; c < 0x20; c++)
      StringReplace(s, ShortToString((ushort)c), StringFormat("\\u%04x", c));
   return s;
  }

//--- quote one JSON member name or string value (escaping included)
string JsonQuote(string s)
  {
   return "\"" + JsonEscape(s) + "\"";
  }

void Main()
  {
   string sym = _Symbol;

   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double mid = (bid > 0.0 && ask > 0.0) ? 0.5 * (bid + ask) : 0.0;

   double marginInitial = 0.0, marginMaintenance = 0.0;
   double probeMarginBuy = 0.0, probeMarginSell = 0.0;
   bool probeOk = false;
   if(mid > 0.0)
     {
      probeOk = OrderCalcMargin(ORDER_TYPE_BUY, sym, 1.0, mid, probeMarginBuy)
                && OrderCalcMargin(ORDER_TYPE_SELL, sym, 1.0, mid,
                                   probeMarginSell);
     }

   long filling = SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   long orderMode = SymbolInfoInteger(sym, SYMBOL_ORDER_MODE);

   //--- Optional denomination witness.  OrderCalcProfit is deliberately
   //--- independent from SYMBOL_TRADE_TICK_VALUE_*: it returns P/L in the
   //--- account currency, so the harness can assess denomination per symbol
   //--- without global FX state or a circular tick-value conversion.
   bool denomOk = false;
   string denomReason = "not run";
   int denomLastError = 0;
   double probeTickSize = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double probeTicks = InpDenomProbeTicks;
   double probeMove = 0.0;
   double buyLossProfit = 0.0;
   double sellGainProfit = 0.0;
   double tickValueLossAtProbe = 0.0;
   double tickValueProfitAtProbe = 0.0;
   double denomBid = bid;
   double denomAsk = ask;
   ResetLastError();
   if(probeTicks > 0.0 && probeTickSize > 0.0 && denomBid > 0.0 && denomAsk > 0.0)
     {
      probeMove = probeTicks * probeTickSize;
      // Re-read both tick values at the same probe moment as the witness.
      tickValueLossAtProbe = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS);
      tickValueProfitAtProbe = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT);
      if(!MathIsValidNumber(probeTicks) || !MathIsValidNumber(probeTickSize)
         || !MathIsValidNumber(denomBid) || !MathIsValidNumber(denomAsk)
         || !MathIsValidNumber(probeMove) || probeMove <= 0.0
         || !MathIsValidNumber(tickValueLossAtProbe)
         || !MathIsValidNumber(tickValueProfitAtProbe)
         || tickValueLossAtProbe < 0.0 || tickValueProfitAtProbe < 0.0)
        {
         denomReason = "invalid denomination probe numeric inputs";
         denomLastError = GetLastError();
        }
      else
        {
         ResetLastError();
         bool buyOk = OrderCalcProfit(ORDER_TYPE_BUY, sym, 1.0, denomAsk,
                                      denomAsk - probeMove, buyLossProfit);
         denomLastError = GetLastError();
         if(!buyOk)
           {
            denomReason = "BUY OrderCalcProfit failed";
           }
         else if(!MathIsValidNumber(buyLossProfit))
           {
            denomReason = "BUY OrderCalcProfit returned invalid profit";
           }
         else if(buyLossProfit >= 0.0)
           {
            denomReason = "BUY OrderCalcProfit returned non-negative loss";
           }
         else
           {
            ResetLastError();
            bool sellOk = OrderCalcProfit(ORDER_TYPE_SELL, sym, 1.0, denomBid,
                                          denomBid - probeMove, sellGainProfit);
            denomLastError = GetLastError();
            if(!sellOk)
              {
               denomReason = "SELL OrderCalcProfit failed";
              }
            else if(!MathIsValidNumber(sellGainProfit))
              {
               denomReason = "SELL OrderCalcProfit returned invalid profit";
              }
            else if(sellGainProfit <= 0.0)
              {
               denomReason = "SELL OrderCalcProfit returned non-positive gain";
              }
            else
              {
               denomOk = buyOk && sellOk && buyLossProfit < 0.0
                         && sellGainProfit > 0.0;
               denomReason = denomOk ? "" : "denomination probe success conditions failed";
              }
           }
        }
     }
   else
     {
      denomReason = "invalid denomination probe inputs or quote";
      denomLastError = GetLastError();
     }

   string j = "{\n";
   j += "  " + JsonQuote("schema") + ": " + JsonQuote("mql5bot.broker_export/1") + ",\n";
   j += "  " + JsonQuote("exported_at") + ": " + JsonQuote(TimeToString(TimeGMT(), TIME_DATE|TIME_SECONDS) + " GMT") + ",\n";
   j += "  " + JsonQuote("account_login") + ": " + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",\n";
   j += "  " + JsonQuote("account_currency") + ": " + JsonQuote(AccountInfoString(ACCOUNT_CURRENCY)) + ",\n";
   j += "  " + JsonQuote("account_margin_mode") + ": " + IntegerToString(AccountInfoInteger(ACCOUNT_MARGIN_MODE)) + ",\n";
   j += "  " + JsonQuote("server") + ": " + JsonQuote(AccountInfoString(ACCOUNT_SERVER)) + ",\n";
   j += "  " + JsonQuote("symbol") + ":\n  {\n";
   j += "    " + JsonQuote("name") + ": " + JsonQuote(sym) + ",\n";
   j += "    " + JsonQuote("path") + ": " + JsonQuote(SymbolInfoString(sym, SYMBOL_PATH)) + ",\n";
   j += "    " + JsonQuote("digits") + ": " + IntegerToString(SymbolInfoInteger(sym, SYMBOL_DIGITS)) + ",\n";
   j += "    " + JsonQuote("point") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_POINT), 12) + ",\n";
   j += "    " + JsonQuote("tick_size") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE), 12) + ",\n";
   j += "    " + JsonQuote("tick_value_profit") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT), 12) + ",\n";
   j += "    " + JsonQuote("tick_value_loss") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS), 12) + ",\n";
   j += "    " + JsonQuote("contract_size") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE), 12) + ",\n";
   j += "    " + JsonQuote("volume_min") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), 12) + ",\n";
   j += "    " + JsonQuote("volume_max") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX), 12) + ",\n";
   j += "    " + JsonQuote("volume_step") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), 12) + ",\n";
   j += "    " + JsonQuote("volume_limit") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_VOLUME_LIMIT), 12) + ",\n";
   j += "    " + JsonQuote("stops_level_points") + ": " + DoubleToString(SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL), 0) + ",\n";
   j += "    " + JsonQuote("freeze_level_points") + ": " + DoubleToString(SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL), 0) + ",\n";
   j += "    " + JsonQuote("spread_points") + ": " + DoubleToString(SymbolInfoInteger(sym, SYMBOL_SPREAD), 0) + ",\n";
   j += "    " + JsonQuote("trade_mode") + ": " + IntegerToString(SymbolInfoInteger(sym, SYMBOL_TRADE_MODE)) + ",\n";
   j += "    " + JsonQuote("filling_mode_mask") + ": " + IntegerToString(filling) + ",\n";
   j += "    " + JsonQuote("order_mode") + ": " + IntegerToString(orderMode) + ",\n";
   j += "    " + JsonQuote("expiration_mode_mask") + ": " + IntegerToString(SymbolInfoInteger(sym, SYMBOL_EXPIRATION_MODE)) + ",\n";
   j += "    " + JsonQuote("currency_profit") + ": " + JsonQuote(SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT)) + ",\n";
   j += "    " + JsonQuote("currency_base") + ": " + JsonQuote(SymbolInfoString(sym, SYMBOL_CURRENCY_BASE)) + ",\n";
   j += "    " + JsonQuote("currency_margin") + ": " + JsonQuote(SymbolInfoString(sym, SYMBOL_CURRENCY_MARGIN)) + ",\n";
   j += "    " + JsonQuote("margin_initial") + ": " + DoubleToString(marginInitial, 12) + ",\n";
   j += "    " + JsonQuote("margin_maintenance") + ": " + DoubleToString(marginMaintenance, 12) + ",\n";
   j += "    " + JsonQuote("swap_long") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_LONG), 12) + ",\n";
   j += "    " + JsonQuote("swap_short") + ": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT), 12) + ",\n";
   j += "    " + JsonQuote("swap_mode") + ": " + IntegerToString(SymbolInfoInteger(sym, SYMBOL_SWAP_MODE)) + ",\n";
   j += "    " + JsonQuote("margin_probe") + ":\n    {\n";
   j += "      " + JsonQuote("ok") + ": " + (probeOk ? "true" : "false") + ",\n";
   j += "      " + JsonQuote("price") + ": " + DoubleToString(mid, 12) + ",\n";
   j += "      " + JsonQuote("buy_1lot") + ": " + DoubleToString(probeMarginBuy, 12) + ",\n";
   j += "      " + JsonQuote("sell_1lot") + ": " + DoubleToString(probeMarginSell, 12) + "\n";
   j += "    },\n";
   j += "    " + JsonQuote("denomination_probe") + ":\n    {\n";
   j += "      " + JsonQuote("ok") + ": " + (denomOk ? "true" : "false") + ",\n";
   j += "      " + JsonQuote("reason") + ": " + JsonQuote(denomReason) + ",\n";
   j += "      " + JsonQuote("last_error") + ": " + IntegerToString(denomLastError) + ",\n";
   j += "      " + JsonQuote("source") + ": " + JsonQuote("OrderCalcProfit") + ",\n";
   j += "      " + JsonQuote("calc_mode") + ": " + IntegerToString(SymbolInfoInteger(sym, SYMBOL_TRADE_CALC_MODE)) + ",\n";
   j += "      " + JsonQuote("account_leverage") + ": " + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE)) + ",\n";
   j += "      " + JsonQuote("account_currency") + ": " + JsonQuote(AccountInfoString(ACCOUNT_CURRENCY)) + ",\n";
   j += "      " + JsonQuote("currency_profit") + ": " + JsonQuote(SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT)) + ",\n";
   j += "      " + JsonQuote("currency_margin") + ": " + JsonQuote(SymbolInfoString(sym, SYMBOL_CURRENCY_MARGIN)) + ",\n";
   j += "      " + JsonQuote("currency_base") + ": " + JsonQuote(SymbolInfoString(sym, SYMBOL_CURRENCY_BASE)) + ",\n";
   j += "      " + JsonQuote("bid") + ": " + (denomOk ? DoubleToString(denomBid, 12) : "null") + ",\n";
   j += "      " + JsonQuote("ask") + ": " + (denomOk ? DoubleToString(denomAsk, 12) : "null") + ",\n";
   j += "      " + JsonQuote("tick_size_at_probe") + ": " + (denomOk ? DoubleToString(probeTickSize, 12) : "null") + ",\n";
   j += "      " + JsonQuote("probe_ticks") + ": " + (denomOk ? DoubleToString(probeTicks, 0) : "null") + ",\n";
   j += "      " + JsonQuote("lot_size") + ": " + (denomOk ? "1.0" : "null") + ",\n";
   j += "      " + JsonQuote("move") + ": " + (denomOk ? DoubleToString(probeMove, 12) : "null") + ",\n";
   j += "      " + JsonQuote("buy_loss_profit") + ": " + (denomOk ? DoubleToString(buyLossProfit, 12) : "null") + ",\n";
   j += "      " + JsonQuote("sell_gain_profit") + ": " + (denomOk ? DoubleToString(sellGainProfit, 12) : "null") + ",\n";
   j += "      " + JsonQuote("tick_value_loss_at_probe") + ": " + (denomOk ? DoubleToString(tickValueLossAtProbe, 12) : "null") + ",\n";
   j += "      " + JsonQuote("tick_value_profit_at_probe") + ": " + (denomOk ? DoubleToString(tickValueProfitAtProbe, 12) : "null") + "\n";
   j += "    }\n";
   j += "  }\n}\n";

   string fname = InpExportDir + sym + ".json";
//--- The export is UTF-8 by contract: tools/broker_symbol_parity.py loads it
//--- with read_text(encoding="utf-8") (no BOM tolerance) and the owner gate
//--- hashes the file bytes, so the encoding is part of the evidence identity.
//--- FileOpen honours its code page ONLY for a FILE_ANSI text file (without
//--- FILE_ANSI a text file is written as UTF-16 + BOM, which that reader
//--- cannot parse), and an unspecified code page means CP_ACP: the machine's
//--- ANSI code page, i.e. the same broker value exporting as different bytes
//--- per Windows locale (U+00D8 -> 0xD8 under CP1252 is not valid UTF-8 and
//--- the export would be skipped as malformed). Signature:
//--- FileOpen(name, flags, delimiter, codepage); the delimiter is unused for
//--- FILE_TXT, so 0 (none) is passed explicitly to reach the code page.
//--- UTF-8 here is BOM-less, which is exactly what the reader expects.
   int fh = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_ANSI, 0, CP_UTF8);
   if(fh == INVALID_HANDLE)
     {
      Print("[mql5bot] export FAILED: cannot open ", fname, " err=", GetLastError());
      return;
     }
   FileWriteString(fh, j);
   FileClose(fh);
   Print("[mql5bot] exported ", sym, " -> MQL5\\Files\\", fname);
  }
//+------------------------------------------------------------------+
//| Script entry                                                     |
//+------------------------------------------------------------------+
void OnStart()
  {
   Main();
  }
