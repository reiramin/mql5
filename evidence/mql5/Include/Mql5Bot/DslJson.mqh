//+------------------------------------------------------------------+
//|  DslJson.mqh — minimal bounded JSON reader (OWNER-PENDING)        |
//|                                                                  |
//|  STATUS: SOURCE-ONLY, NOT COMPILED. Written on Mac; the owner     |
//|  compiles and verifies (see mql5_dsl_runtime/README.md).          |
//|                                                                  |
//|  A tiny, allocation-bounded JSON parser for reading executable    |
//|  bundles. It is DATA-ONLY: no eval, no code, no file traversal.   |
//|  Hard caps (node count, string length, nesting depth) make node   |
//|  explosion and recursion abuse impossible (mission §24).          |
//+------------------------------------------------------------------+
#ifndef DSL_JSON_MQH
#define DSL_JSON_MQH

#define DSL_JSON_MAX_NODES   20000
#define DSL_JSON_MAX_DEPTH   64
#define DSL_JSON_MAX_STRLEN  4096

enum ENUM_DSL_JSON_TYPE
  {
   DSL_JSON_NULL,
   DSL_JSON_BOOL,
   DSL_JSON_NUMBER,
   DSL_JSON_STRING,
   DSL_JSON_ARRAY,
   DSL_JSON_OBJECT
  };

// A flat node pool: children are referenced by index (no pointers). Each
// object/array node owns a contiguous [firstChild..firstChild+count)
// range in the sibling-linked pool. Keys live on the child nodes.
struct SDslJsonNode
  {
   ENUM_DSL_JSON_TYPE type;
   string            key;        // set when the parent is an object
   string            str;        // DSL_JSON_STRING
   double            num;        // DSL_JSON_NUMBER
   string            raw;        // DSL_JSON_NUMBER: the exact lexical
                                 // token (canonical re-serialization
                                 // hashes THIS, never a re-format)
   bool              boolean;    // DSL_JSON_BOOL
   int               firstChild; // index into pool, or -1
   int               nextSibling;// index into pool, or -1
  };

