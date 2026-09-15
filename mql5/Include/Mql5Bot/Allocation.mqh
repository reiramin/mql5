//+------------------------------------------------------------------+
//| Allocation.mqh — Meta Layer allocation consumer (contract 1.1.1)  |
//|                                                                   |
//| Reads `in/allocation.json` exactly as written by the Python Meta  |
//| Layer (`mql5bot.meta_layer.write_allocation_file`): a canonical   |
//| JSON document {"body":{...},"digest":"..."} whose body carries    |
//| schema_version "1", computed_at (UTC ISO-8601) and a             |
//| "strategies" array of {"id","weight"} entries.                    |
//|                                                                   |
//| CONTRACT (docs/SPEC.md `in/allocation.json` + Meta Layer v1.1.1): |
//|  * fresh file      -> per-strategy weight is the sizing scale     |
//|  * stale (>7 days) -> decay to the caller's base gate weight      |
//|  * missing/malformed -> SAFE fallback to the base gate weight;    |
//|    a malformed allocation is NEVER applied (digest-verified)      |
//|  * the multiplier can ONLY reduce size: weights are clamped to     |
//|    [0,1]; it never touches SL/TP, risk %, limits or the kill      |
//|    switch — the Risk Engine stays the final authority and the     |
//|    scaled lots still flow through the full risk path.             |
//|                                                                   |
//| This module contains NO order API and MUST NOT gain one.          |
//+------------------------------------------------------------------+
#property copyright "AEGIS"
#property strict

#include <Mql5Bot\Logger.mqh>

#ifndef ALLOCATION_STALE_DAYS
#define ALLOCATION_STALE_DAYS 7        // SPEC: stale > 7 days decays
#endif

#define ALLOC_MAX_ENTRIES 64

enum ENUM_ALLOCATION_STATE
  {
   ALLOC_MISSING = 0,                 // no file / unreadable
   ALLOC_MALFORMED = 1,               // failed strict validation
   ALLOC_STALE = 2,                   // older than ALLOCATION_STALE_DAYS
   ALLOC_FRESH = 3                    // applied
  };

struct SAllocationEntry
  {
   string            id;
   double            weight;
  };

//+---------------------------------------------------------------+
//| Native SHA-256 (MQL5 docs: CryptEncode, CRYPT_HASH_SHA256)     |
//| over the exact UTF-8/ASCII bytes of `text`; lowercase hex out. |
//| Non-ASCII input is refused (the canonical writer is ASCII).    |
//+---------------------------------------------------------------+
bool Sha256Hex(const string text, string &hexOut)
  {
   uchar src[];
   int n = StringToCharArray(text, src, 0, WHOLE_ARRAY, CP_UTF8);
   if(n <= 1)
      return false;                 // empty or encoding failure
   ArrayResize(src, n - 1);         // drop the terminating NUL
   if(ArraySize(src) != StringLen(text))
      return false;                 // non-ASCII body: refuse, never guess
   uchar key[];
   uchar dst[];
   if(CryptEncode(CRYPT_HASH_SHA256, src, key, dst) != 32)
      return false;
   hexOut = "";
   for(int i = 0; i < 32; i++)
      hexOut += StringFormat("%02x", dst[i]);
   return true;
  }

