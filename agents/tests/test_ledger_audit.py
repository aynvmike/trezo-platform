"""Offline accounting regressions for Claude's supplied audit replacement."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("trezo_ledger_audit", Path(__file__).resolve().parents[2] / "ops/ledger_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def fill(n, side, qty, price, day=1, order=None, symbol="BTC/USD"):
    return {"id": str(n), "order_id": order or str(n), "symbol": symbol,
            "side": side, "qty": str(qty), "price": str(price),
            "transaction_time": "2026-07-%02dT%02d:00:00Z" % (day, n % 24)}


def test_fifo_partial_fills_one_entry_order_and_costs_on_both_sides():
    rows = [fill(1, "buy", 1, 100, order="entry"), fill(2, "buy", 1, 110, order="entry"),
            fill(3, "sell", 1.5, 120), fill(4, "sell", .5, 130)]
    trips, matched, inventory, issues = audit.fifo(rows, {"BTCUSD"})
    assert len(trips) == 1 and trips[0]["pnl"] == 35
    assert trips[0]["entry_notional"] == 210 and trips[0]["exit_notional"] == 245
    assert not issues and not inventory["BTCUSD"]
    assert audit.stats(trips, 25, 5)["modeled_net_usd"] == 33.63


def test_since_keeps_prior_entry_basis():
    book = {"fills": [fill(1,"buy",1,100,1), fill(2,"sell",1,120,25)],
            "positions": [], "history_complete": True}
    result = audit.audit_book(book, "2026-07-24")
    assert result["summary"]["gross_usd"] == 20
    assert result["summary"]["n_completed_entry_orders"] == 1


def test_open_partial_position_is_not_a_completed_sample():
    trips, matched, inventory, issues = audit.fifo([fill(1,"buy",2,100),fill(2,"sell",1,90)], {"BTCUSD"})
    assert not trips and len(matched) == 1 and inventory["BTCUSD"] == 1


def test_missing_basis_is_incomplete_not_a_crypto_short():
    result = audit.audit_book({"fills":[fill(1,"sell",1,100)],"positions":[],"history_complete":True},"2026-07-01")
    assert result["summary"]["verdict"] == "INCOMPLETE"


def test_inventory_mismatch_and_coin_fees_block_verdict():
    b = {"fills":[fill(1,"buy",1,100)],"positions":[],"history_complete":True,
         "activities":[{"activity_type":"CFEE","qty":"-.0025"}]}
    r = audit.audit_book(b,"2026-07-01")
    assert len(r["issues"]) == 2 and r["summary"]["verdict"] == "INCOMPLETE"


def test_drawdown_counts_initial_loss_and_uses_peak_at_trough():
    assert audit.drawdown([-10,-20],baseline=0)["usd"] == -20
    assert audit.drawdown([100,50,1000,900])["pct"] == -50


def test_pagination_does_not_silently_truncate_or_repeat():
    pages = iter([([{"id":"one"}], {}), ([], {})])
    with patch.object(audit,"request",side_effect=lambda *a:next(pages)):
        assert len(audit.activities({})) == 1
    with patch.object(audit,"request",return_value=([{"id":"one"}], {})):
        try:
            audit.activities({})
        except audit.AuditError:
            pass
        else:
            assert False, "repeated page accepted"
    with patch.object(audit,"request",return_value=([{"id":"one"}], {})):
        try:
            audit.activities({},max_pages=1)
        except audit.AuditError:
            pass
        else:
            assert False, "page cap treated as complete"


def test_clustered_sample_cannot_pass_on_one_day_or_small_n():
    def trade(day, pnl):
        return {"pnl":audit.number(pnl),"entry_notional":audit.ZERO,"exit_notional":audit.ZERO,
                "closed_at":"2026-07-%02dT12:00:00Z"%day}
    assert audit.stats([trade(1,1)]*60)["verdict"] == "INSUFFICIENT"
    assert audit.stats([trade(i,1) for i in range(1,11)])["verdict"] == "INSUFFICIENT"
    assert audit.stats([trade(i,1) for i in range(1,11)]*6)["verdict"] == "PASS"
    assert audit.stats([trade(i,-1) for i in range(1,11)]*6)["verdict"] == "FAIL"
    json.dumps(audit.stats([trade(1,1)]),allow_nan=False)


def test_bad_numbers_and_duplicate_fills_are_rejected():
    for v in ("NaN","Infinity",None):
        try:
            audit.number(v)
        except audit.AuditError:
            pass
        else:
            assert False
    f = fill(1,"buy",1,100)
    try:
        audit.fifo([f,f],{"BTCUSD"})
    except audit.AuditError:
        pass
    else:
        assert False


def test_ledger_preserves_book_boundaries_and_missing_pnl():
    rows=[{'id':'a','user_id':'A','strategy':'s','asset_type':'crypto','status':'closed_stop','realized_pnl_usd':None},
          {'id':'b','user_id':'B','strategy':'s','asset_type':'crypto','status':'closed_target','realized_pnl_usd':'10','fees_usd':'2'}]
    result=audit.ledger_summary(rows)
    assert len(result)==2 and result[0]['missing_pnl']==1
    assert result[1]['reported_realized_usd']==10


def test_supabase_short_pages_use_content_range():
    pages=iter([([{'id':'a','asset_type':'crypto','status':'closed_stop'}],{'Content-Range':'0-0/2'}),
                ([{'id':'b','asset_type':'crypto','status':'closed_stop'}],{'Content-Range':'1-1/2'})])
    with patch.object(audit,'request',side_effect=lambda *a:next(pages)):
        result=audit.fetch_ledger({'SUPABASE_URL':'https://example.supabase.co','SUPABASE_SERVICE_KEY':'fake'},'2026-07-01')
    assert result['by_book_strategy'][0]['rows']==2


if __name__ == "__main__":
    for name,value in list(globals().items()):
        if name.startswith("test_"):
            value()
