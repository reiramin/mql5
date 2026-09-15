//+------------------------------------------------------------------+
//|                                        Mql5Bot/Telemetry.mqh     |
//|     Heartbeat + trade event reporting over plain HTTP POSTs.     |
//|     Point WebhookUrl at your collector (e.g. the Python          |
//|     dashboard bridge in python/mql5bot/telemetry_bridge.py) or   |
//|     any HTTP endpoint (Pipedream, n8n, httpbin for testing).     |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_TELEMETRY_MQH
#define MQL5BOT_TELEMETRY_MQH

#include <Mql5Bot/Config.mqh>

class CTelemetry
  {
private:
   bool              m_enabled;
   string            m_url;
   int               m_timeoutMs;

   string            JsonEscape(string s)
     {
      StringReplace(s, "\\", "\\\\");
      StringReplace(s, "\"", "\\\"");
      StringReplace(s, "\n", " ");
      StringReplace(s, "\r", "");
      return s;
     }

   bool              Post(string payload)
     {
      char   data[];
      char   result[];
      string headers = "Content-Type: application/json\r\n";
      int n = StringToCharArray(payload, data, 0, WHOLE_ARRAY, CP_UTF8) - 1;
      ArrayResize(data, n);
      int res = WebRequest("POST", m_url, headers, m_timeoutMs, data, result, headers);
      return res != -1;
     }

public:
                     CTelemetry() : m_enabled(false), m_timeoutMs(2000) {}

   void              Init(bool enabled, string url, int timeoutMs = 2000)
     {
      m_enabled   = enabled;
      m_url       = url;
      m_timeoutMs = timeoutMs;
     }

   bool              IsEnabled() const { return m_enabled; }

   void              Heartbeat(string symbol, string timeframe,
                               double equity, double balance, double dailyPnl)
     {
      if(!m_enabled)
         return;
      string payload = StringFormat(
         "{\"event\":\"heartbeat\",\"ea\":\"mql5bot\",\"version\":\"%s\","
         "\"symbol\":\"%s\",\"timeframe\":\"%s\",\"time\":%I64u,"
         "\"equity\":%.2f,\"balance\":%.2f,\"daily_pnl\":%.2f}",
         MQL5BOT_VERSION, symbol, timeframe,
         (long)TimeCurrent(), equity, balance, dailyPnl);
      Post(payload);
     }

   void              Trade(string symbol, string action, string strategy,
                          double lots, double price, double pnl, string comment)
     {
      if(!m_enabled)
         return;
      string payload = StringFormat(
         "{\"event\":\"trade\",\"ea\":\"mql5bot\",\"version\":\"%s\","
         "\"symbol\":\"%s\",\"action\":\"%s\",\"strategy\":\"%s\","
         "\"time\":%I64u,\"lots\":%.2f,\"price\":%.5f,\"pnl\":%.2f,"
         "\"comment\":\"%s\"}",
         MQL5BOT_VERSION, symbol, action, strategy,
         (long)TimeCurrent(), lots, price, pnl, JsonEscape(comment));
      Post(payload);
     }

   void              Alert(string level, string message)
     {
      if(!m_enabled)
         return;
      string payload = StringFormat(
         "{\"event\":\"alert\",\"ea\":\"mql5bot\",\"version\":\"%s\","
         "\"level\":\"%s\",\"time\":%I64u,\"message\":\"%s\"}",
         MQL5BOT_VERSION, level, (long)TimeCurrent(), JsonEscape(message));
      Post(payload);
     }
  };

#endif // MQL5BOT_TELEMETRY_MQH
//+------------------------------------------------------------------+
