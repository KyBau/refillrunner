# RefillRunner MCP (prototype, read-only)
Claude-first MCP server that helps people refill or transfer a prescription and compare public cash-price benchmarks. Same stack as CancelPath: zero-dependency Python 3.10+, stdio + stateless Streamable HTTP (`POST /mcp`), every tool annotated `readOnlyHint: true`, `destructiveHint: false`.

## Tools
| Tool | Data source |
|---|---|
| `find_refill_steps` | `pharmacies.json` (official chain pages, HTTP-checked 2026-10-13) + federal transfer rules (21 CFR 1306.08(e)-(g) per 88 FR 48379 / 1306.25; verified against eCFR 2026-10-13) |
| `compare_cash_price` | Cost Plus Drugs official public pricing API (`api.costplusdrugs.com/pricelist/cpd/search`) + CMS NADAC 2026 (data.medicaid.gov) |
| `find_pharmacies` | NPPES NPI Registry API (CMS) |
| `lookup_drug` | openFDA NDC Directory (incl. DEA schedule) |

## Run
    python3 server.py            # stdio
    python3 server.py --http     # http://127.0.0.1:8787/mcp
    python3 -m unittest test_server   # offline, mocked upstreams

## Limits (honest)
- No retail chain cash prices and no GoodRx/discount-card prices: no public licensed API found, so none are scraped (GoodRx's terms were not reviewed for this prototype). NADAC is pharmacy acquisition cost, a benchmark, not what a pharmacy charges.
- Refill page list is small (Walgreens transfer, Walmart refill+transfer, Costco, Cost Plus). CVS, Kroger, Amazon Pharmacy pages blocked or 404'd automated checks, so they are not listed rather than guessed.
- Never logs in, refills, or contacts a pharmacy. Not medical advice. Upstream openFDA data is unvalidated per its terms.
- No auth; queries (drug, ZIP) go to the public APIs above. Not deployed (`render.yaml` is ready, free plan).
