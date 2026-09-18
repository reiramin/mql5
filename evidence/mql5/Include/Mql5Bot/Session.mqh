//+------------------------------------------------------------------+
//|                                            Mql5Bot/Session.mqh   |
//|                    Trading session / time-of-day filter          |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_SESSION_MQH
#define MQL5BOT_SESSION_MQH

#include <Mql5Bot/Config.mqh>

class CSessionFilter
  {
private:
   bool              m_enabled;
   int               m_startHour;
   int               m_startMin;
   int               m_endHour;
   int               m_endMin;
   int               m_daysOfWeek;     // bitmask SESSION_*

   bool              InWindow(datetime time) const
     {
      MqlDateTime st;
      TimeToStruct(time, st);
      int nowMin = st.hour * 60 + st.min;
      int startMin = m_startHour * 60 + m_startMin;
      int endMin   = m_endHour * 60 + m_endMin;
      if(startMin < endMin)
         return nowMin >= startMin && nowMin < endMin;
      // overnight window (e.g. 22:00 -> 06:00)
      return nowMin >= startMin || nowMin < endMin;
     }

public:
                     CSessionFilter() :
                        m_enabled(false), m_startHour(8), m_startMin(0),
                        m_endHour(17), m_endMin(0), m_daysOfWeek(SESSION_WEEKDAYS) {}

   void              Init(bool enabled, int startHour, int startMin,
                          int endHour, int endMin, int daysOfWeek)
     {
      m_enabled    = enabled;
      m_startHour  = MathMax(0, MathMin(23, startHour));
      m_startMin   = MathMax(0, MathMin(59, startMin));
      m_endHour    = MathMax(0, MathMin(23, endHour));
      m_endMin     = MathMax(0, MathMin(59, endMin));
      m_daysOfWeek = daysOfWeek;
     }

   bool              IsEnabled() const { return m_enabled; }

   // true when trading is allowed at the given (server) time
   bool              IsTradingTime(datetime time) const
     {
      if(!m_enabled)
         return true;
      MqlDateTime st;
      TimeToStruct(time, st);
      int dayBit = 1 << st.day_of_week;   // 0=Sunday -> 0x01
      if((m_daysOfWeek & dayBit) == 0)
         return false;
      return InWindow(time);
     }
  };

#endif // MQL5BOT_SESSION_MQH
//+------------------------------------------------------------------+
