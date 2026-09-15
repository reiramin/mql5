//+------------------------------------------------------------------+
//|                                        Mql5Bot/StateStore.mqh    |
//| Crash-safe persistence for the fail-safe state machine (SPEC     |
//| §3.5, §8.C, §8.H):                                               |
//|                                                                  |
//| * GlobalVariables carry the HOT state so a restart always sees   |
//|   the kill-switch state, its reason, day-start equity, equity    |
//|   peak and the server day key — a restart NEVER resets the daily |
//|   loss or forgets the drawdown peak (SPEC DoD #13/#14).          |
//| * A strict text file (Files/Mql5Bot/State/state.txt) carries the |
//|   cold state: the ticket registry (POSITION_IDENTIFIER map) with |
//|   per-ticket management flags, so recovery can re-adopt managed  |
//|   positions and rebuild management state after restart (SPEC     |
//|   §3.8, §8.A).                                                   |
//|                                                                  |
//| Format decision (see docs/DECISIONS.md): internal state files    |
//| use a strict line format instead of JSON until the EA<->Factory  |
//| JSON contract ships (which will bring a reviewed JSON writer).   |
//| Reads are strict: any corrupt row is skipped with a warning and  |
//| a corrupt file is renamed aside — never applied partially.       |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_STATESTORE_MQH
#define MQL5BOT_STATESTORE_MQH

#include <Mql5Bot/Config.mqh>

#define STORE_FOLDER      "Mql5Bot\\State\\"
#define STORE_STATE_FILE  "Mql5Bot\\State\\state.txt"
#define STORE_BACKUP_FILE "Mql5Bot\\State\\state.corrupt.txt"

//--- GlobalVariable names (hot state) -------------------------------------+
#define GV_KILL_STATE   "mql5bot.kill_state"
#define GV_KILL_REASON  "mql5bot.kill_reason"
#define GV_DAY_KEY      "mql5bot.day_key"
#define GV_DAY_START    "mql5bot.day_start_equity"
#define GV_EQ_PEAK      "mql5bot.equity_peak"
#define GV_RESET_ACK    "mql5bot.reset_ack"

//--- One managed position record (persisted) ------------------------------+
struct STicketRec
  {
   ulong     ticket;         // POSITION_IDENTIFIER (the ticket itself)
   string    strategyId;     // owning strategy (stable id, not magic)
   string    symbol;
   long      type;           // POSITION_TYPE_BUY / SELL
   double    entry;
   datetime  openTime;
   double    lots;
   bool      partialDone;    // management state rebuilt after restart
   bool      beDone;
                     STicketRec()
     {
      ticket = 0;
      strategyId = "";
      symbol = "";
      type = 0;
      entry = 0.0;
      openTime = 0;
      lots = 0.0;
      partialDone = false;
      beDone = false;
     }
  };

//+------------------------------------------------------------------+
//| Cold state store: ticket registry + flags                        |
//+------------------------------------------------------------------+
class CStateStore
  {
private:
   STicketRec        m_records[];
   bool              m_dirty;
   string            m_lastError;

   int               FindRecord(const ulong ticket) const
     {
      for(int i = 0; i < ArraySize(m_records); i++)
         if(m_records[i].ticket == ticket)
            return i;
      return -1;
     }

   bool              EnsureFolder() const
     {
      return FolderCreate(STORE_FOLDER);
     }

public:
                     CStateStore() : m_dirty(false) { m_lastError = ""; }
   string            LastError() const { return m_lastError; }

   int               Count() const { return ArraySize(m_records); }
   STicketRec        RecordAt(const int i) const
     {
      STicketRec empty;
      return (i >= 0 && i < ArraySize(m_records)) ? m_records[i] : empty;
     }
   bool              HasTicket(const ulong ticket) const
     { return FindRecord(ticket) >= 0; }

   void              Upsert(const STicketRec &rec)
     {
      int i = FindRecord(rec.ticket);
      if(i >= 0)
         m_records[i] = rec;
      else
        {
         int n = ArraySize(m_records);
         ArrayResize(m_records, n + 1);
         m_records[n] = rec;
        }
      m_dirty = true;
     }

   bool              RemoveByTicket(const ulong ticket)
     {
      int i = FindRecord(ticket);
      if(i < 0)
         return false;
      int n = ArraySize(m_records);
      for(int j = i; j < n - 1; j++)
         m_records[j] = m_records[j + 1];
      ArrayResize(m_records, n - 1);
      m_dirty = true;
      return true;
     }

   bool              IsDirty() const { return m_dirty; }
   void              ClearDirty()    { m_dirty = false; }

   //----------------------------------------------------------------
   // Strict text format (see header comment):
   //   AEGIS_STATE v1
   //   T|<ticket>|<strategyId>|<symbol>|<type>|<entry>|<openTime>|<lots>|<partial>|<be>
   //----------------------------------------------------------------
   bool              Save(const string path)
     {
      EnsureFolder();
      // Delete first: FileOpen(FILE_WRITE|FILE_READ) does NOT truncate an
      // existing file, and a shorter new file would leave stale tail rows
      // that a later Load could resurrect as ghost tickets. Delete-then-
      // write is the quarantine-friendly approach (FileMove is not relied
      // upon); a crash between delete and write leaves NO file, which Load
      // treats as an empty registry — recovery re-adopts live positions.
      FileDelete(path);
      int h = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
        {
         m_lastError = "cannot open state file for write";
         return false;
        }
      FileWrite(h, "AEGIS_STATE v1");
      for(int i = 0; i < ArraySize(m_records); i++)
        {
         STicketRec r = m_records[i];
         FileWrite(h, StringFormat("T|%I64u|%s|%s|%d|%.8f|%I64u|%.8f|%d|%d",
                                   r.ticket, r.strategyId, r.symbol,
                                   (int)r.type, r.entry, (ulong)r.openTime,
                                   r.lots, r.partialDone ? 1 : 0,
                                   r.beDone ? 1 : 0));
        }
      FileClose(h);
      m_dirty = false;
      return true;
     }

   bool              Load(const string path)
     {
      if(!FileIsExist(path))
         return false;
      int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
        {
         m_lastError = "cannot open state file for read";
         return false;
        }
      string lines[];
      int count = 0;
      while(!FileIsEnding(h))
        {
         ArrayResize(lines, count + 1);
         lines[count] = FileReadString(h);
         count++;
        }
      FileClose(h);

      if(count < 1 || lines[0] != "AEGIS_STATE v1")
        {
         // corrupt file: quarantine its content, never apply partially
         int bh = FileOpen(STORE_BACKUP_FILE,
                           FILE_WRITE | FILE_READ | FILE_TXT | FILE_ANSI);
         if(bh != INVALID_HANDLE)
           {
            for(int i = 0; i < count; i++)
               FileWrite(bh, lines[i]);
            FileClose(bh);
           }
         FileDelete(path);
         m_lastError = "corrupt state file quarantined";
         return false;
        }
      for(int i = 1; i < count; i++)
        {
         string row = lines[i];
         if(StringSubstr(row, 0, 2) != "T|")
            continue;
         string parts[];
         if(StringSplit(row, '|', parts) != 10)
            continue;                       // malformed row: skip
         STicketRec r;
         r.ticket     = (ulong)StringToInteger(parts[1]);
         r.strategyId = parts[2];
         r.symbol     = parts[3];
         r.type       = (long)StringToInteger(parts[4]);
         r.entry      = StringToDouble(parts[5]);
         r.openTime   = (datetime)StringToInteger(parts[6]);
         r.lots       = StringToDouble(parts[7]);
         r.partialDone= StringToInteger(parts[8]) == 1;
         r.beDone     = StringToInteger(parts[9]) == 1;
         if(r.ticket == 0 || r.symbol == "" || r.strategyId == "")
            continue;
         Upsert(r);
        }
      m_dirty = false;
      return true;
     }
  };

