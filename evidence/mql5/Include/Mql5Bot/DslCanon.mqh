//+------------------------------------------------------------------+
//|  DslCanon.mqh — canonical JSON serialization + SHA-256           |
//|                                                                  |
//|  STATUS: SOURCE-ONLY, NOT COMPILED. Written on Mac; owner compiles|
//|  and verifies (README.md).                                        |
//|                                                                  |
//|  EXACT mirror of python/mql5bot/dsl/normalize.py::canon_json      |
//|  (json.dumps(obj, sort_keys=True, separators=(",", ":"),          |
//|  ensure_ascii default True)) over a parsed CDslJson tree, plus the |
//|  _floatify mapping used by spec_hash / semantic_hash.             |
//|                                                                  |
//|  Number strategy: every DSL_JSON_NUMBER keeps its exact lexical   |
//|  token from the source (CDslJson.Raw). Bundles are produced by    |
//|  Python json.dumps, whose number tokens ARE the canonical repr    |
//|  form, so re-emitting the raw token reproduces canon_json          |
//|  byte-for-byte. A hand-edited token that deviates from repr form  |
//|  (e.g. "1.00") hashes differently and the bundle is REFUSED —     |
//|  fail closed, never repaired.                                     |
//|                                                                  |
//|  The algorithm is pinned on the Python side by                    |
//|  tests/test_mql5_dsl_runtime_source.py: a Python re-implementation |
//|  of exactly this raw-token strategy must reproduce every golden    |
//|  fixture's bundle_hash / spec_hash / semantic_hash.               |
//+------------------------------------------------------------------+
#ifndef DSL_CANON_MQH
#define DSL_CANON_MQH

#include <Mql5Bot/DslJson.mqh>

// keys excluded from the semantic core (normalize.NON_SEMANTIC)
#define DSL_NON_SEMANTIC_KEYS "|name|description|source|claims|hypothesis|metadata|params|"

//+------------------------------------------------------------------+
//| sha256 hex (lowercase) of a raw byte array                        |
//+------------------------------------------------------------------+
string DslSha256HexBytes(const uchar &bytes[])
  {
   uchar key[], hash[];
   if(!CryptEncode(CRYPT_HASH_SHA256, bytes, key, hash))
      return "";
   string out = "";
   for(int i = 0; i < ArraySize(hash); i++)
      out += StringFormat("%02x", hash[i]);
   return out;
  }

