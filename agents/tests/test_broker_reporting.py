"""Offline evidence-export guards: GET-only routes, identity, strict completeness."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests

reporting = load_module("app.brokers.reporting")
START = "2026-09-17T00:00:00Z"
END = "2026-09-18T00:00:00Z"
HISTORY = {"timeframe": "1D", "base_value": 100, "timestamp": [1, 2],
           "equity": [100, None], "profit_loss": [0, None],
           "profit_loss_pct": [0, None], "cashflow": {"DIV": [2, None]}}


def accounts():
    return [SimpleNamespace(account_key=f"book-{i}", account_id=f"slot-{i}",
                            base_url=reporting.PAPER_BASE_URL,
                            headers=lambda i=i: {"APCA-API-KEY-ID": f"key-{i}",
                                                 "APCA-API-SECRET-KEY": f"secret-{i}"})
            for i in range(3)]


class Client:
    def __init__(self, override=None):
        self.calls = []
        self.override = override

    def get(self, url, *, params=None, headers=None):
        path = url.removeprefix(reporting.PAPER_BASE_URL)
        call = {"url": url, "path": path, "params": dict(params or {}), "headers": dict(headers)}
        self.calls.append(call)
        response = self.override(call) if self.override else None
        if response is not None:
            if isinstance(response, Exception):
                raise response
            return response
        if path == "/v2/account":
            data = {"id": "broker-" + headers["APCA-API-KEY-ID"], "cash": "0",
                    "equity": "100", "buying_power": "200", "status": "ACTIVE",
                    "currency": "USD", "account_number": "PRIVATE-NUMBER",
                    "secret": "PRIVATE-RESPONSE", "trading_blocked": False}
        elif path == "/v2/account/portfolio/history":
            data = deepcopy(HISTORY)
        else:
            data = []
        return response_for(data)


def response_for(data, status=200):
    return SimpleNamespace(status_code=status, json=lambda: deepcopy(data),
                           text="PRIVATE-ERROR-BODY")


def export(client, **kwargs):
    return reporting.export_audit(accounts(), after=START, until=END,
                                  client=client, **kwargs)


def test_three_independent_routes_hash_identities_and_preserve_actual_zero():
    client = Client()
    result = export(client)
    assert result["complete"] and result["distinct_broker_identities_verified"]
    assert len({book["broker_id_hash"] for book in result["books"]}) == 3
    assert [book["account"]["data"]["cash"] for book in result["books"]] == ["0"] * 3
    assert all(book["account"]["data"]["last_equity"] is None for book in result["books"])
    assert len(client.calls) == 18
    for i in range(3):
        calls = [c for c in client.calls if c["headers"]["APCA-API-KEY-ID"] == f"key-{i}"]
        assert len(calls) == 6
        assert all(c["headers"]["APCA-API-SECRET-KEY"] == f"secret-{i}" for c in calls)
    encoded = json.dumps(result, allow_nan=False)
    for private in ("PRIVATE", "broker-key-", "APCA", "secret-", "key-0"):
        assert private not in encoded


def test_duplicate_identities_stop_before_position_or_history_reads():
    def override(call):
        return response_for({"id": "same-broker", "cash": 1, "equity": 2, "buying_power": 3})
    client = Client(override)
    result = export(client)
    assert not result["complete"] and not result["distinct_broker_identities_verified"]
    assert len(client.calls) == 3
    assert all(book["positions"]["data"] is None for book in result["books"])


def test_failed_identity_still_checks_all_three_and_does_not_guess():
    def override(call):
        if call["headers"]["APCA-API-KEY-ID"] == "key-1":
            return response_for({}, 503)
    client = Client(override)
    result = export(client)
    assert len(client.calls) == 3
    assert result["books"][1]["account"]["data"] is None
    assert result["books"][1]["account"]["error"] == "broker_unavailable"
    assert result["books"][0]["broker_id_hash"] is not None
    assert result["books"][2]["broker_id_hash"] is not None


def test_nonfinite_or_missing_account_values_are_unknown_not_zero():
    for invalid in ("NaN", float("inf"), "", None, True):
        client = Client(lambda call: response_for({"id": "id", "cash": invalid,
                                                   "equity": 5, "buying_power": 2}))
        result = export(client)
        assert result["books"][0]["account"]["data"] is None
        assert not result["complete"]


def test_failures_are_null_and_successful_empty_collections_stay_empty():
    def override(call):
        if call["path"] == "/v2/positions" and call["headers"]["APCA-API-KEY-ID"] == "key-1":
            return response_for({}, 429)
    result = export(Client(override))
    assert result["books"][0]["positions"]["data"] == []
    assert result["books"][1]["positions"]["data"] is None
    assert result["books"][1]["positions"]["error"] == "rate_limited"
    assert not result["complete"]
    assert "PRIVATE" not in json.dumps(result)


def test_activities_include_dividend_transfer_and_option_events_without_filter():
    pages = [[{"id": "a", "activity_type": "DIV", "net_amount": "4"},
              {"id": "b", "activity_type": "CSD", "net_amount": "1000"}],
             [{"id": "c", "activity_type": "OPEXP", "qty": "1"}]]
    client = Client(lambda call: response_for(pages.pop(0)))
    rows = reporting.PaperReader(accounts()[0], client).activities(
        reporting._date(START), reporting._date(END), 3, page_size=2)
    assert [r["activity_type"] for r in rows] == ["DIV", "CSD", "OPEXP"]
    assert client.calls[1]["params"]["page_token"] == "b"
    assert all("activity_types" not in c["params"] and "category" not in c["params"] for c in client.calls)


def test_full_or_repeated_activity_pages_do_not_claim_complete():
    row = {"id": "a", "activity_type": "DIV", "net_amount": "4"}
    reader = reporting.PaperReader(accounts()[0], Client(lambda call: response_for([row])))
    for limit, expected in ((1, "pagination_limit"), (3, "pagination_no_progress")):
        result = reporting._read(lambda: reader.activities(reporting._date(START),
                                      reporting._date(END), limit, page_size=1))
        assert result["data"] is None and result["error"] == expected


def test_orders_page_by_id_so_equal_timestamps_are_not_lost():
    stamp = "2026-09-17T12:00:00Z"
    def row(oid, ts=stamp): return {"id": oid, "status": "filled", "submitted_at": ts}
    pages = [[row("a"), row("b")], [row("c"), row("d", START)]]
    client = Client(lambda call: response_for(pages.pop(0)))
    rows = reporting.PaperReader(accounts()[0], client).orders(
        reporting._date(START), reporting._date(END), 3, page_size=2)
    assert [r["id"] for r in rows] == ["a", "b", "c"]
    assert "after" in client.calls[0]["params"] and "until" in client.calls[0]["params"]
    assert client.calls[1]["params"]["before_order_id"] == "b"
    assert "after" not in client.calls[1]["params"] and "until" not in client.calls[1]["params"]


def test_open_orders_include_old_nested_protection_legs():
    rows = [{"id": "parent", "status": "new", "submitted_at": "2020-01-01T00:00:00Z",
             "legs": [{"id": "stop", "status": "new", "stop_price": "9.99",
                       "private_field": "PRIVATE"}]}]
    client = Client(lambda call: response_for(rows))
    result = reporting.PaperReader(accounts()[0], client).orders(
        reporting._date(START), reporting._date(END), 2, open_only=True)
    assert result[0]["legs"][0]["stop_price"] == "9.99"
    assert "after" not in client.calls[0]["params"] and "until" not in client.calls[0]["params"]
    assert "PRIVATE" not in json.dumps(result)


def test_order_nanoseconds_after_start_are_not_truncated_out_of_window():
    rows = [{"id": "boundary", "status": "filled", "submitted_at": "2026-09-17T00:00:00.000000001Z"}]
    client = Client(lambda call: response_for(rows))
    result = reporting.PaperReader(accounts()[0], client).orders(
        reporting._date(START), reporting._date(END), 2)
    assert [row["id"] for row in result] == ["boundary"]


def test_history_keeps_missing_observations_and_cashflows_without_return_math():
    client = Client()
    result = reporting.PaperReader(accounts()[0], client).history(reporting._date(START), reporting._date(END))
    assert result["equity"] == [100, None]
    assert result["profit_loss_pct"] == [0, None]
    assert result["cashflow"] == {"DIV": [2, None]}
    assert client.calls[0]["params"] == {"start": reporting._date(START).isoformat(),
        "end": reporting._date(END).isoformat(), "timeframe": "1D", "cashflow_types": "ALL"}


def test_invalid_history_shape_is_unknown():
    for bad in ({**HISTORY, "equity": [100]}, {**HISTORY, "equity": [100, "NaN"]},
                {**HISTORY, "timestamp": [1, None]}, {**HISTORY, "cashflow": {"DIV": [1]}}):
        reader = reporting.PaperReader(accounts()[0], Client(lambda c: response_for(bad)))
        result = reporting._read(lambda: reader.history(reporting._date(START), reporting._date(END)))
        assert result["data"] is None and not result["complete"]


def test_unknown_endpoints_and_foreign_origins_are_rejected_before_credentials_leave():
    client = Client()
    reader = reporting.PaperReader(accounts()[0], client)
    result = reporting._read(lambda: reader.get("/v2/orders/unsafe"))
    assert result["error"] == "endpoint_refused" and not client.calls
    for origin in ("https://api.alpaca.markets", "https://example.org", "https://paper-api.alpaca.markets.evil"):
        account = accounts()[0]
        account.base_url = origin
        result = reporting._read(lambda: reporting.PaperReader(account, client))
        assert result["data"] is None and not client.calls


def test_bad_windows_and_page_limits_make_no_requests():
    client = Client()
    for kwargs in ({"after": "2026-09-17"}, {"after": END, "until": START},
                   {"after": "2000-01-01T00:00:00Z", "until": END},
                   {"max_pages": 0}, {"max_pages": 101}):
        result = reporting._read(lambda: reporting.export_audit(accounts(), client=client, **kwargs))
        assert result["data"] is None and not client.calls


def test_exception_messages_and_response_bodies_never_escape():
    client = Client(lambda call: RuntimeError("PRIVATE headers secret"))
    result = export(client)
    assert "PRIVATE" not in json.dumps(result)
    assert result["books"][0]["account"]["error"] == "transport_failed"


def test_fresh_reporting_import_does_not_import_runtime_scheduler_or_alpaca():
    agents = Path(__file__).resolve().parents[1]
    code = ("import sys; from app.brokers import reporting; "
            "assert not any(n.startswith('app.runtime') or n == 'app.brokers.alpaca' "
            "or n.startswith('app.integrations') for n in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], cwd=agents,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_cli_refuses_existing_output_before_loading_settings():
    script = Path(__file__).resolve().parents[1] / "scripts" / "export_broker_audit.py"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "evidence.json"
        target.write_text("existing evidence", encoding="utf-8")
        result = subprocess.run([sys.executable, str(script), "--output", str(target)],
                                cwd=directory, capture_output=True, text=True, timeout=20)
        assert result.returncode == 2 and not result.stdout
        assert json.loads(result.stderr) == {"error": "output_exists"}
        assert target.read_text(encoding="utf-8") == "existing evidence"


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
