# BENCH-VERITY — Cyan Eclipse Book MCP v0.1.0

**Verdict: PASS-WITH-CONDITIONS**
**Scope: local stdio build (working tree of `eclipse-book-mcp`,
v0.1.0, as run from this network seat (VM egress,
America/Los_Angeles host) on 2026-11-02/03.** Bench:
`/tmp/bench-evidence/bench_book.py` — 28 independent checks,
black-box over stdio JSON-RPC; the bench never imports
`book_engine` — fee math, quote fields, criteria hashes and the
receipt chain were recomputed by the bench's own Decimal/sha256
code from raw inputs. Builder's own suites re-run green from a
clean sibling checkout (19/19 unittest + stdio smoke) — baseline
only, not bench evidence. Live venue payloads were fetched by
the bench seat itself from the venues' public APIs (direct
egress, no auth, no accounts, no keys) and fed through the
server's transport seam (`instrument_ingest` / `book_ingest`) —
M0 contains no network code path of its own (verified at source:
no socket/urllib/http code in `server.py` / `book_engine.py`).

## What was verified

- **Handshake + surface (B1–B2).** `initialize` returns
  `eclipse-book` / `0.1.0`; `tools/list` is exactly the 17 M0
  tools the manifest claims — no more, no fewer.
- **Denylist (B3).** 17 forbidden/variant names — `order_place`,
  `withdraw`, `recommend`, `probability_get`, `signal_get`,
  `buy`, `sell`, `account_get`, plus case variants
  (`Order_Place`, `ORDER_SUBMIT`), a separator variant and a
  Cyrillic-confusable `probаbility_get` — all refused with
  JSON-RPC `-32602` by name.
- **Malformed args (B4).** Missing required fields refuse with
  named `ToolError`s (`INSTRUMENT_FIELD_REQUIRED`,
  `RESOLUTION_CRITERIA_REQUIRED`); a missing `size` on
  `quote_get` surfaces a JSON-RPC error and the process stays
  alive and correct afterwards (no crash).
- **Live Kalshi read (B5–B6).** Market `KXFEDDECISION-28JAN-H26`
  fetched live: verbatim `rules_primary` ingested as the
  resolution criteria; the bench's independent sha256 of the
  criteria text matches the stored criteria hash. Kalshi's
  native status `active` — not in the core vocabulary —
  surfaced as `UNMAPPED` with the native string preserved,
  never coerced. The live order book (YES bids as published;
  YES asks derived from NO bids as `1 − price`, the venue's own
  book construction) produced a quote whose bid / ask / mid /
  spread_bps / liquidity flag matched the bench's independent
  recomputation exactly (0.08 / 0.14 / 0.11 / 5454.54… bps /
  THIN — $14.42 notional at best ask). With no Kalshi fee
  schedule registered, the quote carried
  `fee_status: NO_SCHEDULE` and both all-in fields degraded to
  `FEE_UNVERIFIED` — no wrong number quoted. The verbatim
  criteria + its hash ride on the quote.
- **Live Polymarket read (B7).** Gamma market
  `will-gavin-newsom-win-the-2028-democratic-presidential-nomination-568`
  + its live CLOB book (46 levels, returned unsorted by the
  venue) fed raw through `book_ingest`: the core sorted to the
  bench's independently computed best bid 0.157 / best ask
  0.158.
- **Fee truth (B8–B9).** On the bench's own numbers (25 bps,
  100.00/100.50 book, size 40): all-in buy 4030.05 (fee 10.05),
  all-in sell 3990 (fee 10), per-unit figures exact to the
  string; liquidity DEEP at $50,250 notional. A schedule 72 h
  old against a 24 h freshness window → `fee_status: STALE`,
  all-in fields `FEE_UNVERIFIED`. A 0-bps FRESH schedule on the
  live Kalshi book: all-in buy total exactly 1.4 (0.14 × 10,
  fee 0).
- **Probability law (B10, B15).** An ingest carrying
  `provenance.probability_of_yes` was refused
  `PROBABILITY_FIELD_FORBIDDEN` **pre-commit** — no instrument
  persisted, receipt count unchanged (the 2026-10-25 Test Bench
  post-commit observation is closed in this build). A nested,
  capitalized `trading_window.window.Probability` key was
  likewise refused. A scan of all 31 outputs produced during
  the bench found no probability-, recommendation-, signal-,
  advice- or rating-shaped key anywhere.