//+------------------------------------------------------------------+
//| sha256 hex (lowercase) of the UTF-8 bytes of s                    |
//+------------------------------------------------------------------+
string DslSha256Hex(const string s)
  {
   uchar bytes[];
   int n = StringToCharArray(s, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(bytes, n - 1);      // drop the trailing '\0'
   else      ArrayResize(bytes, 0);          // empty string hashes fine
   return DslSha256HexBytes(bytes);
  }

//+------------------------------------------------------------------+
//| Python json.dumps string escaping (ensure_ascii=True):            |
//| " and \ escaped; \n \r \t \b \f shorthands; every other char      |
//| < 0x20 or > 0x7e as \uXXXX (lowercase hex, per UTF-16 unit —      |
//| surrogate pairs become two \uXXXX escapes exactly like CPython).  |
//+------------------------------------------------------------------+
string DslCanonEscape(const string s)
  {
   string out = "\"";
   int len = StringLen(s);
   for(int i = 0; i < len; i++)
     {
      ushort c = StringGetCharacter(s, i);
      if(c == '"')       out += "\\\"";
      else if(c == '\\') out += "\\\\";
      else if(c == '\n') out += "\\n";
      else if(c == '\r') out += "\\r";
      else if(c == '\t') out += "\\t";
      else if(c == 8)    out += "\\b";
      else if(c == 12)   out += "\\f";
      else if(c < 0x20 || c > 0x7e)
         out += StringFormat("\\u%04x", c);
      else
         out += ShortToString(c);
     }
   return out + "\"";
  }

//+------------------------------------------------------------------+
//| Canonical number token.                                           |
//| floatify=false: the raw lexical token verbatim (see file header). |
//| floatify=true:  mirror normalize._floatify — an integer token     |
//|   gains ".0" (repr(float(n))); "-0"/"-0.0" become "0.0"; a float  |
//|   token is already repr form and passes through. Tokens this      |
//|   mapping cannot faithfully floatify (>15 integer digits, or an   |
//|   integer written in exponent form) are REFUSED via "" + err.     |
//+------------------------------------------------------------------+
string DslCanonNumber(const string raw, const bool floatify, string &err)
  {
   if(raw == "") { err = "empty number token"; return ""; }
   if(!floatify)
      return raw;
   if(raw == "-0" || raw == "-0.0")
      return "0.0";
   bool hasDot = (StringFind(raw, ".") >= 0);
   bool hasExp = (StringFind(raw, "e") >= 0 || StringFind(raw, "E") >= 0);
   if(hasDot || hasExp)
      return raw;                            // already a float token
   int digits = StringLen(raw);
   if(StringGetCharacter(raw, 0) == '-') digits--;
   if(digits > 15)
     {                                       // float(n) may not be exact:
      err = "integer too large to floatify faithfully: " + raw;
      return "";                             // refuse, never approximate
     }
   return raw + ".0";
  }

//+------------------------------------------------------------------+
//| Ordinal (UTF-16 code-unit) key comparison — matches Python's      |
//| code-point sort for all BMP keys (bundle keys are ASCII).         |
//+------------------------------------------------------------------+
int DslKeyCompare(const string a, const string b)
  {
   int la = StringLen(a), lb = StringLen(b);
   int n = MathMin(la, lb);
   for(int i = 0; i < n; i++)
     {
      ushort ca = StringGetCharacter(a, i);
      ushort cb = StringGetCharacter(b, i);
      if(ca != cb) return (ca < cb) ? -1 : 1;
     }
   if(la == lb) return 0;
   return (la < lb) ? -1 : 1;
  }

bool DslCanonNode(CDslJson &json, const int node, const bool floatify,
                  string &out, string &err);

//+------------------------------------------------------------------+
//| Canonical object with an optional pipe-delimited exclusion list   |
//| ("|bundle_hash|" / DSL_NON_SEMANTIC_KEYS). Keys sorted ordinally. |
//+------------------------------------------------------------------+
bool DslCanonObjectExcept(CDslJson &json, const int obj,
                          const bool floatify, const string excludeKeys,
                          string &out, string &err)
  {
   if(json.Type(obj) != DSL_JSON_OBJECT)
     { err = "canon: not an object"; return false; }
   // collect member indices, skipping excluded keys
   int members[];
   int count = 0;
   int c = json.FirstChild(obj);
   while(c >= 0)
     {
      if(excludeKeys == "" ||
         StringFind(excludeKeys, "|" + json.Key(c) + "|") < 0)
        {
         ArrayResize(members, count + 1);
         members[count++] = c;
        }
      c = json.NextSibling(c);
     }
   // insertion sort by key (bounded: node counts are hard-capped)
   for(int i = 1; i < count; i++)
     {
      int m = members[i];
      int j = i - 1;
      while(j >= 0 && DslKeyCompare(json.Key(members[j]), json.Key(m)) > 0)
        { members[j + 1] = members[j]; j--; }
      members[j + 1] = m;
     }
   out += "{";
   for(int k = 0; k < count; k++)
     {
      if(k > 0) out += ",";
      out += DslCanonEscape(json.Key(members[k])) + ":";
      if(!DslCanonNode(json, members[k], floatify, out, err))
         return false;
     }
   out += "}";
   return true;
  }

//+------------------------------------------------------------------+
//| Canonical serialization of any node (appends to out).             |
//+------------------------------------------------------------------+
bool DslCanonNode(CDslJson &json, const int node, const bool floatify,
                  string &out, string &err)
  {
   switch(json.Type(node))
     {
      case DSL_JSON_NULL:   out += "null";  return true;
      case DSL_JSON_BOOL:   out += (json.Bool(node) ? "true" : "false");
                            return true;
      case DSL_JSON_STRING: out += DslCanonEscape(json.Str(node));
                            return true;
      case DSL_JSON_NUMBER:
        {
         string tok = DslCanonNumber(json.Raw(node), floatify, err);
         if(tok == "") return false;
         out += tok;
         return true;
        }
      case DSL_JSON_ARRAY:
        {
         out += "[";
         int c = json.FirstChild(node);
         bool first = true;
         while(c >= 0)
           {
            if(!first) out += ",";
            first = false;
            if(!DslCanonNode(json, c, floatify, out, err))
               return false;
            c = json.NextSibling(c);
           }
         out += "]";
         return true;
        }
      case DSL_JSON_OBJECT:
         return DslCanonObjectExcept(json, node, floatify, "", out, err);
     }
   err = "canon: unknown node type";
   return false;
  }

#endif // DSL_CANON_MQH
