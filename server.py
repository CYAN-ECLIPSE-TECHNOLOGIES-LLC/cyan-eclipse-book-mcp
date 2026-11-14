#!/usr/bin/env python3
# Eclipse Book MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai

"""Eclipse Book MCP — v0.1.0, phase M0 (Market Core, data only).

Powered by Cyan Eclipse Technologies (cetech.ai).

Descriptor (mandatory with the name, spec section 3.1): Eclipse
Book — market data + venue access layer: exchanges and
prediction markets, normalized: one book, one fee truth, one
ledger of record. It is NOT an exchange, not a matching engine,
and never a bookmaker: it holds no funds, crosses no orders,
and takes no other side.

This server owns (spec eclipse-markets-suite-spec-20261025
section 5): the canonical Instrument / Book / Quote / Order /
Position / Resolution objects; resolution criteria stored
VERBATIM + hash-pinned (a criteria edit is a CRITERIA_CHANGED
event; positions keep the criteria as of entry); fee truth
(all-in cost per stated size from versioned, provenance-stamped
fee schedules — a stale schedule degrades the quote to
FEE_UNVERIFIED rather than quoting a wrong number); the
resolution lifecycle (REPORTED -> VERIFIED only against the
criteria's own named source; DISPUTED is first-class); and the
probability law (no core output carries a probability field —
outputs carry price + liquidity flag + depth + criteria ref).

ADAPTER SEAM (M0 fixture form, stated plainly): adapters import
book_engine from this directory and evaluate against the SHARED
suite state file ($ECLIPSE_BOOK_STATE or ./data/state.json
beside this file), loaded fresh at every call. Adapters own
translation from venue-native payloads; the core owns objects,
law, and the ledger.

M0 SCOPE: data only. No accounts, no keys, no order submission
exists in this build at any tier — order_draft produces an
unsubmitted DRAFT record whose mandate pre-evaluation is
honestly NOT_EVALUATED until M2 (owner-gated). No certification
claimed — bench pending.

Transport: MCP over stdio (newline-delimited JSON-RPC 2.0),
stdlib only. State: $ECLIPSE_BOOK_STATE or ./data/state.json,
seeded from fixtures.json.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import book_engine as eng  # noqa: E402
from book_engine import ToolError  # noqa: E402

STATE_PATH = Path(os.environ.get(
    "ECLIPSE_BOOK_STATE", HERE / "data" / "state.json"))
FIXTURES_PATH = HERE / "fixtures.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    state = eng.empty_state()
    seed = json.loads(FIXTURES_PATH.read_text())
    eng.ensure_seeded(state, seed)
    save_state(state)
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


# ------------------------------------------------------------------- tools
def t_instrument_ingest(state, args):
    return eng.ingest_instrument(state, args)


def t_instrument_get(state, args):
    inst = state["instruments"].get(args["instrument_id"])
    if inst is None:
        raise ToolError(f"INSTRUMENT_NOT_FOUND: {args['instrument_id']}")
    return {"instrument": eng.guard_no_probability(inst)}


def t_instrument_search(state, args):
    query = (args.get("query") or "").lower()
    venue = args.get("venue")
    out = []
    for inst in state["instruments"].values():
        if venue and inst["venue"] != venue:
            continue
        if query and query not in inst["title"].lower() \
                and query not in inst["instrument_id"].lower():
            continue
        out.append({"instrument_id": inst["instrument_id"],
                    "venue": inst["venue"], "kind": inst["kind"],
                    "title": inst["title"], "status": inst["status"],
                    "native_status": inst["native_status"],
                    "money_class": inst["money_class"]})
    return {"instruments": out, "count": len(out)}


def t_book_ingest(state, args):
    book = eng.build_book(
        args["instrument_id"], args["venue"],
        args.get("book_type", "CLOB"), args["bids"], args["asks"],
        args["as_of"], tick=args.get("tick"),
        native_ref=args.get("native_ref"))
    book["outcome"] = args.get("outcome")
    return eng.ingest_book(state, book)


def t_quote_get(state, args):
    return {"quote": eng.quote_get(
        state, args["instrument_id"], args["size"],
        outcome=args.get("outcome"), as_of=args.get("as_of"))}


def t_fee_schedule_register(state, args):
    return eng.fee_schedule_register(state, args)


def t_fee_schedule_get(state, args):
    sched, status = eng.fee_freshness(
        state, args["venue"], args.get("as_of") or eng.now_iso())
    if sched is None:
        raise ToolError(f"FEE_SCHEDULE_NOT_FOUND: {args['venue']}")
    return {"fee_schedule": sched, "fee_status": status}


def t_position_open(state, args):
    return eng.position_open(state, args)


def t_position_list(state, args):
    return {"positions": [eng.position_view(state, p)
                          for p in state["positions"].values()],
            "count": len(state["positions"])}


def t_position_get(state, args):
    pos = state["positions"].get(args["position_id"])
    if pos is None:
        raise ToolError(f"POSITION_NOT_FOUND: {args['position_id']}")
    return {"position": eng.position_view(state, pos)}


def t_resolution_report(state, args):
    return eng.resolution_report(state, args)


def t_resolution_verify(state, args):
    return eng.resolution_verify(state, args)


def t_resolution_get(state, args):
    inst = state["instruments"].get(args["instrument_id"])
    if inst is None:
        raise ToolError(f"INSTRUMENT_NOT_FOUND: {args['instrument_id']}")
    return {"resolution": eng.resolution_view(inst)}


def t_order_draft(state, args):
    return eng.order_draft(state, args)


def t_order_get(state, args):
    order = state["orders"].get(args["order_id"])
    if order is None:
        raise ToolError(f"ORDER_NOT_FOUND: {args['order_id']}")
    return {"order": order}


def t_venue_status(state, args):
    return eng.venue_status(state, args["venue"],
                            as_of=args.get("as_of"))


def t_receipt_list(state, args):
    limit = args.get("limit")
    receipts = state["receipts"]
    if limit is not None:
        receipts = receipts[-int(limit):]
    return {"receipts": receipts, "count": len(state["receipts"]),
            "chain_valid": eng.verify_receipt_chain(state["receipts"])}


TOOLS = {
    "instrument_ingest": (
        t_instrument_ingest,
        "Register or refresh a canonical Instrument in the shared "
        "market book from an adapter-normalized venue spec. Use "
        "when a venue adapter has normalized a new or changed "
        "instrument; use instrument_search or instrument_get "
        "instead to read instruments already stored. Mutating and "
        "persistent: writes the instrument to the shared state "
        "file and appends a hash-chained receipt; re-ingesting "
        "the same venue + native_id refreshes status fields in "
        "place under the same core id ('A:<venue>:<native_id>', "
        "or 'B:<venue>:<native_id>' for event contracts). Event "
        "contracts (kind EVENT_CONTRACT or PLAY_EVENT_CONTRACT) "
        "require resolution_criteria carrying verbatim text and "
        "a resolution_source naming the resolver — ingestion is "
        "refused without them. Criteria are hash-pinned at first "
        "ingest; a later ingest with different criteria text "
        "appends a new criteria version and reports a "
        "CRITERIA_CHANGED event instead of silently overwriting. "
        "A status_mapped value outside OPEN|CLOSED|RESOLVED|"
        "VOIDED is stored as UNMAPPED with the native status "
        "preserved, never coerced. Local stdio server: no "
        "network access, no authentication, no rate limits. "
        "Returns {instrument, criteria_changed}, where "
        "criteria_changed is null or the CRITERIA_CHANGED event.",
        {"venue": {"type": "string", "description": "Venue identifier, e.g. 'polymarket_global' or 'coinbase'. Combined with native_id to form the core instrument_id."},
         "native_id": {"type": "string", "description": "The venue's own identifier for the instrument, before normalization."},
         "native_symbol": {"type": "string", "description": "The venue's trading symbol, if it differs from native_id."},
         "kind": {"type": "string", "description": "One of SPOT, EVENT_CONTRACT, EQUITY, PLAY_EVENT_CONTRACT. Event-contract kinds require resolution_criteria and resolution_source."},
         "title": {"type": "string", "description": "Human-readable instrument title; searched by instrument_search."},
         "underlying": {"type": "string", "description": "Underlying asset or subject the instrument references."},
         "outcomes": {"type": "array", "items": {"type": "string"}, "description": "Outcome names for event contracts, e.g. ['YES', 'NO']."},
         "resolution_criteria": {"type": "object", "description": "Object with verbatim criteria 'text' and optional 'source_ref'. Required for event contracts; stored verbatim and hash-pinned."},
         "resolution_source": {"type": "string", "description": "Name of the resolver/source of truth for resolution. Required for event contracts; resolution_verify accepts only this exact source."},
         "trading_window": {"type": "object", "description": "Venue trading-window data, stored as supplied."},
         "tick": {"type": "string", "description": "Minimum price increment as a decimal string, e.g. '0.01'."},
         "min_size": {"type": "string", "description": "Minimum order size as a decimal string."},
         "currency": {"type": "string", "description": "Denomination currency; defaults to 'USD'."},
         "money_class": {"type": "string", "description": "REAL or PLAY; defaults to REAL. PLAY_EVENT_CONTRACT requires PLAY."},
         "native_status": {"type": "string", "description": "The venue's raw status string, preserved verbatim."},
         "status_mapped": {"type": "string", "description": "Status mapped into OPEN, CLOSED, RESOLVED, or VOIDED; anything else is stored as UNMAPPED."},
         "provenance": {"type": "object", "description": "Where the spec came from (adapter, fetch time), stored as supplied."}},
        ["venue", "native_id", "kind", "title"]),
    "instrument_get": (
        t_instrument_get,
        "Fetch one stored canonical Instrument by its core "
        "instrument_id, including its pinned resolution-criteria "
        "versions and current resolution state. Use when you "
        "already know the exact id ('A:<venue>:<native_id>' for "
        "spot/equity, 'B:<venue>:<native_id>' for event "
        "contracts); use instrument_search instead to find "
        "instruments by title or id substring. Read-only: never "
        "writes state or receipts, no authentication. Fails with "
        "INSTRUMENT_NOT_FOUND for an unknown id. Returns "
        "{instrument}.",
        {"instrument_id": {"type": "string", "description": "Core instrument id as returned by instrument_ingest or instrument_search, e.g. 'B:polymarket_global:12345'."}}, ["instrument_id"]),
    "instrument_search": (
        t_instrument_search,
        "Search stored instruments by case-insensitive substring "
        "of title or instrument_id, with an optional exact venue "
        "filter. Use to discover instrument ids when you do not "
        "know the exact core id; use instrument_get when you do. "
        "Read-only and local: searches only instruments already "
        "ingested into this server's state — it never queries a "
        "venue. Both parameters are optional; omitting both lists "
        "every stored instrument. Returns {instruments, count} "
        "with summary rows (instrument_id, venue, kind, title, "
        "status, native_status, money_class), not full "
        "instrument records.",
        {"query": {"type": "string", "description": "Substring matched case-insensitively against title and instrument_id."},
         "venue": {"type": "string", "description": "Exact venue identifier to restrict results to one venue."}}, []),
    "book_ingest": (
        t_book_ingest,
        "Store a canonical order-book snapshot for an "
        "already-ingested instrument, built from normalized "
        "bid/ask levels. Use after instrument_ingest when an "
        "adapter has fresh book data; use quote_get to read "
        "prices computed from the stored book. Mutating and "
        "persistent: replaces the stored snapshot for that "
        "instrument (kept per outcome for event contracts) in "
        "the shared state file. Levels may arrive in any order — "
        "the builder sorts bids descending and asks ascending "
        "and computes spread and depth. Fails with "
        "BOOK_FOR_UNKNOWN_INSTRUMENT if the instrument was never "
        "ingested. Returns {book}.",
        {"instrument_id": {"type": "string", "description": "Core instrument id of an already-ingested instrument."},
         "venue": {"type": "string", "description": "Venue the book came from."},
         "book_type": {"type": "string", "description": "CLOB, AMM, or INDICATIVE; defaults to CLOB."},
         "bids": {"type": "array", "items": {"type": "object"}, "description": "Bid levels as {price, size} objects with decimal-string values, any order."},
         "asks": {"type": "array", "items": {"type": "object"}, "description": "Ask levels as {price, size} objects with decimal-string values, any order."},
         "as_of": {"type": "string", "description": "ISO 8601 timestamp of the snapshot; drives quote_get book-staleness checks."},
         "tick": {"type": "string", "description": "Price tick as a decimal string; enables size-within-5-ticks depth figures."},
         "outcome": {"type": "string", "description": "Event-contract outcome side this book belongs to, e.g. 'YES'."},
         "native_ref": {"type": "string", "description": "Venue-native reference for the snapshot, stored as supplied."}},
        ["instrument_id", "venue", "bids", "asks", "as_of"]),
    "quote_get": (
        t_quote_get,
        "Compute the canonical Quote for an instrument at a "
        "stated size: best bid/ask, computed mid, spread in bps, "
        "liquidity flag and depth, and the all-in buy cost and "
        "sell value from the venue's current fee schedule. Use "
        "for any price or cost question — this is the only "
        "price-shaped output in the server; use instrument_get "
        "for instrument metadata instead. Read-only. All-in "
        "fields are computed only when the fee schedule is "
        "FRESH; a stale or missing schedule returns the literal "
        "string FEE_UNVERIFIED for both all-in fields rather "
        "than a wrong number. Requires a stored two-sided book "
        "(fails BOOK_NOT_FOUND or BOOK_ONE_SIDED otherwise). "
        "For event contracts the quote also carries the verbatim "
        "resolution criteria, its hash, and the named resolution "
        "source. No output ever contains a probability field. "
        "Returns {quote}.",
        {"instrument_id": {"type": "string", "description": "Core instrument id with a stored book."},
         "size": {"type": "string", "description": "Quantity the all-in cost is computed for, as a decimal string, e.g. '100'."},
         "outcome": {"type": "string", "description": "Event-contract outcome side to quote, e.g. 'YES'; omit for single-book instruments."},
         "as_of": {"type": "string", "description": "ISO 8601 evaluation time for fee-freshness and book-staleness; defaults to now."}},
        ["instrument_id", "size"]),
    "fee_schedule_register": (
        t_fee_schedule_register,
        "Register a new versioned fee schedule for a venue so "
        "quote_get can compute all-in costs. Use when a venue "
        "publishes new fees or a stored schedule has gone stale; "
        "use fee_schedule_get to read the current schedule "
        "instead. Mutating and persistent: stores the schedule "
        "under '<venue>@<version>' and appends a hash-chained "
        "receipt. Provenance is mandatory — venue, version, "
        "source, fetched_at, and taker_fee_bps are all required "
        "and registration is refused without them, because a "
        "schedule without provenance is not fee truth. "
        "Registering never edits an existing version in place; "
        "fee_schedule_get picks the version with the newest "
        "fetched_at. Returns {fee_schedule}.",
        {"venue": {"type": "string", "description": "Venue identifier the schedule applies to."},
         "version": {"type": "string", "description": "Schedule version label, e.g. '2026-07-01'; combined with venue as '<venue>@<version>'."},
         "source": {"type": "string", "description": "Provenance: where the schedule was obtained from. Required."},
         "fetched_at": {"type": "string", "description": "ISO 8601 time the schedule was fetched; freshness is measured from here. Required."},
         "taker_fee_bps": {"type": "string", "description": "Taker fee in basis points as a decimal string, e.g. '75' = 0.75%. Required."},
         "maker_fee_bps": {"type": "string", "description": "Maker fee in basis points as a decimal string; defaults to '0'."},
         "settlement_fee_model": {"type": "object", "description": "Settlement fee model object, stored as supplied; defaults to {type: 'none'}."},
         "freshness_hours": {"type": "integer", "description": "Hours after fetched_at before the schedule counts as STALE; defaults to the server config (24)."}},
        ["venue", "version", "source", "fetched_at", "taker_fee_bps"]),
    "fee_schedule_get": (
        t_fee_schedule_get,
        "Return the latest registered fee schedule for a venue "
        "together with its freshness state (FRESH, STALE, or "
        "NO_SCHEDULE) evaluated at as_of. Use before relying on "
        "quote_get all-in costs for a venue, or to check whether "
        "a schedule needs refreshing; use fee_schedule_register "
        "to add a new schedule version. Read-only: never writes "
        "state or receipts, no authentication. Freshness "
        "compares as_of against the schedule's fetched_at plus "
        "its freshness_hours window. Fails with "
        "FEE_SCHEDULE_NOT_FOUND when the venue has no schedule. "
        "Returns {fee_schedule, fee_status}.",
        {"venue": {"type": "string", "description": "Venue identifier to look up."},
         "as_of": {"type": "string", "description": "ISO 8601 evaluation time; defaults to now."}},
        ["venue"]),
    "position_open": (
        t_position_open,
        "Record a new Position in the local book, snapshotting "
        "the instrument's resolution criteria exactly as of "
        "entry. Use when a position has been taken at a venue "
        "and must be tracked against pinned criteria; use "
        "position_list or position_get to read positions back. "
        "Mutating and persistent: assigns the next position id "
        "(pos-N), stores the record, and appends a hash-chained "
        "receipt. This records a position — it does not execute "
        "a trade, contact a venue, or move funds; this server "
        "holds no funds and has no order-submission path. Fails "
        "with INSTRUMENT_NOT_FOUND for an unknown instrument_id. "
        "Returns {position} in position-view form (entry "
        "criteria beside current criteria).",
        {"instrument_id": {"type": "string", "description": "Core instrument id the position is in."},
         "size": {"type": "string", "description": "Position size as a decimal string."},
         "entry_price": {"type": "string", "description": "All-in per-unit cost at entry, as a decimal string, stored as supplied."},
         "outcome": {"type": "string", "description": "Event-contract outcome side held, e.g. 'YES'."},
         "account_ref": {"type": "string", "description": "Free-form account label for the record; defaults to 'owner'."}},
        ["instrument_id", "size", "entry_price"]),
    "position_list": (
        t_position_list,
        "List every recorded Position in the book, each shown "
        "with its criteria-as-of-entry beside the current "
        "criteria, a criteria_changed_since_entry flag, and the "
        "instrument's resolution state. Use for a full position "
        "overview; use position_get for one known position_id. "
        "Read-only, takes no parameters, and is not paginated — "
        "it returns all recorded positions. Positions are local "
        "records of positions taken elsewhere; this server holds "
        "no funds and executes nothing. Returns {positions, "
        "count}.",
        {}, []),
    "position_get": (
        t_position_get,
        "Fetch one recorded Position by position_id, showing the "
        "resolution criteria as of entry beside the current "
        "criteria plus a criteria_changed_since_entry flag and "
        "the instrument's resolution state. Use for a single "
        "known position; use position_list to see every recorded "
        "position. Read-only: a position here is a local record, "
        "not a live venue holding, and fetching it changes "
        "nothing. Fails with POSITION_NOT_FOUND for an unknown "
        "id. Returns {position}.",
        {"position_id": {"type": "string", "description": "Position id as returned by position_open, e.g. 'pos-1'."}}, ["position_id"]),
    "resolution_report": (
        t_resolution_report,
        "Record a venue-reported resolution outcome for an "
        "instrument, moving its resolution state to REPORTED, or "
        "mark it DISPUTED by passing disputed=true. Use when a "
        "venue announces an outcome or a dispute opens; use "
        "resolution_verify to promote a report to VERIFIED, and "
        "resolution_get to read the current state. Mutating and "
        "persistent: updates the instrument's resolution record, "
        "appends to its history, and emits a hash-chained "
        "receipt. A report is a claim, not a verified fact — "
        "state becomes VERIFIED only through resolution_verify "
        "against the criteria's own named source. A report on an "
        "already-VERIFIED instrument does not demote it (only a "
        "dispute flag changes its state). Returns {resolution}.",
        {"instrument_id": {"type": "string", "description": "Core instrument id being resolved."},
         "outcome": {"type": "string", "description": "The reported winning outcome, e.g. 'YES'. Required."},
         "source": {"type": "string", "description": "Who reported the outcome, recorded verbatim."},
         "evidence_ref": {"type": "string", "description": "Reference to the evidence for the report (URL, document id), recorded verbatim."},
         "disputed": {"type": "boolean", "description": "Pass true to mark the resolution DISPUTED instead of REPORTED."}},
        ["instrument_id", "outcome"]),
    "resolution_verify": (
        t_resolution_verify,
        "Promote an instrument's resolution from REPORTED to "
        "VERIFIED by checking it against the resolution source "
        "named in the instrument's own criteria. Use after "
        "resolution_report records an outcome; use "
        "resolution_get to inspect state without changing it. "
        "Mutating and persistent on success: sets state "
        "VERIFIED, records criteria_match, appends history, and "
        "emits a hash-chained receipt. Verification naming any "
        "source other than the criteria's named source is "
        "refused with RESOLUTION_SOURCE_MISMATCH; verifying "
        "before any report fails with RESOLUTION_NOT_REPORTED; "
        "an open DISPUTED state blocks verification unless "
        "dispute_cleared=true. Returns {resolution}.",
        {"instrument_id": {"type": "string", "description": "Core instrument id to verify."},
         "verification_source": {"type": "string", "description": "Must exactly equal the instrument's named resolution_source or verification is refused."},
         "criteria_match": {"type": "boolean", "description": "Whether the reported outcome matches the criteria as written; defaults to true."},
         "dispute_cleared": {"type": "boolean", "description": "Pass true to verify despite an open dispute, recording that the dispute was cleared."}},
        ["instrument_id", "verification_source"]),
    "resolution_get": (
        t_resolution_get,
        "Read an instrument's Resolution record: state (NONE, "
        "REPORTED, VERIFIED, or DISPUTED), reported outcome, "
        "sources, evidence ref, criteria-match flag, and full "
        "history. Use to check where a resolution stands; use "
        "resolution_report to record a report or dispute and "
        "resolution_verify to verify one. Read-only. An "
        "unverified state is data, not fact — only VERIFIED "
        "means the outcome was checked against the criteria's "
        "own named source. Fails with INSTRUMENT_NOT_FOUND for "
        "an unknown instrument_id. Returns {resolution}.",
        {"instrument_id": {"type": "string", "description": "Core instrument id to read the resolution record for."}}, ["instrument_id"]),
    "order_draft": (
        t_order_draft,
        "Create an unsubmitted Order record in DRAFT status with "
        "a hash-chained receipt. Use to prepare and record an "
        "intended order for later review; there is no submission "
        "tool in this build at any tier, so a draft is never "
        "sent to a venue and no funds move. Mutating and "
        "persistent: stores the draft (ord-N) and appends a "
        "receipt; the returned order carries mandate_pre_eval "
        "NOT_EVALUATED_M0_DATA_ONLY — no mandate or funds check "
        "is performed. Use order_get to re-read a draft. Returns "
        "{order} including its receipt_ref.",
        {"instrument_id": {"type": "string", "description": "Core instrument id the draft order is for."},
         "side": {"type": "string", "description": "Order side as supplied by the caller, e.g. 'BUY' or 'SELL'; stored verbatim."},
         "type": {"type": "string", "description": "MARKET or LIMIT only; defaults to LIMIT. Any other type is refused."},
         "size": {"type": "string", "description": "Order size as a decimal string."},
         "limit_price": {"type": "string", "description": "Limit price as a decimal string for LIMIT orders; stored as null when omitted."}},
        ["instrument_id", "side", "size"]),
    "order_get": (
        t_order_get,
        "Fetch one stored Order record by order_id, including "
        "lifecycle status, fills, and fee-reconciliation fields. "
        "Use with an id returned by order_draft; there is no "
        "order-list tool, so unknown ids cannot be discovered "
        "from this server. Read-only. Orders in this build are "
        "unsubmitted DRAFT records only — no order is ever sent "
        "to a venue and no funds move. Fails with "
        "ORDER_NOT_FOUND for an unknown id. Returns {order}.",
        {"order_id": {"type": "string", "description": "Order id as returned by order_draft, e.g. 'ord-1'."}}, ["order_id"]),
    "venue_status": (
        t_venue_status,
        "Report adapter health and coverage for one venue: "
        "capability record, stored instrument count, current "
        "fee-schedule freshness, and receipt-chain validity. Use "
        "to check a venue before quoting or ingesting from it; "
        "use fee_schedule_get for the full schedule record and "
        "receipt_list for the ledger itself. Read-only. In this "
        "build every venue's capability is M0_DATA_ONLY — order "
        "and account tools are absent by design, no funds are "
        "held, and nothing is submitted anywhere. Returns the "
        "venue status object directly (venue, as_of, capability, "
        "instruments, fee_schedule_ref, fee_status, "
        "chain_valid).",
        {"venue": {"type": "string", "description": "Venue identifier to report on."},
         "as_of": {"type": "string", "description": "ISO 8601 evaluation time for the fee-freshness check; defaults to now."}},
        ["venue"]),
    "receipt_list": (
        t_receipt_list,
        "List the append-only, hash-chained receipt ledger that "
        "records every mutating operation in this server, and "
        "report whether the chain still verifies. Use to audit "
        "what changed and in what order; there is no "
        "per-receipt get tool — use limit to take the most "
        "recent entries. Read-only. Each receipt carries seq, "
        "ts, type, prev_hash, hash, and a detail object. "
        "Returns {receipts, count, chain_valid}, where count is "
        "always the full ledger length even when limit trims "
        "the returned list.",
        {"limit": {"type": "integer", "description": "Return only the most recent N receipts; omit to return the whole ledger."}}, []),
}

# Capability denylist, stated in code (spec 7/8): M0 is data
# only — no placement, no accounts, no withdrawals, no advice.
FORBIDDEN_TOOL_NAMES = {
    "order_place", "order_submit", "place_order", "submit_order",
    "trade_execute", "buy", "sell", "withdraw", "withdraw_funds",
    "transfer_funds", "account_get", "account_summary",
    "create_api_key", "margin_open", "leverage_set",
    "recommend", "signal_get", "probability_get",
}


def tool_list():
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": props,
                             "required": required}}
            for name, (_, description, props, required) in TOOLS.items()]


def handle(req: dict):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get(
                "protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-book",
                           "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        if name in FORBIDDEN_TOOL_NAMES or name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602,
                "message": f"unknown or line-forbidden tool {name}"}}
        state = load_state()
        receipts_before = len(state["receipts"])
        try:
            out = TOOLS[name][0](state, args)
            save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(out, indent=1)}]}}
        except ToolError as exc:
            if len(state["receipts"]) > receipts_before:
                save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(exc)})}],
                "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:  # never crash the transport
            response = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32602, "message": "MALFORMED_CONTAINER: argument \'request\'"}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

# Eclipse Book MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
