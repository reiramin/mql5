//+------------------------------------------------------------------+
//|                                             Mql5Bot/Logger.mqh   |
//|                File + terminal logger with severity levels       |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_LOGGER_MQH
#define MQL5BOT_LOGGER_MQH

#include <Mql5Bot/Config.mqh>

//--- Log levels -----------------------------------------------------+
#define LOG_LEVEL_OFF    0
#define LOG_LEVEL_ERROR  1
#define LOG_LEVEL_INFO   2
#define LOG_LEVEL_DEBUG  3

class CLogger
  {
private:
   int               m_handle;      // log file handle
   int               m_level;       // 0=off 1=error 2=info 3=debug

   void              Write(string level, string msg)
     {
      string line = StringFormat("[%s] [%s] %s",
                                 TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
                                 level, msg);
      Print(line);
      if(m_handle != INVALID_HANDLE)
        {
         // append at end of file
         FileSeek(m_handle, 0, SEEK_END);
         FileWrite(m_handle, line);
         FileFlush(m_handle);
        }
     }

public:
                     CLogger() : m_handle(INVALID_HANDLE), m_level(LOG_LEVEL_INFO) {}
                    ~CLogger()
     {
      if(m_handle != INVALID_HANDLE)
         FileClose(m_handle);
     }

   bool              Init(string folder, string prefix, int level)
     {
      m_level = level;
      if(m_level <= LOG_LEVEL_OFF)
         return true;
      // FolderCreate creates one level; attempt it and continue either way.
      FolderCreate(folder);
      string path = folder + prefix + "_" +
                    TimeToString(TimeCurrent(), TIME_DATE) + ".log";
      m_handle = FileOpen(path, FILE_WRITE | FILE_READ | FILE_TXT | FILE_SHARE_READ);
      if(m_handle == INVALID_HANDLE)
        {
         PrintFormat("[mql5bot] warning: cannot open log file %s (error %d)",
                     path, GetLastError());
         return false;
        }
      return true;
     }

   void              Error(string msg)   { if(m_level >= LOG_LEVEL_ERROR) Write("ERROR", msg); }
   void              Warn(string msg)    { if(m_level >= LOG_LEVEL_INFO)  Write("WARN",  msg); }
   void              Info(string msg)    { if(m_level >= LOG_LEVEL_INFO)  Write("INFO",  msg); }
   void              Debug(string msg)   { if(m_level >= LOG_LEVEL_DEBUG) Write("DEBUG", msg); }

   void              Flush()
     {
      if(m_handle != INVALID_HANDLE)
         FileFlush(m_handle);
     }
  };

#endif // MQL5BOT_LOGGER_MQH
//+------------------------------------------------------------------+
