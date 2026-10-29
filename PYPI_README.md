# cyan-eclipse-book

mcp-name: io.github.CYAN-ECLIPSE-TECHNOLOGIES-LLC/book

**What this is:** the MCP server for **Eclipse Book MCP** - The Market Core of the Eclipse Markets suite (spec eclipse-markets-suite-spec-20261025): one canonical Instrument / Book / Quote / Order / Position / Resolution model over exchanges and prediction markets, with venue adapters that translate and never improvise. Resolution criteria are stored verbatim and hash-pinned — a venue criteria edit is a CRITERIA_CHANGED event and positions keep the criteria as of entry. Quotes carry all-in buy/sell cost for a stated size from versioned, provenance-stamped fee schedules; a stale or missing schedule degrades all-in fields to FEE_UNVERIFIED rather than quoting a wrong number. Resolutions move REPORTED -> VERIFIED only against the criteria's own named source (DISPUTED is first-class), and no core output ever carries a probability field — outputs carry price + liquidity flag + depth + verbatim criteria. M0 is data only: no accounts, no keys, no order submission at any tier; order_draft is an unsubmitted record whose mandate pre-evaluation is honestly NOT_EVALUATED until the owner-gated M2.

## Run it

```console
$ pip install cyan-eclipse-book
$ eclipse-book           # MCP over stdio, Python stdlib only
```

MCP client config:

```json
{ "mcpServers": { "cyan-eclipse-book": { "command": "uvx", "args": ["--from", "cyan-eclipse-book", "eclipse-book"] } } }
```

## Tools (17)

`instrument_ingest` - `instrument_get` - `instrument_search` - `book_ingest` - `quote_get` - `fee_schedule_register` - `fee_schedule_get` - `position_open` - `position_list` - `position_get` - `resolution_report` - `resolution_verify` - `resolution_get` - `order_draft` - `order_get` - `venue_status` - `receipt_list`

## Honest scope

- In development — v0.1.0 M0 local build (Market Core, data only; fixtures behind transport seams; CERTIFIED(local) — Eclipse Bazaar Test Bench 2026-10-25)
- State and runtime data files ship in the wheel beside `server.py`,
  at the same relative paths the server reads them from.

Powered by Cyan Eclipse Technologies LLC (cetech.ai) - a Veteran-Owned
Small Business. MIT licensed.
