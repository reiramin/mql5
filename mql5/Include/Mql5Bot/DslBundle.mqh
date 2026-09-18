//+------------------------------------------------------------------+
//|  DslBundle.mqh — fail-closed bundle loader                        |
//|                                                                  |
//|  STATUS: compile-observed on Windows; MQL5<->Python PARITY is     |
//|  OWNER-PENDING until tools/run_dsl_parity.ps1 reports 14/14 EXACT.|
//|                                                                  |
//|  Mirror of python/mql5bot/dsl/bundle.py::load_bundle. Reads a     |
//|  bundle envelope and REFUSES anything it cannot faithfully run:   |
//|                                                                  |
//|   * bundle_hash is RE-DERIVED (canonical JSON via DslCanon.mqh +   |
//|     SHA-256) and compared — presence alone is never enough;       |
//|   * identity.spec_hash / identity.semantic_hash are RE-DERIVED    |
//|     from the bundled spec content and must bind exactly;          |
//|   * indicator_contracts must be present and pin the version this  |
//|     runtime implements for EVERY kind the spec uses;              |
//|   * unresolved ambiguity ANYWHERE in the executable spec refuses; |
//|   * MarketMatches() is the explicit runtime market-compatibility  |
//|     API: the ACTUAL symbol + timeframe must equal the bundle      |
//|     market (§6 — markets are never guessed).                      |
//|                                                                  |
//|  Nothing is repaired, approximated or substituted. A bundle whose |
//|  hash cannot be re-derived (e.g. a number token outside canonical |
//|  repr form) is refused, never accepted.                           |
//+------------------------------------------------------------------+
#ifndef DSL_BUNDLE_MQH
#define DSL_BUNDLE_MQH

#include <Mql5Bot/DslJson.mqh>
#include <Mql5Bot/DslCanon.mqh>

#define DSL_BUNDLE_FORMAT_VERSION    "1.0"
#define DSL_RUNTIME_CONTRACT_VERSION "1.0"
#define DSL_SCHEMA_VERSION           "1.0"

// Indicator kinds this runtime can execute: exactly what the committed
// parity fixtures exercise (EMA/RSI/ATR) plus the canonical channel
// kinds (DONCHIAN/HIGHEST/LOWEST). A bundle that references ANY other
// kind — including SMA/BBANDS/MACD — is REFUSED (never approximated)
// until it is added WITH verified fixture parity. MUST stay in lockstep
// with MQL5_STAGED_RUNTIME_KINDS in python/mql5bot/indicator_universe/
// registry.py (pinned by tests/test_mql5_dsl_runtime_source.py).
string DslSupportedKinds() { return
   "|EMA|RSI|ATR|DONCHIAN|HIGHEST|LOWEST|"; }

// Contract version this runtime implements per supported kind (mirror
// of the Python registry: every baseline kind is version 1). A bundle
// pinning any other version is contract drift and is refused.
int DslKindContractVersion(const string kind)
  {
   if(StringFind(DslSupportedKinds(), "|" + kind + "|") >= 0)
      return 1;
   return -1;
  }

// canonical timeframe name for the market-compatibility check
string DslTimeframeName(const ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M1:  return "M1";
      case PERIOD_M2:  return "M2";
      case PERIOD_M3:  return "M3";
      case PERIOD_M4:  return "M4";
      case PERIOD_M5:  return "M5";
      case PERIOD_M6:  return "M6";
      case PERIOD_M10: return "M10";
      case PERIOD_M12: return "M12";
      case PERIOD_M15: return "M15";
      case PERIOD_M20: return "M20";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H2:  return "H2";
      case PERIOD_H3:  return "H3";
      case PERIOD_H4:  return "H4";
      case PERIOD_H6:  return "H6";
      case PERIOD_H8:  return "H8";
      case PERIOD_H12: return "H12";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN1";
     }
   return "";                       // unknown -> caller must refuse
  }