class CAllocation
  {
private:
   SAllocationEntry  m_entries[ALLOC_MAX_ENTRIES];
   int               m_count;
   ENUM_ALLOCATION_STATE m_state;
   datetime          m_lastPoll;
   datetime          m_lastMtime;
   string            m_path;
   string            m_reason;
   CLogger          *m_log;

public:
                     CAllocation(void) : m_count(0),
      m_state(ALLOC_MISSING), m_lastPoll(0), m_lastMtime(0),
      m_path(""), m_reason("not polled"), m_log(NULL) {}

   void              Init(CLogger *log, const string path)
     {
      m_log = log;
      m_path = path;
     }

   ENUM_ALLOCATION_STATE State(void)   const { return m_state; }
   string            Reason(void)      const { return m_reason; }
   int               Count(void)       const { return m_count; }

   //+---------------------------------------------------------------+
   //| OnTimer poll: reload only when the file mtime changed (SPEC:   |
   //| hot-reload by mtime poll in OnTimer).  Errors keep the last    |
   //| applied state but never crash the EA.                          |
   //+---------------------------------------------------------------+
   void              OnTimerPoll(void)
     {
      if(m_path == "" || !FileIsExist(m_path))
        {
         m_state = ALLOC_MISSING;
         m_reason = "file missing";
         return;
        }
      datetime mtime = (datetime)FileGetInteger(m_path, FILE_MODIFY_DATE);
      if(mtime == m_lastMtime)
         return;                               // unchanged: keep state
      m_lastMtime = mtime;
      SAllocationEntry parsed[ALLOC_MAX_ENTRIES];
      string iso = "";
      string why = "";
      int n = 0;
      if(!ParseFile(m_path, parsed, n, iso, why))
        {
         m_state = ALLOC_MALFORMED;            // NEVER apply malformed
         m_reason = why;
         if(m_log != NULL)
            m_log.Error("allocation refused: " + why);
         return;
        }
      for(int i = 0; i < n; i++)
        {
         m_entries[i].id = parsed[i].id;
         m_entries[i].weight = parsed[i].weight;
        }
      m_count = n;
      m_state = IsStale(iso) ? ALLOC_STALE : ALLOC_FRESH;
      m_reason = m_state == ALLOC_STALE ? "older than "
                 + IntegerToString(ALLOCATION_STALE_DAYS) + " days"
                 : "ok";
      if(m_log != NULL)
         m_log.Info(StringFormat("allocation loaded: %d entries (%s)",
                                 m_count, m_reason));
     }

   //+---------------------------------------------------------------+
   //| Effective multiplier for one strategy id.  Only the FRESH      |
   //| state applies file weights; STALE decays to baseGate;          |
   //| MISSING/MALFORMED fall back to baseGate (documented safe       |
   //| fallback — never "last known good weights").                   |
   //+---------------------------------------------------------------+
   //+---------------------------------------------------------------+
   //| Weight for a strategy id under the CURRENT allocation state.   |
   //| FRESH (Meta-authoritative): listed ids get their weight; an    |
   //| UNKNOWN id gets ZERO — a strategy the Meta decision never      |
   //| scored must never trade on baseGate alone (mission rule:       |
   //| unknown id under active meta => no trade).                     |
   //| STALE/MISSING/MALFORMED (Meta not authoritative): the explicit |
   //| baseline policy applies — every id trades on baseGate.         |
   //+---------------------------------------------------------------+
   double            WeightFor(const string id, const double baseGate)
     {
      if(m_state != ALLOC_FRESH)
         return Clamp01(baseGate);
      for(int i = 0; i < m_count; i++)
         if(m_entries[i].id == id)
            return Clamp01(m_entries[i].weight);
      return 0.0;                // unknown id under ACTIVE meta: no trade
     }

   //+---------------------------------------------------------------+
   //| THE ONLY SEAM: scale already-risk-engine-approved lots.        |
   //| Called AFTER RiskManager.GetLots and BEFORE TradeManager —     |
   //| can only reduce, never widen a stop or raise risk.             |
   //+---------------------------------------------------------------+
   double            ScaleLots(const string id, const double lots,
                               const double baseGate)
     {
      double w = WeightFor(id, baseGate);
      return lots * w;
     }

private:
   static double     Clamp01(const double v)
     {
      if(v < 0.0) return 0.0;
      if(v > 1.0) return 1.0;
      return v;
     }

   static bool       IsStale(const string iso)
     {
      datetime computed = ParseIsoUtc(iso);
      if(computed <= 0)
         return true;                        // unparseable time: stale
      return (TimeCurrent() - computed) >
             (datetime)(ALLOCATION_STALE_DAYS * 86400);
     }

   // "YYYY-MM-DDTHH:MM:SS+00:00" (fixed format written by Python)
   static datetime   ParseIsoUtc(const string s)
     {
      if(StringLen(s) < 19)
         return 0;
      MqlDateTime dt;
      dt.year  = (int)StringToInteger(StringSubstr(s, 0, 4));
      dt.mon   = (int)StringToInteger(StringSubstr(s, 5, 2));
      dt.day   = (int)StringToInteger(StringSubstr(s, 8, 2));
      dt.hour  = (int)StringToInteger(StringSubstr(s, 11, 2));
      dt.min   = (int)StringToInteger(StringSubstr(s, 14, 2));
      dt.sec   = (int)StringToInteger(StringSubstr(s, 17, 2));
      if(dt.year < 2000 || dt.mon < 1 || dt.mon > 12 || dt.day < 1
         || dt.day > 31)
         return 0;
      return StructToTime(dt);
     }

   bool              ParseFile(const string path,
                               SAllocationEntry &out[], int &outCount,
                               string &iso, string &why)
     {
      int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
        {
         why = "cannot open";
         return false;
        }
      string json = "";
      while(!FileIsEnding(h))
         json += FileReadString(h);
      FileClose(h);
      return ParseJson(json, out, outCount, iso, why);
     }

   //-- strict scanner for the documented JSON subset -----------------
   int               m_pos;

   void              SkipWs(const string s)
     {
      while(m_pos < StringLen(s))
        {
         ushort c = StringGetCharacter(s, m_pos);
         if(c != ' ' && c != '\t' && c != '\n' && c != '\r')
            break;
         m_pos++;
        }
     }

   bool              Expect(const string s, const ushort c)
     {
      SkipWs(s);
      if(m_pos >= StringLen(s)
         || StringGetCharacter(s, m_pos) != c)
         return false;
      m_pos++;
      return true;
     }

   bool              ParseString(const string s, string &out)
     {
      if(!Expect(s, '"'))
         return false;
      out = "";
      int n = StringLen(s);
      while(m_pos < n)
        {
         ushort c = StringGetCharacter(s, m_pos++);
         if(c == '"')
            return true;
         if(c == '\\')                     // escape (bounded set)
           {
            if(m_pos >= n)
               return false;
            ushort e = StringGetCharacter(s, m_pos++);
            if(e == 'n') out += "\n";
            else if(e == 't') out += "\t";
            else if(e == 'r') out += "\r";
            else if(e == 'u')
              {
               if(m_pos + 4 > n) return false;
               m_pos += 4;                 // ids are ASCII: skip \uXXXX
               out += "?";
              }
            else out += ShortToString(e);
           }
         else
            out += ShortToString(c);
        }
      return false;                        // unterminated string
     }

   bool              ParseNumber(const string s, double &out)
     {
      SkipWs(s);
      int start = m_pos;
      int n = StringLen(s);
      while(m_pos < n)
        {
         ushort c = StringGetCharacter(s, m_pos);
         if((c < '0' || c > '9') && c != '-' && c != '+' && c != '.'
            && c != 'e' && c != 'E')
            break;
         m_pos++;
        }
      if(m_pos == start)
         return false;
      out = StringToDouble(StringSubstr(s, start, m_pos - start));
      return true;
     }

   bool              SkipValue(const string s)
     {
      SkipWs(s);
      int n = StringLen(s);
      if(m_pos >= n)
         return false;
      ushort c = StringGetCharacter(s, m_pos);
      if(c == '"')
        {
         string tmp;
         return ParseString(s, tmp);
        }
      if(c == '{' || c == '[')
        {
         int depth = 0;
         while(m_pos < n)
           {
            ushort d = StringGetCharacter(s, m_pos);
            if(d == '"')                  // skip strings whole
              {
               string tmp;
               if(!ParseString(s, tmp))
                  return false;
               continue;
              }
            if(d == '{' || d == '[')
               depth++;
            else if(d == '}' || d == ']')
              {
               depth--;
               m_pos++;
               if(depth == 0)
                  return true;
               continue;
              }
            m_pos++;
           }
         return false;
        }
      // bare literals: true / false / null / number
      if(StringSubstr(s, m_pos, 4) == "true"
         || StringSubstr(s, m_pos, 5) == "false"
         || StringSubstr(s, m_pos, 4) == "null")
        {
         m_pos += (StringSubstr(s, m_pos, 4) == "false") ? 5 : 4;
         return true;
        }
      double num;
      return ParseNumber(s, num);
     }

   //+---------------------------------------------------------------+
   //| body: schema_version + computed_at + strategies[{id,weight}]   |
   //+---------------------------------------------------------------+
   bool              ParseBody(const string s)
     {
      bool haveVersion = false, haveIso = false;
      bool strategiesDone = false;
      string key = "";
      string iso = "";
      if(!Expect(s, '{'))
         return false;
      // first scan: everything except "strategies"
      while(true)
        {
         if(!Expect(s, '"'))
            return false;
         if(!ParseString(s, key))
            return false;
         if(!Expect(s, ':'))
            return false;
         if(key == "schema_version")
           {
            string v;
            if(!ParseString(s, v) || v != "1")
              {
               m_reason = "schema_version must be \"1\"";
               return false;
              }
            haveVersion = true;
           }
         else if(key == "computed_at")
           {
            if(!ParseString(s, iso))
               return false;
            haveIso = true;
           }
         else if(key == "strategies")
           {
            if(!ParseStrategies(s))
               return false;
            strategiesDone = true;
           }
         else
           {
            if(!SkipValue(s))
               return false;
           }
         SkipWs(s);
         if(m_pos >= StringLen(s))
            return false;
         ushort c = StringGetCharacter(s, m_pos);
         if(c == ',')
           {
            m_pos++;
            continue;
           }
         if(c == '}')
           {
            m_pos++;
            break;
           }
         return false;
        }
      if(!haveVersion || !haveIso || !strategiesDone)
        {
         if(!haveVersion) m_reason = "missing schema_version";
         else if(!haveIso) m_reason = "missing computed_at";
         else m_reason = "missing strategies";
         return false;
        }
      m_iso = iso;
      return m_count > 0 || true;          // empty book is valid: all base
     }

   bool              ParseStrategies(const string s)
     {
      if(!Expect(s, '['))
         return false;
      m_count = 0;
      // empty array -> valid (no entries; base gate applies)
      SkipWs(s);
      if(m_pos < StringLen(s)
         && StringGetCharacter(s, m_pos) == ']')
        {
         m_pos++;
         return true;
        }
      while(true)
        {
         if(!Expect(s, '{'))
            return false;
         string id = "";
         double weight = -1.0;
         string key = "";
         while(true)
           {
            if(!Expect(s, '"') || !ParseString(s, key)
               || !Expect(s, ':'))
               return false;
            if(key == "id")
              {
               if(!ParseString(s, id) || StringLen(id) == 0)
                 {
                  m_reason = "empty strategy id";
                  return false;
                 }
              }
            else if(key == "weight")
              {
               if(!ParseNumber(s, weight))
                 {
                  m_reason = "weight not a number";
                  return false;
                 }
              }
            else
              {
               if(!SkipValue(s))
                  return false;
              }
            SkipWs(s);
            if(m_pos >= StringLen(s))
               return false;
            ushort c = StringGetCharacter(s, m_pos);
            if(c == ',')
              {
               m_pos++;
               continue;
              }
            if(c == '}')
              {
               m_pos++;
               break;
              }
            return false;
           }
         if(weight < 0.0 || weight > 1.0)
           {
            m_reason = "weight out of [0,1] for " + id;
            return false;
           }
         for(int i = 0; i < m_count; i++)
            if(m_entries[i].id == id)
              {
               m_reason = "duplicate strategy id " + id;
               return false;
              }
         if(m_count >= ALLOC_MAX_ENTRIES)
           {
            m_reason = "too many entries";
            return false;
           }
         m_entries[m_count].id = id;
         m_entries[m_count].weight = weight;
         m_count++;
         SkipWs(s);
         if(m_pos >= StringLen(s))
            return false;
         ushort c2 = StringGetCharacter(s, m_pos);
         if(c2 == ',')
           {
            m_pos++;
            continue;
           }
         if(c2 == ']')
           {
            m_pos++;
            return true;
           }
         return false;
        }
      // Unreachable in practice: every iteration of the loop above ends
      // in return/continue. MQL5 still requires every syntactic control
      // path to return a value — fail closed rather than fall through.
      return false;
     }

   string            m_iso;
   string            m_bodySub;     // exact body substring (digest input)
   string            m_digest;      // digest string as written

public:
   //+---------------------------------------------------------------+
   //| Full-document entry: {"body":{...},"digest":"..."} — the       |
   //| digest is CRYPTOGRAPHICALLY VERIFIED against the body bytes    |
   //| with the native CryptEncode(CRYPT_HASH_SHA256) (MQL5 docs,     |
   //| Crypto functions): sha256(exact body substring) must equal the |
   //| digest string, else the document is rejected.  A mutated body  |
   //| under an old digest, a re-digested different body, a malformed |
   //| or missing digest can never be applied.                        |
   //+---------------------------------------------------------------+
   bool              ParseJson(const string s, SAllocationEntry &out[],
                               int &outCount, string &iso, string &why)
     {
      m_pos = 0;
      m_count = 0;
      m_iso = "";
      m_reason = "";
      if(!Expect(s, '{'))
        {
         why = "not a JSON object";
         return false;
        }
      string key = "";
      bool okBody = false, sawBody = false, sawDigest = false;
      while(true)
        {
         if(!Expect(s, '"') || !ParseString(s, key)
            || !Expect(s, ':'))
           {
            why = "malformed member";
            return false;
           }
         if(key == "body")
           {
            // capture the EXACT body substring, then parse it into
            // m_entries/m_iso
            SkipWs(s);
            int bodyStart = m_pos;
            if(!ParseBodyInto(s))
              {
               why = (m_reason == "") ? "malformed body" : m_reason;
               return false;
              }
            m_bodySub = StringSubstr(s, bodyStart, m_pos - bodyStart);
            okBody = true;
            sawBody = true;
           }
         else if(key == "digest")
           {
            string d;
            if(!ParseString(s, d) || StringLen(d) != 64)
              {
               why = "digest missing or not sha256";
               return false;
              }
            for(int hi = 0; hi < 64; hi++)
              {
               ushort hc = StringGetCharacter(d, hi);
               bool hexd = (hc >= '0' && hc <= '9')
                           || (hc >= 'a' && hc <= 'f');
               if(!hexd)
                 {
                  why = "digest malformed (not lowercase hex)";
                  return false;
                 }
              }
            m_digest = d;
            sawDigest = true;
           }
         else
           {
            if(!SkipValue(s))
              {
               why = "unparseable value for " + key;
               return false;
              }
           }
         SkipWs(s);
         if(m_pos >= StringLen(s))
           {
            why = "unterminated object";
            return false;
           }
         ushort c = StringGetCharacter(s, m_pos);
         if(c == ',')
           {
            m_pos++;
            continue;
           }
         if(c == '}')
           {
            m_pos++;
            break;
           }
         why = "expected , or }";
         return false;
        }
      if(!sawBody || !sawDigest || !okBody)
        {
         why = "missing body/digest";
         return false;
        }
      // cryptographic integrity: sha256(body bytes) must equal the digest
      string actualHex = "";
      if(!Sha256Hex(m_bodySub, actualHex))
        {
         why = "digest computation failed (non-ascii body?)";
         return false;
        }
      if(actualHex != m_digest)
        {
         why = "digest mismatch (body/digest inconsistent)";
         return false;
        }
      for(int i = 0; i < m_count; i++)
        {
         out[i].id = m_entries[i].id;
         out[i].weight = m_entries[i].weight;
        }
      outCount = m_count;
      iso = m_iso;
      return true;
     }

private:
   bool              ParseBodyInto(const string s)
     {
      // ParseBody writes into m_entries/m_iso/m_reason/m_count already.
      return ParseBody(s);
     }
  };
//+------------------------------------------------------------------+
