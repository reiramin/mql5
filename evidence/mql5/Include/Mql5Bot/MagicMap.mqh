//+------------------------------------------------------------------+
//|                                        Mql5Bot/MagicMap.mqh      |
//| Stable strategy identity (SPEC §3.9):                            |
//|                                                                  |
//|   strategy_id --FNV-1a 32--> slot in reserved magic range        |
//|                                                                  |
//| * magic is derived from a STABLE string id, never from an enum/  |
//|   array index or the position order                              |
//| * a persistent registry keeps id->magic so reloads, removals and |
//|   re-adds never reassign magics (SPEC DoD #21)                   |
//| * collisions probe deterministically to the next free slot       |
//|                                                                  |
//| Numeric contract mirrors python/mql5bot/symbolspec.py so tests   |
//| can pin identical vectors on both sides.                         |
//+------------------------------------------------------------------+
#property strict

#ifndef MQL5BOT_MAGICMAP_MQH
#define MQL5BOT_MAGICMAP_MQH

#include <Mql5Bot/Config.mqh>

#define MAGIC_BASE     16777216    // 0x1000000 (reserved range start)
#define MAGIC_SPAN     1048576     // 0x100000 (2^20 slots)
#define MAGIC_MAX      (MAGIC_BASE + MAGIC_SPAN - 1)

//+------------------------------------------------------------------+
//| FNV-1a 32-bit (UTF-8), unsigned                                  |
//+------------------------------------------------------------------+
uint Fnv1a32(const string text)
  {
   uchar arr[];
   int n = StringToCharArray(text, arr, 0, WHOLE_ARRAY, CP_UTF8);
      uint h = 2166136261;                 // FNV offset basis
      for(int i = 0; i < n - 1; i++)       // exclude the trailing '\0'
        {
         h ^= (uint)arr[i];
         h = (uint)(((ulong)h * 16777619) & 0xFFFFFFFF);   // FNV prime
        }
      return h;
  }

//+------------------------------------------------------------------+
//| Persistent id -> magic registry                                  |
//+------------------------------------------------------------------+
class CMagicMap
  {
private:
   string            m_ids[];
   long              m_magics[];

   int               FindId(const string id) const
     {
      for(int i = 0; i < ArraySize(m_ids); i++)
         if(m_ids[i] == id)
            return i;
      return -1;
     }

   bool              IsTaken(const long magic) const
     {
      for(int i = 0; i < ArraySize(m_magics); i++)
         if(m_magics[i] == magic)
            return true;
      return false;
     }

public:
                     CMagicMap() {}

   int               Total() const { return ArraySize(m_ids); }
   string            IdAt(const int i) const
     { return (i >= 0 && i < ArraySize(m_ids)) ? m_ids[i] : ""; }
   long              MagicAt(const int i) const
     { return (i >= 0 && i < ArraySize(m_magics)) ? m_magics[i] : 0; }

   // Existing magic for an id, or -1 when unknown.
   long              Get(const string id) const
     {
      int i = FindId(id);
      return (i >= 0) ? m_magics[i] : -1;
     }

   // Return the stable magic for `id`, allocating on first use.
   // Deterministic for a given insertion history (registry contract).
   long              Allocate(const string id)
     {
      int known = FindId(id);
      if(known >= 0)
         return m_magics[known];

      long primary = MAGIC_BASE + (long)(Fnv1a32(id) % (uint)MAGIC_SPAN);
      long magic   = primary;
      int  wraps   = 0;
      while(IsTaken(magic))
        {
         magic++;
         if(magic > MAGIC_MAX)
           {
            magic = MAGIC_BASE;         // wrap once around the range
            wraps++;
            if(wraps > 1)
              {
               PrintFormat("[mql5bot] MagicMap: range exhausted for id %s", id);
               return -1;
              }
           }
        }
      ArrayResize(m_ids, ArraySize(m_ids) + 1);
      ArrayResize(m_magics, ArraySize(m_magics) + 1);
      int last = ArraySize(m_ids) - 1;
      m_ids[last]    = id;
      m_magics[last] = magic;
      return magic;
     }

   bool              Remove(const string id)
     {
      int i = FindId(id);
      if(i < 0)
         return false;
      int n = ArraySize(m_ids);
      for(int j = i; j < n - 1; j++)
        {
         m_ids[j]    = m_ids[j + 1];
         m_magics[j] = m_magics[j + 1];
        }
      ArrayResize(m_ids, n - 1);
      ArrayResize(m_magics, n - 1);
      return true;                       // removal never re-allocates others
     }

   //----------------------------------------------------------------
   // Persistence: simple strict text format (no external JSON lib).
   //   line 1: "MAGICMAP v1"
   //   rows  : "<id>=<magic>"
   // Corrupt rows are skipped with a warning; a corrupt file never
   // wipes the in-memory map (caller loads into a fresh map first).
   //----------------------------------------------------------------
   bool              SaveToFile(const string path) const
     {
      // delete-then-write (see StateStore): FILE_WRITE|FILE_READ does not
      // truncate, and stale tail rows would resurrect removed ids on load
      FileDelete(path);
      int h = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return false;
      FileWrite(h, "MAGICMAP v1");
      for(int i = 0; i < ArraySize(m_ids); i++)
         FileWrite(h, m_ids[i] + "=" + IntegerToString(m_magics[i]));
      FileClose(h);
      return true;
     }

   bool              LoadFromFile(const string path)
     {
      if(!FileIsExist(path))
         return false;
      int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return false;
      // read all lines first, close immediately
      string lines[];
      int count = 0;
      while(!FileIsEnding(h))
        {
         ArrayResize(lines, count + 1);
         lines[count] = FileReadString(h);
         count++;
        }
      FileClose(h);

      if(count < 1 || lines[0] != "MAGICMAP v1")
         return false;
      for(int i = 1; i < count; i++)
        {
         string row = lines[i];
         int eq = StringFind(row, "=");
         if(eq <= 0)
            continue;                    // corrupt row: skip, never abort
         string id = StringSubstr(row, 0, eq);
         long magic = (long)StringToInteger(StringSubstr(row, eq + 1));
         if(magic < MAGIC_BASE || magic > MAGIC_MAX)
            continue;
         if(Get(id) >= 0 || IsTaken(magic))
            continue;                    // duplicate: keep first occurrence
         ArrayResize(m_ids, ArraySize(m_ids) + 1);
         ArrayResize(m_magics, ArraySize(m_magics) + 1);
         int last = ArraySize(m_ids) - 1;
         m_ids[last]    = id;
         m_magics[last] = magic;
        }
      return true;
     }
  };

#endif // MQL5BOT_MAGICMAP_MQH
//+------------------------------------------------------------------+
