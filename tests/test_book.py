"""Eclipse Book v0.1 tests — canonical objects, criteria
pinning + CRITERIA_CHANGED (spec 5.4), fee truth + FEE_UNVERIFIED
(5.3), liquidity + probability law (5.5), resolution lifecycle
(5.4), UNMAPPED statuses (5.2), order-draft limits (5.6/7.2),
cross-adapter normalization parity, and chain integrity."""
import copy
import sys
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "eclipse-forecast-mcp"))
sys.path.insert(0, str(HERE.parent / "eclipse-strike-mcp"))

import book_engine as eng  # noqa: E402


def _load_adapter(name, dirname):
    import importlib.util
    path = HERE.parent / dirname / "server.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


srv = _load_adapter("server_book", "eclipse-book-mcp")

AS_OF = "2026-10-25T06:00:00Z"
CRITERIA_V1 = "Resolves Yes if the named source publishes X."
CRITERIA_V2 = "Resolves Yes if the named source publishes X, " \
              "using the revised methodology note."


def fresh_state():
    state = eng.empty_state()
    seed = {"config": {},
            "fee_schedules": [
                {"venue": "testvenue", "version": "v1",
                 "source": "fixture schedule",
                 "fetched_at": "2026-10-25T00:00:00Z",
                 "taker_fee_bps": "75", "maker_fee_bps": "0",
                 "settlement_fee_model": {"type": "none"},
                 "freshness_hours": 24,
                 "schedule_ref": "testvenue@v1"}]}
    return eng.ensure_seeded(state, seed)


def ingest_event(state, criteria=CRITERIA_V1, **over):
    spec = {"venue": "testvenue", "native_id": "mkt-1",
            "kind": "EVENT_CONTRACT", "title": "Will X happen?",
            "outcomes": ["Yes", "No"],
            "resolution_criteria": {"text": criteria,
                                    "source_ref": "test:1"},
            "resolution_source": "Named Source",
            "tick": "0.01", "min_size": "1", "currency": "USD",
            "money_class": "REAL", "native_status": "active",
            "status_mapped": "OPEN"}
    spec.update(over)
    return eng.ingest_instrument(state, spec)


def ingest_book(state, iid, best_ask_size="30000"):
    book = eng.build_book(
        iid, "testvenue", "CLOB",
        [{"price": "0.61", "size": "28000"},
         {"price": "0.60", "size": "41000"}],
        [{"price": "0.62", "size": best_ask_size},
         {"price": "0.63", "size": "45000"}],
        "2026-10-25T05:00:00Z", tick="0.01")
    book["outcome"] = "Yes"
    return eng.ingest_book(state, book)


class TestInstruments(unittest.TestCase):
    def test_criteria_pinned_verbatim(self):
        state = fresh_state()
        out = ingest_event(state)
        inst = out["instrument"]
        self.assertEqual(inst["resolution_criteria"], CRITERIA_V1)
        self.assertEqual(inst["criteria_versions"][0]["hash"],
                         eng.sha(CRITERIA_V1))
        self.assertIsNone(out["criteria_changed"])

    def test_event_contract_requires_criteria(self):
        state = fresh_state()
        with self.assertRaises(eng.ToolError) as ctx:
            ingest_event(state, criteria=None,
                         resolution_criteria=None)
        self.assertIn("RESOLUTION_CRITERIA_REQUIRED",
                      str(ctx.exception))

    def test_unmapped_status_preserved_never_coerced(self):
        state = fresh_state()
        out = eng.ingest_instrument(state, {
            "venue": "testvenue", "native_id": "sp-1", "kind": "SPOT",
            "title": "XYZ/USD", "native_status": "pending_review",
            "status_mapped": None})
        self.assertEqual(out["instrument"]["status"], "UNMAPPED")
        self.assertEqual(out["instrument"]["native_status"],
                         "pending_review")

    def test_probability_key_anywhere_is_forbidden(self):
        state = fresh_state()
        with self.assertRaises(eng.ToolError) as ctx:
            ingest_event(state, provenance={
                "feed": "x", "probability_estimate": "0.5"})
        self.assertIn("PROBABILITY_FIELD_FORBIDDEN", str(ctx.exception))


class TestCriteriaChanged(unittest.TestCase):
    def test_edit_flags_event_and_position_keeps_entry_criteria(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        pos = eng.position_open(state, {
            "instrument_id": iid, "size": "100",
            "entry_price": "0.62", "outcome": "Yes"})["position"]
        self.assertEqual(pos["criteria_as_of_entry"]["text"],
                         CRITERIA_V1)
        out = ingest_event(state, criteria=CRITERIA_V2)
        event = out["criteria_changed"]
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "CRITERIA_CHANGED")
        self.assertEqual(event["old_hash"], eng.sha(CRITERIA_V1))
        self.assertEqual(event["new_hash"], eng.sha(CRITERIA_V2))
        view = eng.position_view(state, state["positions"][
            pos["position_id"]])
        self.assertTrue(view["criteria_changed_since_entry"])
        self.assertEqual(view["criteria_as_of_entry"]["text"],
                         CRITERIA_V1)
        self.assertEqual(view["criteria_current"]["text"], CRITERIA_V2)
        types = [r["type"] for r in state["receipts"]]
        self.assertIn("criteria_changed", types)