class CDslBundleLoader
  {
private:
   string            m_error;
   int               m_spec;      // spec object node (valid after Load)
   string            m_symbol;    // bundle market (valid after Load)
   string            m_timeframe;

   bool              Fail(const string msg)
     { m_error = msg; return false; }

   //--- sha256 over the canonical envelope EXCLUDING bundle_hash
   //    (exact mirror of bundle._binding_hash / normalize.canon_json)
   bool              DeriveBundleHash(CDslJson &json, string &out)
     {
      string canon = "", err = "";
      if(!DslCanonObjectExcept(json, json.Root, false, "|bundle_hash|",
                               canon, err))
        { m_error = "bundle_hash underivable: " + err; return false; }
      out = DslSha256Hex(canon);
      if(out == "")
        { m_error = "bundle_hash underivable: sha256 failed"; return false; }
      return true;
     }

   //--- canonical FLOATIFIED semantic core of the spec (normalize:
   //    top-level NON_SEMANTIC keys excluded, every numeric leaf a float)
   bool              DeriveSemanticCore(CDslJson &json, const int spec,
                                        string &canonCore)
     {
      string err = "";
      canonCore = "";
      if(!DslCanonObjectExcept(json, spec, true, DSL_NON_SEMANTIC_KEYS,
                               canonCore, err))
        { m_error = "semantic core underivable: " + err; return false; }
      return true;
     }

   //--- spec_hash input: {"schema_version":…,"semantic":core,
   //    "strategy_id":…,"version":…} (keys already in canonical order)
   bool              DeriveSpecHash(CDslJson &json, const int spec,
                                    const string canonCore, string &out)
     {
      string err = "";
      string ver = DslCanonNumber(
         json.Raw(json.Member(spec, "version")), true, err);
      if(ver == "")
        { m_error = "spec version underivable: " + err; return false; }
      string payload = "{\"schema_version\":"
         + DslCanonEscape(json.GetStr(spec, "schema_version", ""))
         + ",\"semantic\":" + canonCore
         + ",\"strategy_id\":"
         + DslCanonEscape(json.GetStr(spec, "strategy_id", ""))
         + ",\"version\":" + ver + "}";
      out = DslSha256Hex(payload);
      return (out != "");
     }

public:
                     CDslBundleLoader() : m_spec(-1), m_symbol(""),
                                          m_timeframe("") {}
   string            Error() const     { return m_error; }
   int               Spec() const      { return m_spec; }
   string            Symbol() const    { return m_symbol; }
   string            Timeframe() const { return m_timeframe; }

   // json must already be Parse()'d. Returns false + Error() on any
   // fail-closed condition. On success, Spec() is the spec object node.
   bool              Load(CDslJson &json)
     {
      m_error = ""; m_spec = -1; m_symbol = ""; m_timeframe = "";
      int root = json.Root;
      if(json.Type(root) != DSL_JSON_OBJECT)
         return Fail("bundle must be a JSON object");

      if(json.GetStr(root, "bundle_format_version", "")
         != DSL_BUNDLE_FORMAT_VERSION)
         return Fail("unsupported bundle_format_version");
      if(json.GetStr(root, "runtime_contract_version", "")
         != DSL_RUNTIME_CONTRACT_VERSION)
         return Fail("unsupported runtime_contract_version");

      int ident = json.Member(root, "identity");
      if(json.Type(ident) != DSL_JSON_OBJECT)
         return Fail("missing identity block");
      string idKeys[4] = {"strategy_id", "strategy_version", "spec_hash",
                          "semantic_hash"};
      for(int i = 0; i < 4; i++)
         if(json.Member(ident, idKeys[i]) < 0)
            return Fail("identity." + idKeys[i] + " is required");

      int market = json.Member(root, "market");
      if(json.GetStr(market, "symbol", "") == "" ||
         json.GetStr(market, "timeframe", "") == "")
         return Fail("bundle market must specify symbol and timeframe");

      // ---- bundle_hash: RE-DERIVED and compared (tamper check) ----
      if(json.Member(root, "bundle_hash") < 0)
         return Fail("missing bundle_hash");
      string derived = "";
      if(!DeriveBundleHash(json, derived))
         return false;                       // underivable -> refused
      if(derived != json.GetStr(root, "bundle_hash", "#"))
         return Fail("bundle_hash mismatch (tampered or mis-encoded): "
                     "stored " + json.GetStr(root, "bundle_hash", "") +
                     " != computed " + derived);

      int spec = json.Member(root, "spec");
      if(json.Type(spec) != DSL_JSON_OBJECT)
         return Fail("missing spec document");
      if(json.GetStr(spec, "schema_version", "") != DSL_SCHEMA_VERSION)
         return Fail("unsupported spec schema_version");

      // draft / ambiguity refusal: version must be > 0 and no ambiguous
      // markers ANYWHERE in the executable spec (entry, exit, filters,
      // indicators — everywhere; drafts never run)
      if((int)json.GetNum(spec, "version", 0) <= 0)
         return Fail("bundled spec is not executable (version 0 draft)");
      if(HasAmbiguous(json, spec))
         return Fail("bundled spec has unresolved ambiguity");

      // identity must bind the content: re-derive spec/semantic hashes
      string canonCore = "";
      if(!DeriveSemanticCore(json, spec, canonCore))
         return false;
      string semHash = DslSha256Hex(canonCore);
      if(semHash == "" ||
         semHash != json.GetStr(ident, "semantic_hash", "#"))
         return Fail("identity.semantic_hash does not bind the spec "
                     "(re-derived " + semHash + ")");
      string specHash = "";
      if(!DeriveSpecHash(json, spec, canonCore, specHash))
         return Fail("spec_hash underivable");
      if(specHash != json.GetStr(ident, "spec_hash", "#"))
         return Fail("identity.spec_hash does not bind the spec "
                     "(re-derived " + specHash + ")");

      if(json.GetStr(spec, "strategy_id", "")
         != json.GetStr(ident, "strategy_id", "#"))
         return Fail("identity.strategy_id does not match the spec");
      if((int)json.GetNum(spec, "version", -1)
         != (int)json.GetNum(ident, "strategy_version", -2))
         return Fail("identity.strategy_version does not match the spec");

      int specMarket = json.Member(spec, "market");
      if(json.GetStr(market, "symbol", "")
         != json.GetStr(specMarket, "symbol", "#"))
         return Fail("bundle market does not match the spec market");
      if(json.GetStr(market, "timeframe", "")
         != json.GetStr(specMarket, "timeframe", "#"))
         return Fail("bundle market does not match the spec market");

      // every indicator kind must be supported (else refuse, never
      // guess) AND carry a matching indicator_contracts pin
      int contracts = json.Member(root, "indicator_contracts");
      if(json.Type(contracts) != DSL_JSON_ARRAY)
         return Fail("missing indicator_contracts");
      int inds = json.Member(spec, "indicators");
      int c = json.FirstChild(inds);
      while(c >= 0)
        {
         string kind = json.GetStr(c, "kind", "");
         if(StringFind(DslSupportedKinds(), "|" + kind + "|") < 0)
            return Fail("unsupported indicator kind: " + kind);
         // the bundle must pin THIS kind's contract at the version
         // this runtime implements (drift -> refuse)
         bool pinned = false;
         int ct = json.FirstChild(contracts);
         while(ct >= 0)
           {
            if(json.GetStr(ct, "kind", "") == kind)
              {
               pinned = true;
               int pinnedVer = (int)json.GetNum(ct, "version", -1);
               if(pinnedVer != DslKindContractVersion(kind))
                  return Fail("indicator " + kind + " contract drift: "
                              "bundle pinned v" +
                              IntegerToString(pinnedVer) +
                              " but this runtime implements v" +
                              IntegerToString(
                                 DslKindContractVersion(kind)));
               break;
              }
            ct = json.NextSibling(ct);
           }
         if(!pinned)
            return Fail("indicator " + kind +
                        " has no indicator_contracts pin");
         c = json.NextSibling(c);
        }
      // contract entries must all name supported kinds (mirror of the
      // Python unknown-contract refusal)
      int ct2 = json.FirstChild(contracts);
      while(ct2 >= 0)
        {
         string ck = json.GetStr(ct2, "kind", "");
         if(StringFind(DslSupportedKinds(), "|" + ck + "|") < 0)
            return Fail("unknown indicator contract " + ck);
         ct2 = json.NextSibling(ct2);
        }

      m_symbol = json.GetStr(market, "symbol", "");
      m_timeframe = json.GetStr(market, "timeframe", "");
      m_spec = spec;
      return true;
     }

   // ---- explicit runtime market-compatibility API (§6) ----
   // The ACTUAL execution symbol + timeframe MUST equal the bundle
   // market exactly. Call after Load(); false -> the runtime must not
   // evaluate a single bar.
   bool              MarketMatches(const string symbol,
                                   const ENUM_TIMEFRAMES tf)
     {
      if(m_spec < 0)
         return Fail("MarketMatches: no loaded bundle");
      string tfName = DslTimeframeName(tf);
      if(tfName == "")
         return Fail("MarketMatches: unsupported chart timeframe");
      if(symbol != m_symbol || tfName != m_timeframe)
         return Fail("market mismatch: runtime " + symbol + "/" + tfName +
                     " != bundle " + m_symbol + "/" + m_timeframe +
                     " — refusing to run (§6)");
      return true;
     }

   // recursively detect any {"ambiguous": ...} operand in a spec tree
   bool              HasAmbiguous(CDslJson &json, int node)
     {
      if(node < 0) return false;
      if(json.Type(node) == DSL_JSON_OBJECT &&
         json.Member(node, "ambiguous") >= 0)
         return true;
      int c = json.FirstChild(node);
      while(c >= 0)
        {
         if(HasAmbiguous(json, c)) return true;
         c = json.NextSibling(c);
        }
      return false;
     }
  };

#endif // DSL_BUNDLE_MQH
