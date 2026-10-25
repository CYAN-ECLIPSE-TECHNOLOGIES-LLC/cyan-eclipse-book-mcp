#!/usr/bin/env python3
"""End-to-end stdio smoke for Eclipse Book v0.1 (M0).

Temp state. Drives initialize -> instrument_ingest (event
contract, criteria pinned) -> book_ingest -> quote_get (all-in
fee truth) -> position_open -> resolution_report -> wrong-source
verify refused -> verify against the named source -> receipt_list.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def rpc(proc, rid, method, params=None):
    req = {"jsonrpc": "2.0", "id": rid, "method": method,
           "params": params or {}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def call(proc, rid, name, args):
    response = rpc(proc, rid, "tools/call",
                   {"name": name, "arguments": args})
    return json.loads(response["result"]["content"][0]["text"])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env["ECLIPSE_BOOK_STATE"] = str(Path(tmp) / "state.json")
        proc = subprocess.Popen(
            [sys.executable, str(HERE / "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            cwd=str(HERE), env=env)
        try:
            init = rpc(proc, 1, "initialize",
                       {"protocolVersion": "2025-03-26"})
            assert init["result"]["serverInfo"]["name"] == "eclipse-book"
            print("initialize OK")

            out = call(proc, 2, "instrument_ingest", {
                "venue": "polymarket_global",
                "native_id": "smoke-mkt", "kind": "EVENT_CONTRACT",
                "title": "Will the smoke test pass?",
                "outcomes": ["Yes", "No"],
                "resolution_criteria": {
                    "text": "Resolves Yes if the smoke completes.",
                    "source_ref": "smoke:1"},
                "resolution_source": "Smoke Oracle",
                "tick": "0.01", "min_size": "1",
                "native_status": "active", "status_mapped": "OPEN"})
            iid = out["instrument"]["instrument_id"]
            print("instrument_ingest OK;", iid)

            call(proc, 3, "book_ingest", {
                "instrument_id": iid, "venue": "polymarket_global",
                "outcome": "Yes", "as_of": "2026-10-25T05:00:00Z",
                "tick": "0.01",
                "bids": [{"price": "0.61", "size": "28000"}],
                "asks": [{"price": "0.62", "size": "30000"}]})
            print("book_ingest OK")

            q = call(proc, 4, "quote_get", {
                "instrument_id": iid, "size": "100", "outcome": "Yes",
                "as_of": "2026-10-25T06:00:00Z"})["quote"]
            assert q["all_in_buy_cost"]["total"] == "62.465", q
            assert q["liquidity_flag"] == "DEEP"
            print("quote_get OK; all-in 62.465, DEEP, criteria attached:",
                  bool(q["resolution_criteria"]))

            pos = call(proc, 5, "position_open", {
                "instrument_id": iid, "size": "100",
                "entry_price": "0.62", "outcome": "Yes"})["position"]
            assert pos["criteria_as_of_entry"]["text"].startswith(
                "Resolves Yes")
            print("position_open OK; criteria snapshotted at entry")

            call(proc, 6, "resolution_report", {
                "instrument_id": iid, "outcome": "Yes",
                "source": "venue wire", "evidence_ref": "smoke-ev"})
            bad = rpc(proc, 7, "tools/call", {
                "name": "resolution_verify",
                "arguments": {"instrument_id": iid,
                              "verification_source": "Some Blog"}})
            body = json.loads(bad["result"]["content"][0]["text"])
            assert "RESOLUTION_SOURCE_MISMATCH" in body["error"], body
            print("resolution_verify OK; wrong source refused by name")

            res = call(proc, 8, "resolution_verify", {
                "instrument_id": iid,
                "verification_source": "Smoke Oracle",
                "criteria_match": True})["resolution"]
            assert res["state"] == "VERIFIED"
            print("resolution_verify OK; VERIFIED against named source")

            receipts = call(proc, 9, "receipt_list", {})
            assert receipts["chain_valid"] is True
            print(f"receipts OK; {receipts['count']} entries, chain valid")
            print("SMOKE PASSED")
        finally:
            proc.stdin.close()
            proc.terminate()


if __name__ == "__main__":
    main()
