"""Eclipse Book — shared Market Core engine (spec
eclipse-markets-suite-spec-20261025 sections 5-7).

This module is the suite law in code: canonical Instrument /
Book / Quote / Order / Position / Resolution objects, fee truth
(section 5.3), the resolution-verification discipline (5.4),
liquidity + probability honesty (5.5), and the append-only
hash-chained receipt ledger.

Adapters (Forecast, Strike first) import this module from the
sibling core directory and translate venue-native payloads into
engine calls against the SHARED suite state, loaded fresh at
every call. An adapter may never emit a core object it had to
guess at: missing native fields surface as explicit gaps, and a
venue status that does not map into the core vocabulary surfaces
as UNMAPPED with the native string preserved, never coerced
(section 5.2).

M0 SCOPE: data only. This engine contains no order-submission,
account, withdrawal, or transfer capability at any tier — the
Order object exists as a DRAFT record (section 5.6) whose mandate
pre-evaluation is honestly NOT_EVALUATED in M0. Placement is M2,
owner-gated (spec section 18, decision D3).

Pure functions over a state dict: load/save are the caller's
job. Stdlib only. Money math is Decimal end-to-end; prices are
decimal strings on every surface (section 5.2).
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal


class ToolError(Exception):
    pass


KINDS = {"SPOT", "EVENT_CONTRACT", "EQUITY", "PLAY_EVENT_CONTRACT"}
STATUSES = {"OPEN", "CLOSED", "RESOLVED", "VOIDED"}
MONEY_CLASSES = {"REAL", "PLAY"}
BOOK_TYPES = {"CLOB", "AMM", "INDICATIVE"}
RESOLUTION_STATES = {"NONE", "REPORTED", "VERIFIED", "DISPUTED"}
ORDER_TYPES = {"MARKET", "LIMIT"}
ORDER_STATUSES = {"DRAFT", "SUBMITTED", "OPEN", "PARTIAL", "FILLED",
                  "CANCELLED", "REJECTED", "EXPIRED"}

# Liquidity law (spec 5.5): core-owned thresholds, notional in the
# instrument's currency at the best ask. Adapters may tighten,
# never loosen. DEEP >= 10000, THIN < 1000, else FRAGILE.
LIQUIDITY_DEEP_MIN = Decimal("10000")
LIQUIDITY_THIN_MAX = Decimal("1000")

DEFAULT_FEE_FRESHNESS_HOURS = 24
DEFAULT_BOOK_STALE_SECONDS = 86400


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value):
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def D(value) -> Decimal:
    return Decimal(str(value))


def ds(value) -> str:
    """Decimal -> canonical decimal string (no exponent, no
    trailing-zero noise)."""
    d = D(value)
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


# ---------------------------------------------------------------- receipts
def emit_receipt(state: dict, rtype: str, detail: dict) -> dict:
    prev = state["receipts"][-1]["hash"] if state["receipts"] else "GENESIS"
    entry = {"seq": len(state["receipts"]) + 1, "ts": now_iso(),
             "type": rtype, "prev_hash": prev, "detail": detail}
    entry["hash"] = sha(prev + canon(
        {k: v for k, v in entry.items() if k != "hash"}))
    state["receipts"].append(entry)
    return entry


def verify_receipt_chain(receipts) -> bool:
    prev = "GENESIS"
    for entry in receipts:
        expect = sha(prev + canon(
            {k: v for k, v in entry.items() if k != "hash"}))
        if entry.get("hash") != expect or entry.get("prev_hash") != prev:
            return False
        prev = entry["hash"]
    return True


# ------------------------------------------------------- probability law
def probability_scan(obj, path="$"):
    """Spec 5.5: the core never emits a probability field.
    Returns the list of offending key paths (keys only — a price
    is a price, and no output key may name it anything else)."""
    hits = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if "probab" in str(key).lower():
                hits.append(f"{path}.{key}")
            hits.extend(probability_scan(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            hits.extend(probability_scan(value, f"{path}[{i}]"))
    return hits


def guard_no_probability(obj):
    hits = probability_scan(obj)
    if hits:
        raise ToolError(
            "PROBABILITY_FIELD_FORBIDDEN: core outputs carry price + "
            f"liquidity + criteria, never a probability field ({hits})")
    return obj


# ------------------------------------------------------------------- state
def empty_state() -> dict:
    return {"config": {"fee_freshness_hours": DEFAULT_FEE_FRESHNESS_HOURS,
                       "book_stale_seconds": DEFAULT_BOOK_STALE_SECONDS},
            "instruments": {}, "books": {}, "fee_schedules": {},
            "positions": {}, "orders": {}, "receipts": []}


def ensure_seeded(state: dict, seed: dict) -> dict:
    state["config"].update(seed.get("config", {}))
    for sched in seed.get("fee_schedules", []):
        if sched["schedule_ref"] not in state["fee_schedules"]:
            state["fee_schedules"][sched["schedule_ref"]] = sched
    return state


# ------------------------------------------------------------ fee schedules
def fee_schedule_register(state: dict, args: dict) -> dict:
    """Fee schedules are versioned data with provenance (5.3):
    source + fetched_at are required; a schedule without them is
    not a schedule."""
    for field in ("venue", "version", "source", "fetched_at",
                  "taker_fee_bps"):
        if args.get(field) in (None, ""):
            raise ToolError(f"FEE_SCHEDULE_PROVENANCE_REQUIRED: {field}")
    ref = f"{args['venue']}@{args['version']}"
    sched = {"schedule_ref": ref, "venue": args["venue"],
             "version": args["version"], "source": args["source"],
             "fetched_at": args["fetched_at"],
             "taker_fee_bps": ds(args["taker_fee_bps"]),
             "maker_fee_bps": ds(args.get("maker_fee_bps", "0")),
             "settlement_fee_model": args.get(
                 "settlement_fee_model", {"type": "none"}),
             "freshness_hours": int(args.get(
                 "freshness_hours",
                 state["config"]["fee_freshness_hours"]))}
    state["fee_schedules"][ref] = sched
    emit_receipt(state, "fee_schedule_registered",
                 {"schedule_ref": ref, "venue": sched["venue"],
                  "fetched_at": sched["fetched_at"]})
    return {"fee_schedule": sched}


def fee_schedule_for(state: dict, venue: str):
    """Latest registered schedule for a venue, or None."""
    cands = [s for s in state["fee_schedules"].values()
             if s["venue"] == venue]
    if not cands:
        return None
    return sorted(cands, key=lambda s: s["fetched_at"])[-1]


def fee_freshness(state: dict, venue: str, as_of: str):
    """-> (schedule, status): FRESH | STALE | NO_SCHEDULE."""
    sched = fee_schedule_for(state, venue)
    if sched is None:
        return None, "NO_SCHEDULE"
    age_h = (parse_time(as_of) - parse_time(
        sched["fetched_at"])).total_seconds() / 3600.0
    if age_h > sched["freshness_hours"]:
        return sched, "STALE"
    return sched, "FRESH"


# --------------------------------------------------------------- instruments
def instrument_id_for(venue: str, kind: str, native_id: str) -> str:
    wing = "B" if kind in ("EVENT_CONTRACT", "PLAY_EVENT_CONTRACT") else "A"
    return f"{wing}:{venue}:{native_id}"


def ingest_instrument(state: dict, spec_in: dict) -> dict:
    """Register or refresh a canonical Instrument. Resolution
    criteria are verbatim + hash-pinned at first read (5.4): a
    later ingest carrying different criteria records a
    CRITERIA_CHANGED event; the instrument keeps every version,
    and positions keep the criteria as of their entry."""
    for field in ("venue", "native_id", "kind", "title"):
        if not spec_in.get(field):
            raise ToolError(f"INSTRUMENT_FIELD_REQUIRED: {field}")
    kind = spec_in["kind"]
    if kind not in KINDS:
        raise ToolError(f"INSTRUMENT_KIND_UNKNOWN: {kind}")
    money_class = spec_in.get("money_class", "REAL")
    if money_class not in MONEY_CLASSES:
        raise ToolError(f"MONEY_CLASS_UNKNOWN: {money_class}")
    if kind == "PLAY_EVENT_CONTRACT" and money_class != "PLAY":
        raise ToolError("PLAY_INSTRUMENT_REQUIRES_PLAY_MONEY_CLASS")
    criteria = spec_in.get("resolution_criteria")
    if kind in ("EVENT_CONTRACT", "PLAY_EVENT_CONTRACT"):
        if not criteria or not criteria.get("text"):
            raise ToolError(
                "RESOLUTION_CRITERIA_REQUIRED: an event contract "
                "without verbatim criteria is not an instrument")
        if not spec_in.get("resolution_source"):
            raise ToolError(
                "RESOLUTION_SOURCE_REQUIRED: the named resolver is "
                "part of the instrument (spec 5.4)")
    native_status = spec_in.get("native_status")
    mapped = spec_in.get("status_mapped")
    status = mapped if mapped in STATUSES else "UNMAPPED"
    iid = instrument_id_for(spec_in["venue"], kind, spec_in["native_id"])
    existing = state["instruments"].get(iid)
    event = None
    if existing is None:
        inst = {"instrument_id": iid, "venue": spec_in["venue"],
                "native_id": spec_in["native_id"],
                "native_symbol": spec_in.get("native_symbol"),
                "kind": kind, "title": spec_in["title"],
                "underlying": spec_in.get("underlying"),
                "outcomes": spec_in.get("outcomes", []),
                "resolution_source": spec_in.get("resolution_source"),
                "trading_window": spec_in.get("trading_window", {}),
                "tick": spec_in.get("tick"),
                "min_size": spec_in.get("min_size"),
                "currency": spec_in.get("currency", "USD"),
                "money_class": money_class, "status": status,
                "native_status": native_status,
                "provenance": spec_in.get("provenance", {}),
                "resolution": {"state": "NONE", "outcome": None,
                               "source": None, "evidence_ref": None,
                               "criteria_match": None, "history": []}}
        if criteria:
            inst["resolution_criteria"] = criteria["text"]
            inst["resolution_criteria_source_ref"] = criteria.get(
                "source_ref")
            inst["criteria_versions"] = [{
                "hash": sha(criteria["text"]), "text": criteria["text"],
                "source_ref": criteria.get("source_ref"),
                "first_seen": now_iso()}]
        state["instruments"][iid] = inst
        emit_receipt(state, "instrument_ingested",
                     {"instrument_id": iid, "venue": inst["venue"],
                      "kind": kind})
        return {"instrument": guard_no_probability(inst),
                "criteria_changed": None}
    # Refresh: status/native fields update; criteria are pinned.
    existing["status"] = status
    existing["native_status"] = native_status
    if spec_in.get("trading_window"):
        existing["trading_window"] = spec_in["trading_window"]
    if criteria:
        new_hash = sha(criteria["text"])
        cur_hash = existing["criteria_versions"][-1]["hash"]
        if new_hash != cur_hash:
            existing["criteria_versions"].append({
                "hash": new_hash, "text": criteria["text"],
                "source_ref": criteria.get("source_ref"),
                "first_seen": now_iso()})
            existing["resolution_criteria"] = criteria["text"]
            existing["resolution_criteria_source_ref"] = criteria.get(
                "source_ref")
            event = {"type": "CRITERIA_CHANGED", "instrument_id": iid,
                     "old_hash": cur_hash, "new_hash": new_hash}
            emit_receipt(state, "criteria_changed", dict(event))
    return {"instrument": guard_no_probability(existing),
            "criteria_changed": event}


def criteria_snapshot(inst: dict):
    if "criteria_versions" not in inst:
        return None
    cur = inst["criteria_versions"][-1]
    return {"text": cur["text"], "hash": cur["hash"],
            "source_ref": cur.get("source_ref")}


# --------------------------------------------------------------------- books
def build_book(instrument_id: str, venue: str, book_type: str,
               bids, asks, as_of: str, tick=None, native_ref=None):
    """Canonical Book from normalized levels. bids/asks: lists of
    {price, size} with decimal-string values, any order — the
    builder sorts (bids desc, asks asc) and preserves venue-native
    precision by keeping the strings it was given."""
    if book_type not in BOOK_TYPES:
        raise ToolError(f"BOOK_TYPE_UNKNOWN: {book_type}")
    bids_s = sorted(bids, key=lambda lv: D(lv["price"]), reverse=True)
    asks_s = sorted(asks, key=lambda lv: D(lv["price"]))
    book = {"instrument_id": instrument_id, "venue": venue,
            "as_of": as_of, "book_type": book_type,
            "bids": [{"price": ds(lv["price"]), "size": ds(lv["size"])}
                     for lv in bids_s],
            "asks": [{"price": ds(lv["price"]), "size": ds(lv["size"])}
                     for lv in asks_s],
            "native_ref": native_ref}
    book["depth_summary"] = depth_summary(book, tick)
    if bids_s and asks_s:
        bid, ask = D(bids_s[0]["price"]), D(asks_s[0]["price"])
        mid = (bid + ask) / 2
        book["spread_bps"] = ds((ask - bid) / mid * 10000) if mid else None
    else:
        book["spread_bps"] = None
    return book


def depth_summary(book: dict, tick=None) -> dict:
    bids, asks = book["bids"], book["asks"]
    out = {"size_at_best_bid": bids[0]["size"] if bids else "0",
           "size_at_best_ask": asks[0]["size"] if asks else "0",
           "notional_at_best_ask": "0", "size_within_5_ticks_bid": "0",
           "size_within_5_ticks_ask": "0"}
    if asks:
        out["notional_at_best_ask"] = ds(
            D(asks[0]["size"]) * D(asks[0]["price"]))
    if tick:
        t = D(tick)
        if bids:
            floor = D(bids[0]["price"]) - 5 * t
            out["size_within_5_ticks_bid"] = ds(sum(
                D(lv["size"]) for lv in bids if D(lv["price"]) >= floor))
        if asks:
            cap = D(asks[0]["price"]) + 5 * t
            out["size_within_5_ticks_ask"] = ds(sum(
                D(lv["size"]) for lv in asks if D(lv["price"]) <= cap))
    return out


def liquidity_flag(book: dict) -> str:
    notional = D(book["depth_summary"]["notional_at_best_ask"])
    if notional >= LIQUIDITY_DEEP_MIN:
        return "DEEP"
    if notional < LIQUIDITY_THIN_MAX:
        return "THIN"
    return "FRAGILE"


def ingest_book(state: dict, book: dict) -> dict:
    iid = book["instrument_id"]
    if iid not in state["instruments"]:
        raise ToolError(f"BOOK_FOR_UNKNOWN_INSTRUMENT: {iid}")
    outcome = book.get("outcome")
    key = f"{iid}|{outcome}" if outcome else iid
    book = dict(book)
    book["outcome"] = outcome
    state["books"][key] = book
    return {"book": book}


def get_book(state: dict, instrument_id: str, outcome=None):
    key = f"{instrument_id}|{outcome}" if outcome else instrument_id
    book = state["books"].get(key)
    if book is None and outcome is None:
        cands = [b for k, b in state["books"].items()
                 if k.startswith(instrument_id + "|")]
        if len(cands) == 1:
            book = cands[0]
    if book is None:
        raise ToolError(f"BOOK_NOT_FOUND: {key}")
    return book


# -------------------------------------------------------------------- quotes
def quote_get(state: dict, instrument_id: str, size,
              outcome=None, as_of=None) -> dict:
    """The ONLY price-shaped object consumers may receive (5.1):
    price + all-in cost for a stated size + fee-truth state +
    liquidity + (for event contracts) the criteria attached.
    Never a probability field (5.5)."""
    inst = state["instruments"].get(instrument_id)
    if inst is None:
        raise ToolError(f"INSTRUMENT_NOT_FOUND: {instrument_id}")
    book = get_book(state, instrument_id, outcome)
    if not book["bids"] or not book["asks"]:
        raise ToolError("BOOK_ONE_SIDED: no two-sided book, no quote")
    as_of = as_of or now_iso()
    bid = D(book["bids"][0]["price"])
    ask = D(book["asks"][0]["price"])
    mid = (bid + ask) / 2
    n = D(size)
    sched, fee_status = fee_freshness(state, inst["venue"], as_of)
    quote = {"instrument_id": instrument_id, "venue": inst["venue"],
             "outcome": outcome, "as_of": as_of,
             "book_as_of": book["as_of"], "bid": ds(bid), "ask": ds(ask),
             "mid": ds(mid), "mid_basis": "computed",
             "spread_bps": book["spread_bps"],
             "size": ds(n), "currency": inst["currency"],
             "money_class": inst["money_class"],
             "liquidity_flag": liquidity_flag(book),
             "depth_summary": book["depth_summary"],
             "fee_status": fee_status,
             "fee_schedule_ref": sched["schedule_ref"] if sched else None}
    age = (parse_time(as_of) - parse_time(
        book["as_of"])).total_seconds()
    quote["book_stale"] = age > state["config"]["book_stale_seconds"]
    if fee_status == "FRESH":
        bps = D(sched["taker_fee_bps"])
        buy_gross = ask * n
        buy_fee = buy_gross * bps / 10000
        sell_gross = bid * n
        sell_fee = sell_gross * bps / 10000
        quote["all_in_buy_cost"] = {
            "total": ds(buy_gross + buy_fee),
            "per_unit": ds((buy_gross + buy_fee) / n),
            "fee_amount": ds(buy_fee),
            "fee_schedule_ref": sched["schedule_ref"]}
        quote["all_in_sell_value"] = {
            "total": ds(sell_gross - sell_fee),
            "per_unit": ds((sell_gross - sell_fee) / n),
            "fee_amount": ds(sell_fee),
            "fee_schedule_ref": sched["schedule_ref"]}
        quote["settlement_fee_model"] = sched["settlement_fee_model"]
        if inst["kind"] in ("EVENT_CONTRACT", "PLAY_EVENT_CONTRACT"):
            quote["max_payout_for_size"] = ds(n * D(1))
    else:
        # A wrong all-in number is worse than no number (5.3).
        quote["all_in_buy_cost"] = "FEE_UNVERIFIED"
        quote["all_in_sell_value"] = "FEE_UNVERIFIED"
    if inst["kind"] in ("EVENT_CONTRACT", "PLAY_EVENT_CONTRACT"):
        snap = criteria_snapshot(inst)
        quote["resolution_criteria"] = snap["text"]
        quote["resolution_criteria_hash"] = snap["hash"]
        quote["resolution_source"] = inst["resolution_source"]
    return guard_no_probability(quote)


# ----------------------------------------------------------------- positions
def position_open(state: dict, args: dict) -> dict:
    inst = state["instruments"].get(args["instrument_id"])
    if inst is None:
        raise ToolError(f"INSTRUMENT_NOT_FOUND: {args['instrument_id']}")
    pid = f"pos-{len(state['positions']) + 1}"
    snap = criteria_snapshot(inst)
    pos = {"position_id": pid, "instrument_id": inst["instrument_id"],
           "venue": inst["venue"],
           "account_ref": args.get("account_ref", "owner"),
           "outcome": args.get("outcome"),
           "size": ds(args["size"]),
           "avg_cost": ds(args["entry_price"]),
           "avg_cost_basis": "all-in per unit, as supplied at entry",
           "settlement_state": "OPEN",
           "criteria_as_of_entry": snap,
           "opened_at": now_iso()}
    state["positions"][pid] = pos
    emit_receipt(state, "position_opened",
                 {"position_id": pid, "instrument_id": inst["instrument_id"],
                  "criteria_hash": snap["hash"] if snap else None})
    return {"position": position_view(state, pos)}


def position_view(state: dict, pos: dict) -> dict:
    inst = state["instruments"][pos["instrument_id"]]
    view = dict(pos)
    cur = criteria_snapshot(inst)
    view["criteria_current"] = cur
    entry = pos.get("criteria_as_of_entry")
    view["criteria_changed_since_entry"] = bool(
        entry and cur and entry["hash"] != cur["hash"])
    view["resolution_state"] = inst["resolution"]["state"]
    view["money_class"] = inst["money_class"]
    return guard_no_probability(view)


# --------------------------------------------------------------- resolutions
def resolution_report(state: dict, args: dict) -> dict:
    """A resolution is a claim until verified (5.4): REPORTED."""
    inst = state["instruments"].get(args["instrument_id"])
    if inst is None:
        raise ToolError(f"INSTRUMENT_NOT_FOUND: {args['instrument_id']}")
    res = inst["resolution"]
    if args.get("disputed"):
        res["state"] = "DISPUTED"
    elif res["state"] in ("NONE", "DISPUTED"):
        res["state"] = "REPORTED"
    res["outcome"] = args["outcome"]
    res["source"] = args.get("source")
    res["evidence_ref"] = args.get("evidence_ref")
    res["history"].append({"state": res["state"], "ts": now_iso(),
                           "outcome": args["outcome"],
                           "evidence_ref": args.get("evidence_ref")})
    emit_receipt(state, "resolution_reported",
                 {"instrument_id": inst["instrument_id"],
                  "state": res["state"], "outcome": args["outcome"]})
    return {"resolution": resolution_view(inst)}


def resolution_verify(state: dict, args: dict) -> dict:
    """VERIFIED only against the criteria's OWN named source
    (5.4). A verification attempt naming any other source is
    refused by name; a live dispute keeps the state DISPUTED."""
    inst = state["instruments"].get(args["instrument_id"])
    if inst is None:
        raise ToolError(f"INSTRUMENT_NOT_FOUND: {args['instrument_id']}")
    res = inst["resolution"]
    if res["state"] == "NONE":
        raise ToolError("RESOLUTION_NOT_REPORTED: nothing to verify")
    named = inst.get("resolution_source")
    if args.get("verification_source") != named:
        raise ToolError(
            f"RESOLUTION_SOURCE_MISMATCH: criteria name '{named}' as "
            f"the source of truth; '{args.get('verification_source')}' "
            "cannot verify this resolution")
    if res["state"] == "DISPUTED" and not args.get("dispute_cleared"):
        raise ToolError(
            "RESOLUTION_DISPUTED: dispute is open; verification waits "
            "for finality (spec 5.4)")
    res["state"] = "VERIFIED"
    res["criteria_match"] = bool(args.get("criteria_match", True))
    res["history"].append({"state": "VERIFIED", "ts": now_iso(),
                           "verification_source": named,
                           "criteria_match": res["criteria_match"]})
    emit_receipt(state, "resolution_verified",
                 {"instrument_id": inst["instrument_id"],
                  "outcome": res["outcome"],
                  "criteria_match": res["criteria_match"]})
    return {"resolution": resolution_view(inst)}


def resolution_view(inst: dict) -> dict:
    res = inst["resolution"]
    return guard_no_probability({
        "instrument_id": inst["instrument_id"],
        "state": res["state"], "verification": res["state"],
        "outcome": res["outcome"], "source": res["source"],
        "named_resolution_source": inst.get("resolution_source"),
        "evidence_ref": res["evidence_ref"],
        "criteria_match": res["criteria_match"],
        "history": res["history"]})


# -------------------------------------------------------------------- orders
def order_draft(state: dict, args: dict) -> dict:
    """M0: a DRAFT record only. No submission path exists in
    this build at any tier; the mandate pre-evaluation is
    honestly NOT_EVALUATED until M2 wires the Wallet gate
    (spec 5.6 / 7.2)."""
    inst = state["instruments"].get(args["instrument_id"])
    if inst is None:
        raise ToolError(f"INSTRUMENT_NOT_FOUND: {args['instrument_id']}")
    otype = args.get("type", "LIMIT")
    if otype not in ORDER_TYPES:
        raise ToolError(
            f"ORDER_TYPE_NOT_IN_V1_ALLOWLIST: {otype} (MARKET|LIMIT only)")
    oid = f"ord-{len(state['orders']) + 1}"
    order = {"order_id": oid, "venue_order_id": None,
             "instrument_id": inst["instrument_id"],
             "venue": inst["venue"], "side": args["side"],
             "type": otype, "size": ds(args["size"]),
             "limit_price": ds(args["limit_price"])
             if args.get("limit_price") is not None else None,
             "status": "DRAFT", "fills": [],
             "mandate_ref": None,
             "mandate_pre_eval": "NOT_EVALUATED_M0_DATA_ONLY",
             "created_at": now_iso()}
    state["orders"][oid] = order
    receipt = emit_receipt(state, "order_drafted",
                           {"order_id": oid,
                            "instrument_id": inst["instrument_id"]})
    order["receipt_ref"] = receipt["hash"]
    return {"order": order}


# ---------------------------------------------------------------- venue status
def venue_status(state: dict, venue: str, as_of=None) -> dict:
    as_of = as_of or now_iso()
    sched, fee_status = fee_freshness(state, venue, as_of)
    insts = [i for i in state["instruments"].values()
             if i["venue"] == venue]
    return {"venue": venue, "as_of": as_of,
            "capability": "M0_DATA_ONLY",
            "order_tools": "ABSENT",
            "account_tools": "ABSENT",
            "instruments": len(insts),
            "fee_schedule_ref": sched["schedule_ref"] if sched else None,
            "fee_status": fee_status,
            "chain_valid": verify_receipt_chain(state["receipts"])}