//+------------------------------------------------------------------+
//| Hot state helpers (GlobalVariables)                              |
//| GVs carry doubles only, so the kill-switch REASON is stored as a |
//| bounded integer code; the mapping is fixed and versioned here.   |
//+------------------------------------------------------------------+
enum ENUM_STATE_REASON
  {
   REASON_NONE          = 0,
   REASON_MANUAL        = 1,   // manual trip / explicit reset source
   REASON_MAX_DRAWDOWN  = 2,   // automatic: drawdown kill switch
   REASON_DAILY_LOSS    = 3,   // automatic: daily loss limit
   REASON_SL_GUARD      = 4,   // automatic: SL remediation failed
   REASON_ADOPTED       = 5    // safe mode: adopted position, not secured yet
  };

string StateReasonToString(const int code)
  {
   switch(code)
     {
      case REASON_MANUAL:        return "manual";
      case REASON_MAX_DRAWDOWN:  return "max_drawdown";
      case REASON_DAILY_LOSS:    return "daily_loss";
      case REASON_SL_GUARD:      return "sl_guard";
      case REASON_ADOPTED:       return "adopted_unsafe";
      default:                   return "";
     }
  }

int StateReasonToCode(const string reason)
  {
   if(reason == "manual")         return REASON_MANUAL;
   if(reason == "max_drawdown")   return REASON_MAX_DRAWDOWN;
   if(reason == "daily_loss")     return REASON_DAILY_LOSS;
   if(reason == "sl_guard")       return REASON_SL_GUARD;
   if(reason == "adopted_unsafe") return REASON_ADOPTED;
   return REASON_NONE;
  }

// Persist the hot state. Call on every state change (bounded writes).
void HotStateSave(const ENUM_ENGINE_STATE state, const int reasonCode,
                  const int dayKey, const double dayStart, const double peak)
  {
   GlobalVariableSet(GV_KILL_STATE,  (double)state);
   GlobalVariableSet(GV_KILL_REASON, (double)reasonCode);
   GlobalVariableSet(GV_DAY_KEY,     (double)dayKey);
   GlobalVariableSet(GV_DAY_START,   dayStart);
   GlobalVariableSet(GV_EQ_PEAK,     peak);
  }

// Load the hot state into caller variables. Returns false when nothing
// was ever stored (fresh account) — callers must then use safe defaults.
bool HotStateLoad(ENUM_ENGINE_STATE &state, int &reasonCode,
                  int &dayKey, double &dayStart, double &peak)
  {
   if(!GlobalVariableCheck(GV_KILL_STATE))
      return false;
   state      = (ENUM_ENGINE_STATE)(int)GlobalVariableGet(GV_KILL_STATE);
   reasonCode = (int)GlobalVariableGet(GV_KILL_REASON);
   dayKey     = (int)GlobalVariableGet(GV_DAY_KEY);
   dayStart   = GlobalVariableGet(GV_DAY_START);
   peak       = GlobalVariableGet(GV_EQ_PEAK);
   return true;
  }

#endif // MQL5BOT_STATESTORE_MQH
//+------------------------------------------------------------------+