- **Criteria pinning (B11).** Position opened on the live
  Kalshi instrument; a one-word criteria edit on re-ingest
  produced a `CRITERIA_CHANGED` event (old hash = the live
  rules hash), and the position still carries the as-of-entry
  criteria + hash with `criteria_changed_since_entry: true`.
- **Resolution fences (B12).** `resolution_verify` against a
  wrong source was refused by name
  (`RESOLUTION_SOURCE_MISMATCH`, naming 'Federal Reserve'); an
  open dispute blocked verification (`RESOLUTION_DISPUTED`);
  after `dispute_cleared`, verification against the criteria's
  own named source → `VERIFIED`.
- **Order fence (B13).** `ICEBERG` refused
  (`ORDER_TYPE_NOT_IN_V1_ALLOWLIST`); a LIMIT draft records
  `status: DRAFT`, `mandate_pre_eval:
  NOT_EVALUATED_M0_DATA_ONLY`, with a receipt ref. No
  submission path exists.
- **Ledger (B14).** The bench recomputed the full receipt
  hash chain from the state file with its own implementation —
  12 receipts, chain valid, matching the server's own
  `chain_valid: true`.
- **Venue status (B16).** `capability: M0_DATA_ONLY`,
  `order_tools: ABSENT`, `account_tools: ABSENT`.

## Conditions

- **C-B1 (minor, non-blocking).** `max_payout_for_size` — a
  fee-independent figure (size × $1) — is attached to an
  event-contract quote only when the fee schedule is FRESH;
  under `NO_SCHEDULE` / `STALE` it is omitted along with the
  all-in fields. Absence, never a wrong number — but the
  payout does not depend on the fee schedule and the spec's
  quote shape implies it attaches. Queued as an M1 fix.
- **C-B2 (publish hygiene, non-blocking for use).** Version
  drift: `server.json` reads 0.1.1 while `VERSION`,
  `pyproject.toml` and the server's own version string read
  0.1.0. OWNER-HANDS ship-day step 1 requires agreement before
  tagging; reconcile before the PyPI/MCP-Registry publish.

## Scope fences on this verdict

- PASS-WITH-CONDITIONS covers the M0 data core above: local
  stdio build + live **public reads** from Kalshi and
  Polymarket as ingested through the transport seam from this
  seat on 2026-11-03. Book itself makes no network calls; the
  live step verified is the seam + normalization + law against
  real venue payloads, not a shipped venue adapter.
- NOT_RUN / out of scope, unchanged from the manifest: order
  placement, account reads, the Wallet mandate gate (M2/M1,
  owner-gated, spec §18 D3); fee schedules as live venue data
  (Kalshi's published fee formula is not bps-shaped; no live
  schedule was registered for a venue — venue quotes honestly
  degrade to `FEE_UNVERIFIED`); Polymarket US / Kraken /
  Binance.US / Alpaca chapters (specced, not built).
- The market-data gate fences were probed, not assumed: no
  tool emits a recommendation, signal, ranking or probability
  (B3/B10/B15); copy in README + manifest carries no
  advice-shaped claims.

— Verity bench, 2026-11-02

**Postscript (2026-11-02, ship-day execution).** C-B2
reconciled to 0.1.0 across VERSION / pyproject / server.json
(the MCP Registry already held book@0.1.0, so the registry
snapshot and the package now describe the same build); tree
committed (371b61e) and tag v0.1.0 pushed. The Publish-to-PyPI
run (gh 41557921209) FAILED in the build job's test step —
the test loader assumed the suite's sibling layout, which a
standalone checkout doesn't have — and the publish job never
ran: nothing reached PyPI (verified after the fact via the
JSON API, the simple index, and pip; an interim "uploaded"
reading from this VM's egress was a false signal and is
withdrawn). Loader fixed with an in-repo fallback + the
cross-adapter parity test now skips with a stated reason
when siblings are absent (commit c60ba0d; standalone suite
green: 18 pass + 1 skip; sibling layout 19/19 + smoke).
OWNER-HANDS' Trusted Publisher table also named the wrong
repo (`eclipse-book-mcp`; actual: `cyan-eclipse-book-mcp`) —
corrected in the same commit. Re-run is HELD pending the
owner's delete + re-add of the pending publisher under the
corrected repo name; on his confirmation the v0.1.0 tag
re-points to c60ba0d and the workflow re-runs by dispatch on
that ref.
