import json, unittest, server as s
FIX = {
 "costplus": [{"medication_name": "Atorvastatin", "brand_name": "Lipitor", "strength": "20mg", "form": "Tablet", "url": "u",
               "cpd_channel": {"price_per_unit": 0.01, "cash_dispensing_fee": 5, "in_stock": True}},
              {"medication_name": "Atorvastatin", "strength": "40mg", "cpd_channel": {"price_per_unit": 0.02, "cash_dispensing_fee": 5}}],
 "medicaid": {"results": [{"ndc_description": "ATORVASTATIN 20 MG TABLET", "nadac_per_unit": "0.028", "pricing_unit": "EA", "effective_date": "2026-10-07"},
                          {"ndc_description": "ATORVASTATIN 20 MG TABLET", "nadac_per_unit": "0.030", "pricing_unit": "EA", "effective_date": "2026-09-01"}]},
 "npiregistry": {"results": [{"number": "123", "basic": {"organization_name": "TEST RX"}, "addresses": [
     {"address_purpose": "MAILING", "address_1": "PO"}, {"address_purpose": "LOCATION", "address_1": "1 Main", "city": "X", "state": "IL", "postal_code": "606011234", "telephone_number": "555"}]}]},
 "fda": {"results": [{"product_ndc": "1-1", "generic_name": "Oxycodone", "dea_schedule": "CII", "active_ingredients": [{"name": "OXY", "strength": "5 mg/1"}]}]}}
CALLS = []
def fake(url, ttl=0):
    CALLS.append(url)
    for k, v in FIX.items():
        if k in url: return v
    raise AssertionError(url)
s.FETCH = fake
def rpc(m, p=None, i=1): return s.handle({"jsonrpc": "2.0", "id": i, "method": m, "params": p or {}})
def call(n, a): return rpc("tools/call", {"name": n, "arguments": a})["result"]
class T(unittest.TestCase):
    def test_init(self):
        r = rpc("initialize", {"protocolVersion": "2026-07-28"})["result"]
        self.assertEqual(r["protocolVersion"], "2026-07-28"); self.assertEqual(r["serverInfo"]["name"], "refillrunner")
        self.assertEqual(rpc("initialize", {"protocolVersion": "1999"})["result"]["protocolVersion"], s.SUPPORTED[0])
    def test_tools_all_readonly(self):
        tools = rpc("tools/list")["result"]["tools"]; self.assertEqual(len(tools), 4)
        for t in tools:
            self.assertTrue(t["annotations"]["readOnlyHint"]); self.assertFalse(t["annotations"]["destructiveHint"])
            self.assertFalse(t["inputSchema"]["additionalProperties"])
    def test_refill_known_unknown(self):
        r = call("find_refill_steps", {"pharmacy": "Walmart"})["structuredContent"]
        self.assertTrue(r["found"]); self.assertIn("walmart.com", r["transfer_url"]); self.assertTrue(r["transfer_rules"])
        self.assertFalse(call("find_refill_steps", {"pharmacy": "Nowhere Drugs"})["structuredContent"]["found"])
        self.assertIn("supported_pharmacies", call("find_refill_steps", {})["structuredContent"])
    def test_price(self):
        r = call("compare_cash_price", {"drug": "atorvastatin", "strength": "20mg", "quantity": 30})["structuredContent"]
        self.assertEqual(len(r["cost_plus_drugs"]), 1); self.assertEqual(r["cost_plus_drugs"][0]["est_total_before_shipping"], 5.3)
        self.assertEqual(len(r["nadac_benchmark"]), 1); self.assertEqual(r["nadac_benchmark"][0]["nadac_per_unit"], 0.028)
        self.assertIn("ACQUISITION", r["sources"]["nadac"]); self.assertIn("not_included", r)
    def test_price_requires_drug(self): self.assertTrue(call("compare_cash_price", {"drug": " "})["isError"])
    def test_pharmacies(self):
        r = call("find_pharmacies", {"postal_code": "60601", "name": "test"})["structuredContent"]
        self.assertEqual(r["pharmacies"][0]["address"], "1 Main, X, IL, 60601"); self.assertIn("organization_name=test%2A", CALLS[-1])
        self.assertTrue(call("find_pharmacies", {"postal_code": "6060"})["isError"])
    def test_drug(self):
        r = call("lookup_drug", {"drug": "oxycodone"})["structuredContent"]; self.assertEqual(r["results"][0]["dea_schedule"], "CII")
    def test_errors(self):
        self.assertEqual(rpc("tools/call", {"name": "refill_now"})["error"]["code"], -32602)
        self.assertEqual(rpc("nope")["error"]["code"], -32601)
        self.assertIsNone(s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
if __name__ == "__main__": unittest.main()
