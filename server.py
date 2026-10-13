#!/usr/bin/env python3
"""RefillRunner MCP server: read-only prescription refill/transfer help + public cash-price benchmarks.
Data: Cost Plus Drugs public pricing API, CMS NADAC (data.medicaid.gov), NPPES NPI Registry, openFDA NDC.
Zero dependencies (Python 3.10+). No auth, no user data stored, no logging. Never orders, refills or contacts a pharmacy."""
import json, os, re, sys, time, difflib, urllib.parse, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
HERE = os.path.dirname(os.path.abspath(__file__))
PHARM = json.load(open(os.path.join(HERE, "pharmacies.json")))
VERSION = "0.1.0"
SUPPORTED = ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"]
RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
NADAC_DS = os.environ.get("NADAC_DATASET", "fbb83258-11c7-47f5-8b18-5f8e79f7e704")  # NADAC 2026
UA = {"User-Agent": "RefillRunner/0.1 (+read-only MCP)"}
_C = {}
def _get(url, ttl=3600):
    hit = _C.get(url)
    if hit and time.time() - hit[0] < ttl: return hit[1]
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r: d = json.loads(r.read())
    _C[url] = (time.time(), d); return d
FETCH = _get  # tests may monkeypatch
TRANSFER_RULES = [
 "Ask the NEW pharmacy to request the transfer; give them your name, date of birth, the medication, and the old pharmacy's name and phone (or the Rx number).",
 "Schedule II controlled substances (e.g. oxycodone, Adderall) have no refills. Since DEA's 2023 rule (21 CFR 1306.08(e)-(g), 88 FR 48379), an UNFILLED electronic Schedule II-V prescription may, at the patient's request, be transferred once between retail pharmacies for initial dispensing, pharmacist-to-pharmacist and in electronic form, where state law allows; otherwise ask your prescriber for a new prescription.",
 "Schedule III-V refills may be transferred one time only between pharmacies, unless the pharmacies share a real-time online database (21 CFR 1306.25).",
 "State law can add restrictions; the pharmacist is the final authority."]
