#!/usr/bin/env python3
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
        "T1 (core-local). Register or refresh a canonical "
        "Instrument from an adapter-normalized spec. Event "
        "contracts REQUIRE verbatim resolution criteria + a "
        "named resolution source; criteria are hash-pinned and a "
        "later change is a CRITERIA_CHANGED event (spec 5.4). "
        "Unmapped venue statuses surface as UNMAPPED, never "
        "coerced (5.2).",
        {"venue": {"type": "string"}, "native_id": {"type": "string"},
         "native_symbol": {"type": "string"},
         "kind": {"type": "string"}, "title": {"type": "string"},
         "underlying": {"type": "string"},
         "outcomes": {"type": "array", "items": {"type": "string"}},
         "resolution_criteria": {"type": "object"},
         "resolution_source": {"type": "string"},
         "trading_window": {"type": "object"},
         "tick": {"type": "string"}, "min_size": {"type": "string"},
         "currency": {"type": "string"},
         "money_class": {"type": "string"},
         "native_status": {"type": "string"},
         "status_mapped": {"type": "string"},
         "provenance": {"type": "object"}},
        ["venue", "native_id", "kind", "title"]),
    "instrument_get": (
        t_instrument_get,
        "T0. One canonical Instrument by core id, criteria "
        "versions and resolution state included.",
        {"instrument_id": {"type": "string"}}, ["instrument_id"]),
    "instrument_search": (
        t_instrument_search,
        "T0. Search instruments by title/id substring, optional "
        "venue filter.",
        {"query": {"type": "string"}, "venue": {"type": "string"}}, []),
    "book_ingest": (
        t_book_ingest,
        "T1 (core-local). Store a canonical Book snapshot built "
        "from normalized levels for an ingested instrument "
        "(per outcome for event contracts).",
        {"instrument_id": {"type": "string"},
         "venue": {"type": "string"}, "book_type": {"type": "string"},
         "bids": {"type": "array", "items": {"type": "object"}},
         "asks": {"type": "array", "items": {"type": "object"}},
         "as_of": {"type": "string"}, "tick": {"type": "string"},
         "outcome": {"type": "string"},
         "native_ref": {"type": "string"}},
        ["instrument_id", "venue", "bids", "asks", "as_of"]),
    "quote_get": (
        t_quote_get,
        "T0. The only price-shaped object (spec 5.1): bid/ask/"
        "computed mid, ALL-IN buy/sell cost for the stated size "
        "from the venue's dated fee schedule, liquidity flag + "
        "depth, and — for event contracts — the verbatim "
        "resolution criteria. A stale or missing fee schedule "
        "degrades all-in fields to FEE_UNVERIFIED (5.3). Never "
        "a probability field (5.5).",
        {"instrument_id": {"type": "string"},
         "size": {"type": "string"}, "outcome": {"type": "string"},
         "as_of": {"type": "string"}},
        ["instrument_id", "size"]),
    "fee_schedule_register": (
        t_fee_schedule_register,
        "T1 (core-local). Register a versioned fee schedule. "
        "Provenance (source + fetched_at) is REQUIRED — a "
        "schedule without it is not a schedule (5.3).",
        {"venue": {"type": "string"}, "version": {"type": "string"},
         "source": {"type": "string"},
         "fetched_at": {"type": "string"},
         "taker_fee_bps": {"type": "string"},
         "maker_fee_bps": {"type": "string"},
         "settlement_fee_model": {"type": "object"},
         "freshness_hours": {"type": "integer"}},
        ["venue", "version", "source", "fetched_at", "taker_fee_bps"]),
    "fee_schedule_get": (
        t_fee_schedule_get,
        "T0. The venue's current fee schedule + its freshness "
        "state (FRESH | STALE | NO_SCHEDULE).",
        {"venue": {"type": "string"}, "as_of": {"type": "string"}},
        ["venue"]),
    "position_open": (
        t_position_open,
        "T1 (core-local record). Record a position with the "
        "resolution criteria snapshotted AS OF ENTRY (5.4). A "
        "record, not an execution: M0 places nothing.",
        {"instrument_id": {"type": "string"},
         "size": {"type": "string"},
         "entry_price": {"type": "string"},
         "outcome": {"type": "string"},
         "account_ref": {"type": "string"}},
        ["instrument_id", "size", "entry_price"]),
    "position_list": (
        t_position_list,
        "T0/T1. All recorded positions, each carrying its "
        "criteria-as-of-entry beside the current criteria and a "
        "criteria_changed_since_entry flag.",
        {}, []),
    "position_get": (
        t_position_get,
        "T0/T1. One recorded position by id.",
        {"position_id": {"type": "string"}}, ["position_id"]),
    "resolution_report": (
        t_resolution_report,
        "T1 (core-local). Record a venue-reported resolution "
        "(REPORTED) or mark a dispute (DISPUTED, first-class, "
        "spec 5.4). A report is a claim, not a fact.",
        {"instrument_id": {"type": "string"},
         "outcome": {"type": "string"}, "source": {"type": "string"},
         "evidence_ref": {"type": "string"},
         "disputed": {"type": "boolean"}},
        ["instrument_id", "outcome"]),
    "resolution_verify": (
        t_resolution_verify,
        "T1 (core-local). Promote REPORTED -> VERIFIED, only "
        "against the criteria's OWN named source of truth; any "
        "other source is refused by name, and an open dispute "
        "blocks verification until cleared (5.4).",
        {"instrument_id": {"type": "string"},
         "verification_source": {"type": "string"},
         "criteria_match": {"type": "boolean"},
         "dispute_cleared": {"type": "boolean"}},
        ["instrument_id", "verification_source"]),
    "resolution_get": (
        t_resolution_get,
        "T0. The Resolution record for an instrument: state "
        "(NONE|REPORTED|VERIFIED|DISPUTED), outcome, sources, "
        "history. Unverified is data, not fact (5.4).",
        {"instrument_id": {"type": "string"}}, ["instrument_id"]),
    "order_draft": (
        t_order_draft,
        "T1. Build an UNSUBMITTED Order in DRAFT (MARKET|LIMIT "
        "only) with its receipt. M0 has no submission path at "
        "any tier; mandate pre-evaluation reads "
        "NOT_EVALUATED_M0_DATA_ONLY (spec 5.6, 7.2).",
        {"instrument_id": {"type": "string"},
         "side": {"type": "string"}, "type": {"type": "string"},
         "size": {"type": "string"},
         "limit_price": {"type": "string"}},
        ["instrument_id", "side", "size"]),
    "order_get": (
        t_order_get,
        "T0/T1. One Order record with lifecycle + fills + fee "
        "reconciliation fields.",
        {"order_id": {"type": "string"}}, ["order_id"]),
    "venue_status": (
        t_venue_status,
        "T0. Adapter health for a venue: capability record "
        "(M0 = DATA ONLY), instrument count, fee-schedule "
        "freshness, ledger chain state.",
        {"venue": {"type": "string"}, "as_of": {"type": "string"}},
        ["venue"]),
    "receipt_list": (
        t_receipt_list,
        "T0. The suite ledger: append-only, hash-chained "
        "receipts; verifies the chain.",
        {"limit": {"type": "integer"}}, []),
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
                "code": -32603, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