class CDslJson
  {
private:
   SDslJsonNode      m_pool[];
   int               m_count;
   string            m_src;
   int               m_pos;
   int               m_len;
   string            m_error;

   int               NewNode(ENUM_DSL_JSON_TYPE t)
     {
      if(m_count >= DSL_JSON_MAX_NODES)
        { m_error = "node limit exceeded"; return -1; }
      if(m_count >= ArraySize(m_pool))
         ArrayResize(m_pool, m_count + 256);
      m_pool[m_count].type        = t;
      m_pool[m_count].key         = "";
      m_pool[m_count].str         = "";
      m_pool[m_count].num         = 0.0;
      m_pool[m_count].raw         = "";
      m_pool[m_count].boolean     = false;
      m_pool[m_count].firstChild  = -1;
      m_pool[m_count].nextSibling = -1;
      return m_count++;
     }

   void              SkipWs()
     {
      while(m_pos < m_len)
        {
         ushort c = StringGetCharacter(m_src, m_pos);
         if(c==' '||c=='\t'||c=='\n'||c=='\r') m_pos++;
         else break;
        }
     }

   bool              ParseString(string &out)
     {
      if(StringGetCharacter(m_src, m_pos) != '"')
        { m_error = "expected string"; return false; }
      m_pos++;
      out = "";
      while(m_pos < m_len)
        {
         ushort c = StringGetCharacter(m_src, m_pos++);
         if(c == '"') return true;
         if(StringLen(out) >= DSL_JSON_MAX_STRLEN)
           { m_error = "string too long"; return false; }
         if(c == '\\')
           {
            if(m_pos >= m_len) { m_error="bad escape"; return false; }
            ushort e = StringGetCharacter(m_src, m_pos++);
            if(e=='n') out += "\n";
            else if(e=='t') out += "\t";
            else if(e=='r') out += "\r";
            else if(e=='u')
              {
               // \uXXXX — read 4 hex digits (bounded)
               if(m_pos + 4 > m_len) { m_error="bad \\u"; return false; }
               int code = 0;
               for(int i=0;i<4;i++)
                 {
                  ushort h = StringGetCharacter(m_src, m_pos++);
                  int d = (h>='0'&&h<='9')?(h-'0'):
                          (h>='a'&&h<='f')?(h-'a'+10):
                          (h>='A'&&h<='F')?(h-'A'+10):-1;
                  if(d<0){ m_error="bad hex"; return false; }
                  code = code*16 + d;
                 }
               out += ShortToString((ushort)code);
              }
            else out += ShortToString(e);   // \" \\ \/ etc: literal char
           }
         else
            out += ShortToString(c);
        }
      m_error = "unterminated string";
      return false;
     }

   int               ParseValue(int depth)
     {
      if(depth > DSL_JSON_MAX_DEPTH)
        { m_error = "max depth exceeded"; return -1; }
      SkipWs();
      if(m_pos >= m_len) { m_error="unexpected end"; return -1; }
      ushort c = StringGetCharacter(m_src, m_pos);
      if(c == '{') return ParseObject(depth);
      if(c == '[') return ParseArray(depth);
      if(c == '"')
        {
         int n = NewNode(DSL_JSON_STRING);
         if(n<0) return -1;
         string s; if(!ParseString(s)) return -1;
         m_pool[n].str = s; return n;
        }
      if(c=='t' || c=='f')
        {
         bool v = (c=='t');
         string lit = v ? "true" : "false";
         if(StringSubstr(m_src, m_pos, StringLen(lit)) != lit)
           { m_error="bad literal"; return -1; }
         m_pos += StringLen(lit);
         int n = NewNode(DSL_JSON_BOOL); if(n<0) return -1;
         m_pool[n].boolean = v; return n;
        }
      if(c=='n')
        {
         if(StringSubstr(m_src, m_pos, 4) != "null")
           { m_error="bad literal"; return -1; }
         m_pos += 4; return NewNode(DSL_JSON_NULL);
        }
      // number
      int start = m_pos;
      while(m_pos < m_len)
        {
         ushort d = StringGetCharacter(m_src, m_pos);
         if((d>='0'&&d<='9')||d=='-'||d=='+'||d=='.'||d=='e'||d=='E') m_pos++;
         else break;
        }
      if(m_pos == start) { m_error="bad value"; return -1; }
      int n = NewNode(DSL_JSON_NUMBER); if(n<0) return -1;
      m_pool[n].raw = StringSubstr(m_src, start, m_pos-start);
      m_pool[n].num = StringToDouble(m_pool[n].raw);
      return n;
     }

   int               ParseObject(int depth)
     {
      int node = NewNode(DSL_JSON_OBJECT); if(node<0) return -1;
      m_pos++; // {
      SkipWs();
      int lastChild = -1;
      if(m_pos<m_len && StringGetCharacter(m_src,m_pos)=='}')
        { m_pos++; return node; }
      while(m_pos < m_len)
        {
         SkipWs();
         string key; if(!ParseString(key)) return -1;
         SkipWs();
         if(m_pos>=m_len || StringGetCharacter(m_src,m_pos)!=':')
           { m_error="expected ':'"; return -1; }
         m_pos++;
         int child = ParseValue(depth+1); if(child<0) return -1;
         m_pool[child].key = key;
         if(lastChild<0) m_pool[node].firstChild = child;
         else            m_pool[lastChild].nextSibling = child;
         lastChild = child;
         SkipWs();
         if(m_pos>=m_len){ m_error="unterminated object"; return -1; }
         ushort d = StringGetCharacter(m_src,m_pos++);
         if(d=='}') return node;
         if(d!=','){ m_error="expected ',' or '}'"; return -1; }
        }
      m_error="unterminated object"; return -1;
     }

   int               ParseArray(int depth)
     {
      int node = NewNode(DSL_JSON_ARRAY); if(node<0) return -1;
      m_pos++; // [
      SkipWs();
      int lastChild = -1;
      if(m_pos<m_len && StringGetCharacter(m_src,m_pos)==']')
        { m_pos++; return node; }
      while(m_pos < m_len)
        {
         int child = ParseValue(depth+1); if(child<0) return -1;
         if(lastChild<0) m_pool[node].firstChild = child;
         else            m_pool[lastChild].nextSibling = child;
         lastChild = child;
         SkipWs();
         if(m_pos>=m_len){ m_error="unterminated array"; return -1; }
         ushort d = StringGetCharacter(m_src,m_pos++);
         if(d==']') return node;
         if(d!=','){ m_error="expected ',' or ']'"; return -1; }
        }
      m_error="unterminated array"; return -1;
     }

public:
                     CDslJson() : m_count(0), m_pos(0), m_len(0) {}

   int               Root;

   bool              Parse(const string src)
     {
      m_src = src; m_pos = 0; m_len = StringLen(src);
      m_count = 0; m_error = ""; ArrayResize(m_pool, 256);
      Root = ParseValue(0);
      if(Root < 0) return false;
      SkipWs();
      if(m_pos != m_len) { m_error = "trailing content"; return false; }
      return true;
     }

   string            Error() const { return m_error; }

   // ---- read-only accessors (index-based; -1 == absent) ----
   ENUM_DSL_JSON_TYPE Type(int idx) const
     { return (idx<0)?DSL_JSON_NULL:m_pool[idx].type; }
   double            Num(int idx) const { return (idx<0)?0.0:m_pool[idx].num; }
   string            Str(int idx) const { return (idx<0)?"":m_pool[idx].str; }
   string            Raw(int idx) const { return (idx<0)?"":m_pool[idx].raw; }
   string            Key(int idx) const { return (idx<0)?"":m_pool[idx].key; }
   bool              Bool(int idx) const { return (idx<0)?false:m_pool[idx].boolean; }

   // object member lookup by key
   int               Member(int obj, const string key) const
     {
      if(obj<0 || m_pool[obj].type!=DSL_JSON_OBJECT) return -1;
      int c = m_pool[obj].firstChild;
      while(c>=0)
        {
         if(m_pool[c].key == key) return c;
         c = m_pool[c].nextSibling;
        }
      return -1;
     }

   // array iteration
   int               FirstChild(int idx) const
     { return (idx<0)?-1:m_pool[idx].firstChild; }
   int               NextSibling(int idx) const
     { return (idx<0)?-1:m_pool[idx].nextSibling; }
   int               ArraySizeOf(int idx) const
     {
      int n=0, c=FirstChild(idx);
      while(c>=0){ n++; c=NextSibling(c); }
      return n;
     }

   // convenience typed getters with a default
   string            GetStr(int obj, const string key, const string def) const
     { int m=Member(obj,key); return (m<0)?def:Str(m); }
   double            GetNum(int obj, const string key, double def) const
     { int m=Member(obj,key); return (m<0)?def:Num(m); }
  };

#endif // DSL_JSON_MQH