DISC = "Informational only, not medical or pharmacy advice. Prices are public list/benchmark figures, not a quote; confirm with the pharmacy."
def S(props, req=()): return {"type": "object", "properties": props, "required": list(req), "additionalProperties": False}
TOOLS = [
 {"name": "find_refill_steps", "title": "Find refill or transfer steps",
  "description": "Official refill/transfer page for a pharmacy chain (if verified) plus the federal transfer rules (Schedule II cannot be transferred; III-V once). Read-only; never contacts a pharmacy.",
  "inputSchema": S({"pharmacy": {"type": "string", "description": "e.g. 'Walgreens'. Optional."}})},
 {"name": "compare_cash_price", "title": "Compare public cash prices",
  "description": "For a drug name, returns Cost Plus Drugs' published cash price (official public API) and the CMS NADAC average pharmacy acquisition cost per unit as a benchmark. Not a quote; no coupon/discount-card prices.",
  "inputSchema": S({"drug": {"type": "string", "description": "Generic or brand name, e.g. 'atorvastatin'."}, "strength": {"type": "string", "description": "Optional, e.g. '20mg'."}, "quantity": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Units (default 30)."}}, ["drug"])},
 {"name": "find_pharmacies", "title": "Find pharmacies near a ZIP",
  "description": "Licensed pharmacies by ZIP code from the federal NPPES NPI Registry (name, address, phone, NPI). Read-only.",
  "inputSchema": S({"postal_code": {"type": "string", "pattern": "^[0-9]{5}$"}, "name": {"type": "string", "description": "Optional organization name filter, e.g. 'CVS'."}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ["postal_code"])},
 {"name": "lookup_drug", "title": "Look up a drug (FDA NDC)",
  "description": "FDA NDC Directory entries (openFDA) for a drug: brand/generic name, labeler, dosage form, strength, DEA schedule. Useful to check whether it is a controlled substance before a transfer.",
  "inputSchema": S({"drug": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["drug"])},
]
for t in TOOLS: t["annotations"] = {"title": t["title"], **RO}
def _norm(s): return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
def find_refill_steps(a):
    p = _norm(a.get("pharmacy")); out = {"transfer_rules": TRANSFER_RULES, "disclaimer": DISC}
    if not p: out["supported_pharmacies"] = sorted(v["pharmacy"] for v in PHARM.values()); return out
    key = next((k for k, v in PHARM.items() if p in (k, _norm(v["pharmacy"])) or (len(p) >= 4 and (p in _norm(v["pharmacy"]) or k in p))), None)
    if key: out.update(found=True, **PHARM[key])
    else: out.update(found=False, pharmacy=a.get("pharmacy"), advice="No verified page for this pharmacy. Use its app/website or call; the new pharmacy can also request the transfer for you.",
                     suggestions=difflib.get_close_matches(p, list(PHARM), n=2, cutoff=0.5))
    return out
def _cpd(drug, strength):
    d = FETCH("https://api.costplusdrugs.com/pricelist/cpd/search?" + urllib.parse.urlencode({"term": drug}))
    rows = []
    for e in d if isinstance(d, list) else []:
        ch = e.get("cpd_channel") or {}
        if strength and _norm(strength) != _norm(e.get("strength")): continue
        if ch.get("price_per_unit") is None: continue
        rows.append({"name": e.get("medication_name"), "brand_name": e.get("brand_name"), "strength": e.get("strength"), "form": e.get("form"),
                     "price_per_unit": ch["price_per_unit"], "dispensing_fee": ch.get("cash_dispensing_fee"), "in_stock": ch.get("in_stock"), "url": e.get("url")})
    return rows
def _nadac(drug, strength):
    q = f"{drug.upper()}%" if not strength else f"{drug.upper()}%{re.sub(r'(?i)mg', ' MG', strength).upper().replace('  ', ' ').strip()}%"
    qs = urllib.parse.urlencode({"limit": 25, "conditions[0][property]": "ndc_description", "conditions[0][value]": q, "conditions[0][operator]": "LIKE",
                                 "sorts[0][property]": "effective_date", "sorts[0][order]": "desc"})
    d = FETCH(f"https://data.medicaid.gov/api/1/datastore/query/{NADAC_DS}/0?{qs}")
    seen = {}
    for r in d.get("results", []):
        k = r["ndc_description"]
        if k not in seen: seen[k] = {"description": k, "nadac_per_unit": float(r["nadac_per_unit"]), "unit": r.get("pricing_unit"), "effective_date": r.get("effective_date")}
    return list(seen.values())
def compare_cash_price(a):
    drug = (a.get("drug") or "").strip(); strength = a.get("strength"); qty = int(a.get("quantity") or 30)
    if not drug: raise ValueError("drug is required")
    out = {"drug": drug, "quantity": qty, "disclaimer": DISC, "sources": {}}
    try:
        cpd = _cpd(drug, strength)
        for r in cpd: r["est_total_before_shipping"] = round(r["price_per_unit"] * qty + (r["dispensing_fee"] or 0), 2)
        out["cost_plus_drugs"] = cpd[:8]; out["sources"]["cost_plus_drugs"] = "https://api.costplusdrugs.com/pricelist/cpd/search (official public API; shipping extra)"
    except (urllib.error.URLError, ValueError, TimeoutError) as e: out["cost_plus_drugs_error"] = str(e)
    try:
        nd = _nadac(drug, strength)
        for r in nd: r["benchmark_for_quantity"] = round(r["nadac_per_unit"] * qty, 2)
        out["nadac_benchmark"] = nd[:8]; out["sources"]["nadac"] = "CMS NADAC via data.medicaid.gov: average pharmacy ACQUISITION cost, not a retail price"
    except (urllib.error.URLError, ValueError, TimeoutError) as e: out["nadac_error"] = str(e)
    out["not_included"] = "Retail chain cash prices and discount-card (GoodRx etc.) prices: no public licensed API; ask the pharmacy for its cash price."
    return out
def find_pharmacies(a):
    z = a.get("postal_code", "")
    if not re.fullmatch(r"\d{5}", z): raise ValueError("postal_code must be 5 digits")
    p = {"version": "2.1", "taxonomy_description": "Pharmacy", "postal_code": z, "enumeration_type": "NPI-2", "limit": int(a.get("limit") or 10)}
    if a.get("name"): p["organization_name"] = a["name"].strip() + "*"
    d = FETCH("https://npiregistry.cms.hhs.gov/api/?" + urllib.parse.urlencode(p))
    out = []
    for r in d.get("results", []):
        loc = next((x for x in r.get("addresses", []) if x.get("address_purpose") == "LOCATION"), {})
        out.append({"name": r.get("basic", {}).get("organization_name"), "npi": r.get("number"), "address": ", ".join(filter(None, [loc.get("address_1"), loc.get("address_2"), loc.get("city"), loc.get("state"), (loc.get("postal_code") or "")[:5]])), "phone": loc.get("telephone_number")})
    return {"postal_code": z, "count": len(out), "pharmacies": out, "source": "NPPES NPI Registry (CMS)"}
def lookup_drug(a):
    drug = (a.get("drug") or "").strip()
    if not drug: raise ValueError("drug is required")
    s = f'generic_name:"{drug}"+brand_name:"{drug}"'
    try: d = FETCH(f"https://api.fda.gov/drug/ndc.json?search={urllib.parse.quote(s, safe=':+')}&limit={int(a.get('limit') or 5)}")
    except urllib.error.HTTPError as e:
        if e.code == 404: return {"drug": drug, "count": 0, "results": []}
        raise
    res = [{"product_ndc": r.get("product_ndc"), "brand_name": r.get("brand_name"), "generic_name": r.get("generic_name"), "labeler": r.get("labeler_name"),
            "dosage_form": r.get("dosage_form"), "strength": [f"{i.get('name')} {i.get('strength')}" for i in r.get("active_ingredients", [])],
            "dea_schedule": r.get("dea_schedule"), "marketing_category": r.get("marketing_category")} for r in d.get("results", [])]
    return {"drug": drug, "count": len(res), "results": res, "source": "openFDA NDC Directory (unvalidated per openFDA terms)"}
FN = {"find_refill_steps": find_refill_steps, "compare_cash_price": compare_cash_price, "find_pharmacies": find_pharmacies, "lookup_drug": lookup_drug}
def handle(req):
    if not isinstance(req, dict) or req.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    mid, meth, p = req.get("id"), req.get("method"), req.get("params") or {}
    if "id" not in req: return None
    if meth == "initialize":
        v = p.get("protocolVersion"); v = v if v in SUPPORTED else SUPPORTED[0]
        r = {"protocolVersion": v, "capabilities": {"tools": {"listChanged": False}},
             "serverInfo": {"name": "refillrunner", "title": "RefillRunner", "version": VERSION},
             "instructions": "Read-only. Use find_refill_steps for refill/transfer how-to, lookup_drug to check DEA schedule, compare_cash_price for public price benchmarks, find_pharmacies for nearby pharmacies. Always show sources and the disclaimer. Never claim a refill was placed."}
    elif meth == "ping": r = {}
    elif meth == "tools/list": r = {"tools": TOOLS}
    elif meth == "tools/call":
        f = FN.get(p.get("name"))
        if not f: return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {p.get('name')}"}}
        try: data, err = f(p.get("arguments") or {}), False
        except (ValueError, urllib.error.URLError, TimeoutError) as e: data, err = {"error": str(e)}, True
        r = {"content": [{"type": "text", "text": json.dumps(data, indent=1)}], "structuredContent": data, "isError": err}
    else: return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {meth}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": r}
ALLOWED_ORIGINS = [o for o in os.environ.get("REFILLRUNNER_ALLOWED_ORIGINS", "https://claude.ai,https://claude.com,https://grok.com,https://muse.ai").split(",") if o]
class H(BaseHTTPRequestHandler):
    server_version = "refillrunner/" + VERSION
    def _send(self, code, body=None, ctype="application/json"):
        b = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
    def _origin_ok(self):
        o = self.headers.get("Origin")
        return o is None or o in ALLOWED_ORIGINS or o.startswith("http://localhost") or o.startswith("http://127.0.0.1")
    def do_GET(self):
        if self.path == "/healthz": return self._send(200, {"ok": True, "version": VERSION, "pharmacies": len(PHARM)})
        if self.path.startswith("/mcp"): return self._send(405, {"error": "SSE stream not offered; POST JSON-RPC to /mcp"})
        if self.path in ("/", "/privacy"): return self._send(200, open(os.path.join(HERE, "PRIVACY.md"), "rb").read(), "text/markdown; charset=utf-8")
        self._send(404, {"error": "not found"})
    def do_DELETE(self): self._send(405, {"error": "stateless server; no sessions"})
    def do_POST(self):
        if not self.path.startswith("/mcp"): return self._send(404, {"error": "not found"})
        if not self._origin_ok(): return self._send(403, {"error": "origin not allowed"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64_000: return self._send(413, {"error": "payload too large"})
        try: msg = json.loads(self.rfile.read(n) or b"null")
        except json.JSONDecodeError: return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        out = [r for r in (handle(m) for m in msg) if r] if isinstance(msg, list) else handle(msg)
        if not out: return self._send(202)
        self._send(200, out)
if __name__ == "__main__":
    if "--http" in sys.argv:
        h, pt = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8787"))
        print(f"RefillRunner MCP on http://{h}:{pt}/mcp", file=sys.stderr, flush=True); ThreadingHTTPServer((h, pt), H).serve_forever()
    else:
        for line in sys.stdin:
            if not line.strip(): continue
            try: out = handle(json.loads(line))
            except json.JSONDecodeError: out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if out: print(json.dumps(out), flush=True)
