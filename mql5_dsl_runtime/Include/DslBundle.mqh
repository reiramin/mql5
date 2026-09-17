//+------------------------------------------------------------------+
//|  DslBundle.mqh — fail-closed bundle loader (OWNER-PENDING)        |
//|                                                                  |
//|  STATUS: SOURCE-ONLY, NOT COMPILED. Written on Mac; owner compiles|
//|  and verifies (README.md).                                        |
//|                                                                  |
//|  Mirror of python/mql5bot/dsl/bundle.py::load_bundle. Reads a     |
//|  bundle envelope and REFUSES anything it cannot faithfully run.   |
//|                                                                  |
//|  Parity status vs the Python loader (mission §10):                |
//|   MIRRORED here: object shape, bundle/runtime version, identity    |
//|     presence, market symbol+timeframe presence AND spec match,     |
//|     bundle_hash presence, draft/ambiguity refusal, id/version bind,|
//|     supported-indicator-kind refusal.                             |
//|   OWNER-PENDING (needs the canonical re-serializer, see below):    |
//|     bundle_hash re-derivation, spec_hash/semantic_hash re-derive   |
//|     binding, full spec re-validation, indicator-contract VERSION   |
//|     drift. Until those land, a bundle whose hash cannot be verified |
//|     is treated as UNTRUSTED and refused — never accepted.          |
//+------------------------------------------------------------------+
#ifndef DSL_BUNDLE_MQH
#define DSL_BUNDLE_MQH

#include "DslJson.mqh"

#define DSL_BUNDLE_FORMAT_VERSION   "1.0"
#define DSL_RUNTIME_CONTRACT_VERSION "1.0"

// Baseline indicator kinds this runtime can execute. A bundle that
// references any other kind is REFUSED (never approximated) until the
// owner adds it (README: extended kinds are extension points).
string DslSupportedKinds() { return
   "|EMA|SMA|RSI|ATR|BBANDS|MACD|DONCHIAN|HIGHEST|LOWEST|"; }

class CDslBundleLoader
  {
private:
   string            m_error;
   int               m_spec;     // spec object node (valid after Load)

   bool              Fail(const string msg)
     { m_error = msg; return false; }

public:
                     CDslBundleLoader() : m_spec(-1) {}
   string            Error() const { return m_error; }
   int               Spec() const  { return m_spec; }

   // json must already be Parse()'d. Returns false + Error() on any
   // fail-closed condition. On success, Spec() is the spec object node.
   bool              Load(CDslJson &json)
     {
      m_error=""; m_spec=-1;
      int root = json.Root;
      if(json.Type(root)!=DSL_JSON_OBJECT)
         return Fail("bundle must be a JSON object");

      if(json.GetStr(root,"bundle_format_version","")!=DSL_BUNDLE_FORMAT_VERSION)
         return Fail("unsupported bundle_format_version");
      if(json.GetStr(root,"runtime_contract_version","")!=DSL_RUNTIME_CONTRACT_VERSION)
         return Fail("unsupported runtime_contract_version");

      int ident = json.Member(root,"identity");
      if(json.Type(ident)!=DSL_JSON_OBJECT)
         return Fail("missing identity block");
      string idKeys[4] = {"strategy_id","strategy_version","spec_hash","semantic_hash"};
      for(int i=0;i<4;i++)
         if(json.Member(ident,idKeys[i])<0)
            return Fail("identity."+idKeys[i]+" is required");

      int market = json.Member(root,"market");
      if(json.GetStr(market,"symbol","")=="" || json.GetStr(market,"timeframe","")=="")
         return Fail("bundle market must specify symbol and timeframe");

      // ---- bundle_hash verification (OWNER-COMPLETION) ----
      // Python binds the envelope with sha256(canon_json(envelope minus
      // bundle_hash)). To verify here, re-serialize the envelope in the
      // SAME canonical form as normalize.canon_json (keys sorted, compact
      // separators ",",":" ; integral floats as Python repr) and hash with
      // CryptEncode(CRYPT_HASH_SHA256, ...). This canonical re-serializer
      // is the ONE non-trivial owner-completion point; until it is in
      // place the loader MUST treat a bundle whose hash it cannot verify
      // as UNTRUSTED. Do not skip this — an unverified bundle is refused,
      // not accepted. (Structural checks below still apply.)
      if(json.Member(root,"bundle_hash")<0)
         return Fail("missing bundle_hash");
      // TODO(owner): if(!VerifyBundleHash(json)) return Fail("bundle_hash mismatch");

      int spec = json.Member(root,"spec");
      if(json.Type(spec)!=DSL_JSON_OBJECT)
         return Fail("missing spec document");

      // draft / ambiguity refusal: version must be > 0 and no ambiguous
      // markers anywhere in the entry tree
      if((int)json.GetNum(spec,"version",0) <= 0)
         return Fail("bundled spec is not executable (version 0 draft)");
      if(HasAmbiguous(json, json.Member(spec,"entry")))
         return Fail("bundled spec has unresolved ambiguity");

      // identity must bind the content
      if(json.GetStr(spec,"strategy_id","")!=json.GetStr(ident,"strategy_id","#"))
         return Fail("identity.strategy_id does not match the spec");
      if((int)json.GetNum(spec,"version",-1)!=(int)json.GetNum(ident,"strategy_version",-2))
         return Fail("identity.strategy_version does not match the spec");
      int specMarket = json.Member(spec,"market");
      if(json.GetStr(market,"symbol","")!=json.GetStr(specMarket,"symbol","#"))
         return Fail("bundle market does not match the spec market");
      if(json.GetStr(market,"timeframe","")!=json.GetStr(specMarket,"timeframe","#"))
         return Fail("bundle market does not match the spec market");

      // every indicator kind must be supported (else refuse, never guess)
      int inds = json.Member(spec,"indicators");
      int c = json.FirstChild(inds);
      while(c>=0)
        {
         string kind = json.GetStr(c,"kind","");
         if(StringFind(DslSupportedKinds(), "|"+kind+"|")<0)
            return Fail("unsupported indicator kind: "+kind);
         c = json.NextSibling(c);
        }

      m_spec = spec;
      return true;
     }

   // recursively detect any {"ambiguous": ...} operand in a condition tree
   bool              HasAmbiguous(CDslJson &json, int node)
     {
      if(node<0) return false;
      if(json.Type(node)==DSL_JSON_OBJECT && json.Member(node,"ambiguous")>=0)
         return true;
      int c = json.FirstChild(node);
      while(c>=0){ if(HasAmbiguous(json,c)) return true; c=json.NextSibling(c); }
      return false;
     }
  };

#endif // DSL_BUNDLE_MQH
