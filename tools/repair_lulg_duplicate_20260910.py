"""Retire the verified duplicate LULG bookkeeping row; never sends broker orders.

Default is read-only. --apply saves original rows, then conditionally retires
only the duplicate. Realized P/L stays NULL: a transfer of management is not
a filled trade. The Wheel's original row remains open.
"""
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
import sys, json, urllib.request, urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))
import relay

UID = "6ce61054-7ffd-41b5-80c3-1cd0220c79eb"
DUP = "072aeb66-ac96-4141-b668-c18b5b3deea3"
OWNER = "5308eb58-887f-4dac-aaee-afc2ed70c303"
ORDER = "c7a69c64-6900-4788-9d11-5e5b0fd5f03d"
OCC = "LULG260918P00004000"

def main():
    relay._URL, relay._KEY = relay._load_env()
    env = {}
    for ln in Path(relay._find_env()).read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, _, v = ln.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    assert env["TREZO_ACCOUNT_USER_ID_2"] == UID
    base = env.get("ALPACA_BASE_URL_2", "https://paper-api.alpaca.markets").rstrip("/")
    if base.endswith("/v2"): base = base[:-3]
    assert base == "https://paper-api.alpaca.markets"
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY_2"],
               "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY_2"]}
    def broker(path):
        with urllib.request.urlopen(urllib.request.Request(base+path, headers=headers), timeout=15) as r:
            return json.load(r)
    def row(table, ident):
        result = relay.get(f"/rest/v1/{table}?select=*&id=eq.{ident}&user_id=eq.{UID}")
        assert len(result) == 1
        return result[0]
    original = row("paper_positions", DUP)
    owner = row("options_positions", OWNER)
    if original["status"] == "closed_adopted" and original["source_payload"].get("superseded_by") == OWNER:
        print("Already repaired; no writes.")
        return
    assert original["status"] == owner["status"] == "open"
    assert original["source_payload"].get("adopted") is True
    assert original["broker_order_id"] is None
    assert original["ticker"] == OCC and original["side"] == "short"
    assert ORDER in owner["notes"] and OCC in owner["notes"]
    position = broker("/v2/positions/"+OCC)
    order = broker("/v2/orders/"+ORDER)
    assert order["status"] == "filled" and order["symbol"] == OCC and order["side"] == "sell"
    assert Decimal(position["qty"]) == -Decimal(str(original["quantity"])) == -Decimal(str(owner["contracts"]))
    assert Decimal(order["filled_qty"]) == Decimal(str(owner["contracts"]))
    assert Decimal(position["avg_entry_price"]) == Decimal(str(original["entry_price"])) == Decimal(order["filled_avg_price"])
    payload = dict(original["source_payload"], superseded_by=OWNER,
                   superseded_table="options_positions", verified_order_id=ORDER,
                   management_transfer_reason="duplicate adoption of an existing Wheel contract")
    changes = dict(status="closed_adopted", realized_pnl_usd=None, exit_price=None,
                   exit_at=datetime.now(timezone.utc).isoformat(), source_payload=payload)
    print(json.dumps({"book": UID, "retire_duplicate": DUP, "keep_open": OWNER,
                      "broker_order": ORDER, "broker_contracts": position["qty"],
                      "new_status": changes["status"], "realized_pnl": None}))
    if "--apply" not in sys.argv:
        print("DRY RUN: nothing written.")
        return
    boots = relay.get("/rest/v1/ops_log_tail?select=line&line->>event=eq.engine_boot&order=ts.desc&limit=1")
    assert boots and "commit=681b08d" in boots[0]["line"]["reason"], "fixed engine must be running first"
    backup = ROOT / "logs" / ("LULG-before-repair-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".json")
    backup.write_text(json.dumps(dict(paper=original, wheel=owner, broker_position=position, broker_order=order), indent=2), encoding="utf-8")
    query = f"/rest/v1/paper_positions?id=eq.{DUP}&user_id=eq.{UID}&status=eq.open"
    if original.get("updated_at"):
        query += "&updated_at=eq." + urllib.parse.quote(original["updated_at"], safe="")
    result = relay._req("PATCH", query, changes, {"Prefer":"return=representation"})
    assert len(result) == 1, "row changed concurrently; no repair applied"
    assert row("paper_positions",DUP)["status"] == "closed_adopted"
    assert row("options_positions",OWNER)["status"] == "open"
    print("REPAIRED: one Wheel manager remains; broker untouched. Backup:", backup)

if __name__ == "__main__":
    main()
