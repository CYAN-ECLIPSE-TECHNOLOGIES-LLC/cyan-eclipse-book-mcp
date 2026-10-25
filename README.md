# Eclipse Book MCP

**Powered by Cyan Eclipse Technologies** — https://cetech.ai

**Eclipse Book — market data + venue access layer: exchanges and prediction markets, normalized: one book, one fee truth, one ledger of record.**

> **WORKING NAME — conditional pass.** "Eclipse Book" passed the brand §3 naming test conditionally (spec §3.1): the descriptor above is **mandatory** wherever the name appears, because "book" can echo *bookmaker* — and this product is not one. **Eclipse Book is a market data + venue access layer — not an exchange**: it is not a matching engine, never crosses orders, never holds funds, and takes no other side of any trade. The name never appears shortened in sports contexts (spec §2.3).

## Why this exists

Every price an agent acts on is a fact about **a venue, at a moment, at a depth** — and for event contracts, a fact about a set of words that decide settlement. Raw venue feeds hide all three: fees sit in schedules nobody re-reads, liquidity sits behind a single headline price, and resolution criteria get edited quietly. Book is the normalization + governance core of the Markets suite: one instrument model, one book model, one fee-truth rule, one resolution-verification discipline, one hash-chained ledger — with venue adapters (Forecast, Strike first) that translate and never improvise.

## Status — honest labels

v0.1.0, phase **M0 (Market Core, data only)**. Local stdio transport, Python stdlib only, **no network calls, no accounts, no API keys, no order submission at any tier, and no certification claimed — bench pending.** Own suites: 16/16 tests + stdio smoke passing. Adapters run against fixtures behind transport seams; live venue reads are a later verification step and are labeled `not_tested` in the manifest. Placement is M2 and owner-gated per venue (spec §18, decision D3); withdrawals are T3-always by design when they arrive (§7.3).

## What the core owns

- **Canonical objects** — `Instrument`, `Book`, `Quote`, `Order` (draft records only in M0), `Position`, `Resolution`. Decimal strings end-to-end; no float math on money paths.
- **Native truth preserved (spec §5.2)** — venue statuses that don't map into the core vocabulary surface as `UNMAPPED` with the native string kept, never coerced to the nearest familiar state.
- **Resolution criteria are part of the instrument (§5.4)** — stored **verbatim**, hash-pinned at first read. If a venue edits criteria mid-market, ingest records a `CRITERIA_CHANGED` event with both hashes; a recorded **position keeps the criteria as of its entry** beside the current text, so the change is flagged, never silently absorbed.
- **Fee truth (§5.3)** — every `Quote` carries **all-in** buy/sell cost for a stated size, computed from a **versioned, provenance-stamped fee schedule** (source + fetched-at required). A stale or missing schedule degrades the all-in fields to **`FEE_UNVERIFIED`** rather than quoting a wrong number — a wrong all-in is worse than no number.
- **Resolution lifecycle (§5.4)** — a venue-reported resolution starts `REPORTED` (a claim, not a fact) and becomes `VERIFIED` only when checked against the criteria's **own named source of truth**; any other source is refused by name. `DISPUTED` is a first-class state and blocks verification until the dispute clears.
- **Liquidity + probability honesty (§5.5)** — every Quote carries price, a core-owned `liquidity_flag` (DEEP / FRAGILE / THIN, from notional at best), depth summary, and — for event contracts — the verbatim criteria. **The core never emits a probability field**: a guard scans every quote/position/resolution output and refuses if a probability-shaped key appears. A 0.90 price on $200 of depth renders as price · THIN · $200 at best · criteria attached — an output that cannot be honestly misread as "90% likely."
- **The ledger** — append-only, hash-chained receipts (GENESIS-anchored) for ingests, criteria changes, fee-schedule registrations, position records, drafts, and resolution transitions. Tamper-evident by construction and tested.

## Tools (17, all M0 data/read/record)

`instrument_ingest` · `instrument_get` · `instrument_search` · `book_ingest` · `quote_get` · `fee_schedule_register` · `fee_schedule_get` · `position_open` · `position_list` · `position_get` · `resolution_report` · `resolution_verify` · `resolution_get` · `order_draft` · `order_get` · `venue_status` · `receipt_list`

The denylist is stated in code: `order_place`, `order_submit`, `withdraw`, `account_get`, `create_api_key`, `margin_open`, `recommend`, `probability_get`, and kin return JSON-RPC `-32602` by name. `order_draft` builds an **unsubmitted** DRAFT (MARKET/LIMIT only) whose mandate pre-evaluation honestly reads `NOT_EVALUATED_M0_DATA_ONLY` — the Wallet gate is wired at M2, not simulated here.

## The line (spec §8)

No leverage, margin, or derivatives in v1. No access circumvention. No advice — the suite carries data, records, and (later) the owner's own mandates; recommendation-shaped output is a refused surface, not a disclaimed one. No market abuse, no data resale, no custody: the suite holds credentials (from M1), never assets. This is data and tooling, **not financial advice** — and Test Bench certification, when it comes, will certify normalization, gates, and receipts, never trading outcomes.

## Layout

`server.py` (MCP stdio) · `book_engine.py` (the suite law, imported by adapters) · `fixtures.json` (fee schedules + config seeds) · `tests/` · `smoke.py` · `make_icon.py` / `icon-512.png` (§6).

State: `$ECLIPSE_BOOK_STATE` or `./data/state.json`, shared with the suite's adapters — adapters hold no second copy of the law.

A Cyan Eclipse Technologies product. The "Powered by Cyan Eclipse Technologies" attribution travels with it.