class TestFeeTruth(unittest.TestCase):
    def test_all_in_math_from_dated_schedule(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        ingest_book(state, iid)
        q = eng.quote_get(state, iid, "100", outcome="Yes",
                          as_of=AS_OF)
        gross = Decimal("0.62") * 100
        fee = gross * Decimal("75") / 10000
        self.assertEqual(q["all_in_buy_cost"]["total"],
                         eng.ds(gross + fee))
        self.assertEqual(q["all_in_buy_cost"]["fee_amount"],
                         eng.ds(fee))
        self.assertEqual(q["fee_schedule_ref"], "testvenue@v1")
        self.assertEqual(q["fee_status"], "FRESH")
        self.assertEqual(q["max_payout_for_size"], "100")
        self.assertEqual(q["resolution_criteria"], CRITERIA_V1)

    def test_stale_schedule_degrades_to_fee_unverified(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        ingest_book(state, iid)
        q = eng.quote_get(state, iid, "100", outcome="Yes",
                          as_of="2026-11-20T00:00:00Z")
        self.assertEqual(q["fee_status"], "STALE")
        self.assertEqual(q["all_in_buy_cost"], "FEE_UNVERIFIED")
        self.assertEqual(q["all_in_sell_value"], "FEE_UNVERIFIED")
        # The price itself is still a price; only the all-in
        # claim degrades (5.3: a wrong number is worse than none).
        self.assertEqual(q["ask"], "0.62")

    def test_no_schedule_is_fee_unverified(self):
        state = fresh_state()
        out = eng.ingest_instrument(state, {
            "venue": "noschedulevenue", "native_id": "s-1",
            "kind": "SPOT", "title": "ABC/USD",
            "native_status": "online", "status_mapped": "OPEN"})
        iid = out["instrument"]["instrument_id"]
        book = eng.build_book(iid, "noschedulevenue", "CLOB",
                              [{"price": "10", "size": "5"}],
                              [{"price": "11", "size": "5"}],
                              "2026-10-25T05:00:00Z", tick="0.01")
        eng.ingest_book(state, book)
        q = eng.quote_get(state, iid, "1", as_of=AS_OF)
        self.assertEqual(q["fee_status"], "NO_SCHEDULE")
        self.assertEqual(q["all_in_buy_cost"], "FEE_UNVERIFIED")


class TestLiquidityLaw(unittest.TestCase):
    def test_thin_book_flagged(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        ingest_book(state, iid, best_ask_size="400")  # 400 x .50-ish
        book = eng.build_book(
            iid, "testvenue", "CLOB",
            [{"price": "0.48", "size": "350"}],
            [{"price": "0.50", "size": "400"}],
            "2026-10-25T05:00:00Z", tick="0.01")
        book["outcome"] = "Yes"
        eng.ingest_book(state, book)
        q = eng.quote_get(state, iid, "10", outcome="Yes", as_of=AS_OF)
        self.assertEqual(q["liquidity_flag"], "THIN")
        self.assertEqual(q["depth_summary"]["notional_at_best_ask"],
                         "200")

    def test_deep_book_flagged(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        ingest_book(state, iid)
        q = eng.quote_get(state, iid, "10", outcome="Yes", as_of=AS_OF)
        self.assertEqual(q["liquidity_flag"], "DEEP")

    def test_no_probability_fields_in_any_output(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        ingest_book(state, iid)
        pos = eng.position_open(state, {
            "instrument_id": iid, "size": "10",
            "entry_price": "0.62", "outcome": "Yes"})
        outputs = [eng.quote_get(state, iid, "10", outcome="Yes",
                                 as_of=AS_OF),
                   pos, eng.resolution_view(
                       state["instruments"][iid]),
                   eng.venue_status(state, "testvenue", as_of=AS_OF)]
        for out in outputs:
            self.assertEqual(eng.probability_scan(out), [])


class TestResolutionLifecycle(unittest.TestCase):
    def test_report_verify_only_against_named_source(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        out = eng.resolution_report(state, {
            "instrument_id": iid, "outcome": "Yes",
            "source": "venue wire", "evidence_ref": "ev-1"})
        self.assertEqual(out["resolution"]["state"], "REPORTED")
        with self.assertRaises(eng.ToolError) as ctx:
            eng.resolution_verify(state, {
                "instrument_id": iid,
                "verification_source": "Some Blog"})
        self.assertIn("RESOLUTION_SOURCE_MISMATCH", str(ctx.exception))
        out = eng.resolution_verify(state, {
            "instrument_id": iid,
            "verification_source": "Named Source",
            "criteria_match": True})
        self.assertEqual(out["resolution"]["state"], "VERIFIED")
        self.assertTrue(out["resolution"]["criteria_match"])

    def test_disputed_is_first_class_and_blocks_verify(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        out = eng.resolution_report(state, {
            "instrument_id": iid, "outcome": "Yes",
            "source": "Named Source", "evidence_ref": "ev-9",
            "disputed": True})
        self.assertEqual(out["resolution"]["state"], "DISPUTED")
        with self.assertRaises(eng.ToolError) as ctx:
            eng.resolution_verify(state, {
                "instrument_id": iid,
                "verification_source": "Named Source"})
        self.assertIn("RESOLUTION_DISPUTED", str(ctx.exception))
        out = eng.resolution_verify(state, {
            "instrument_id": iid,
            "verification_source": "Named Source",
            "dispute_cleared": True})
        self.assertEqual(out["resolution"]["state"], "VERIFIED")


class TestOrderDraft(unittest.TestCase):
    def test_draft_only_allowlist_types_no_submit_path(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        out = eng.order_draft(state, {
            "instrument_id": iid, "side": "BUY", "type": "LIMIT",
            "size": "10", "limit_price": "0.60"})
        self.assertEqual(out["order"]["status"], "DRAFT")
        self.assertEqual(out["order"]["mandate_pre_eval"],
                         "NOT_EVALUATED_M0_DATA_ONLY")
        with self.assertRaises(eng.ToolError) as ctx:
            eng.order_draft(state, {
                "instrument_id": iid, "side": "BUY", "type": "STOP",
                "size": "10"})
        self.assertIn("ORDER_TYPE_NOT_IN_V1_ALLOWLIST",
                      str(ctx.exception))
        for name in ("order_place", "order_submit", "withdraw",
                     "probability_get"):
            self.assertIn(name, srv.FORBIDDEN_TOOL_NAMES)
            self.assertNotIn(name, srv.TOOLS)


class TestChain(unittest.TestCase):
    def test_chain_valid_and_tamper_detected(self):
        state = fresh_state()
        iid = ingest_event(state)["instrument"]["instrument_id"]
        ingest_book(state, iid)
        self.assertTrue(eng.verify_receipt_chain(state["receipts"]))
        forged = copy.deepcopy(state["receipts"])
        forged[0]["detail"]["instrument_id"] = "B:other:fake"
        self.assertFalse(eng.verify_receipt_chain(forged))


class TestCrossAdapterParity(unittest.TestCase):
    """The same logical book expressed in Polymarket CLOB shape
    and in Coinbase level-2 shape must normalize to the same
    canonical Book + Quote math (modulo venue fields) — parity
    lives in the shared core builders (spec 5.2)."""

    def test_parity(self):
        forecast = _load_adapter("server_forecast",
                                 "eclipse-forecast-mcp")
        strike = _load_adapter("server_strike", "eclipse-strike-mcp")
        clob = {"bids": [{"price": "100.00", "size": "2.5"},
                         {"price": "99.50", "size": "4"}],
                "asks": [{"price": "100.50", "size": "3"},
                         {"price": "101.00", "size": "5"}],
                "timestamp": "2026-10-25T05:00:00Z",
                "tick_size": "0.01", "hash": "h-1"}
        cb = {"bids": [["100.00", "2.5", 2], ["99.50", "4", 1]],
              "asks": [["100.50", "3", 2], ["101.00", "5", 3]],
              "time": "2026-10-25T05:00:00Z", "sequence": "s-1"}
        b1 = forecast.parse_clob_book(clob, "B:x:m", "Yes")
        b2 = strike.parse_coinbase_book(cb, "A:y:m")
        for key in ("bids", "asks", "spread_bps", "depth_summary"):
            self.assertEqual(b1[key], b2[key], key)
        # Quote math parity under equal fee terms.
        state = fresh_state()
        for venue in ("polymarket_global", "coinbase"):
            eng.fee_schedule_register(state, {
                "venue": venue, "version": "par",
                "source": "parity fixture",
                "fetched_at": "2026-10-25T00:00:00Z",
                "taker_fee_bps": "50", "freshness_hours": 48})
        i1 = eng.ingest_instrument(state, {
            "venue": "polymarket_global", "native_id": "pm",
            "kind": "SPOT", "title": "PAR/USD",
            "native_status": "active", "status_mapped": "OPEN"})
        i2 = eng.ingest_instrument(state, {
            "venue": "coinbase", "native_id": "cb",
            "kind": "SPOT", "title": "PAR/USD",
            "native_status": "online", "status_mapped": "OPEN"})
        eng.ingest_book(state, b1 | {"instrument_id":
                                     i1["instrument"]["instrument_id"]})
        eng.ingest_book(state, b2 | {"instrument_id":
                                     i2["instrument"]["instrument_id"]})
        q1 = eng.quote_get(state, i1["instrument"]["instrument_id"],
                           "2", as_of=AS_OF)
        q2 = eng.quote_get(state, i2["instrument"]["instrument_id"],
                           "2", as_of=AS_OF)
        for key in ("bid", "ask", "mid", "spread_bps",
                    "liquidity_flag"):
            self.assertEqual(q1[key], q2[key], key)
        self.assertEqual(q1["all_in_buy_cost"]["total"],
                         q2["all_in_buy_cost"]["total"])


if __name__ == "__main__":
    unittest.main()
