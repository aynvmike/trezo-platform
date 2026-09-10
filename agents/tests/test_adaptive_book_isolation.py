"""Per-book scope controls and real risk-path admission; no fixtures or network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tests import _bootstrap

_bootstrap.stub_config()
asa = _bootstrap.load_module("app.agents.adaptive_scope")
scope = _bootstrap.load_module("app.runtime.scope")
adaptive = _bootstrap.load_module("app.strategies.adaptive")
settings = _bootstrap.load_module("app.runtime.settings")
from tests.test_adaptive_scope_handler import _patched, _run, _event


def _posture(uid, **kw):
    values = dict(id=f"posture-{uid}", user_id=uid,
                  created_at=datetime.now(timezone.utc).isoformat(),
                  action="set_posture", scope="market", reason=f"Book {uid}",
                  trigger="regime:trending_up", severity="low", ttl_minutes=360)
    values.update(kw)
    return adaptive.ScopeAdjustment(**values)


def test_scope_requires_an_explicit_owner_and_never_inherits_primary():
    registry = scope._BookScopeState()
    registry.for_book("A").set_posture(_posture("A", tcs_bump=12,
                                               paused_strategies=("crypto_swing",)))
    assert registry.view("A").tcs_bump == 12
    for uid in (None, "", "B", "missing-book"):
        assert registry.view(uid).tcs_bump == 0
        assert registry.view(uid).paused_strategies == frozenset()
    try:
        registry.for_book("")
    except ValueError:
        pass
    else:
        raise AssertionError("Unowned adjustment acquired a control book")


def test_shared_event_obeys_each_books_own_autonomy_mode():
    registry = scope._BookScopeState()
    modes = {"A": "suggest", "B": "guarded", "C": "full"}
    persisted, reads = [], []
    def own_settings(uid):
        reads.append(uid)
        return SimpleNamespace(autonomy_mode=modes[uid])
    async def persist(adj):
        persisted.append(adj)
    with _patched(settings, get_bot_settings=own_settings), \
         _patched(asa, _book_ids=lambda: list(modes), scope_state=registry, _persist=persist):
        out = _run(asa.AdaptiveScopeAgent().on_message(_event(severity="low")))
    assert reads == ["A", "B", "C"]
    assert [(m.payload["user_id"], m.kind) for m in out] == [("A", "info"), ("C", "scope")]
    assert registry.view("A").flagged_tickers == frozenset()
    assert registry.view("B").flagged_tickers == frozenset()
    assert registry.view("C").flagged_tickers == frozenset({"TSLA"})
    assert [(a.user_id, a.status) for a in persisted] == [("A", "suggested"), ("C", "applied")]


def test_owned_event_never_changes_or_persists_a_sibling_control():
    registry = scope._BookScopeState()
    persisted = []
    async def persist(adj):
        persisted.append(adj)
    with _patched(asa, _book_ids=lambda: ["A", "B"], scope_state=registry,
                  _autonomy_mode=lambda uid: "full", _persist=persist):
        out = _run(asa.AdaptiveScopeAgent().on_message(_event(user_id="B")))
        unknown = _run(asa.AdaptiveScopeAgent().on_message(_event(user_id="missing")))
    assert len(out) == 1 and out[0].payload["user_id"] == "B"
    assert unknown == []
    assert registry.view("A").flagged_tickers == frozenset()
    assert registry.view("B").flagged_tickers == frozenset({"TSLA"})
    assert [a.user_id for a in persisted] == ["B"]


def test_unchanged_first_book_does_not_skip_other_books_in_tick():
    registry = scope._BookScopeState()
    registry.for_book("A").set_posture(_posture("A"))
    persisted = []
    async def persist(adj):
        persisted.append(adj)
    async def approved(uid):
        return []
    async def regime():
        return SimpleNamespace(regime="trending_up", summary="Trend confirmed", confidence=.9)
    with _patched(asa, _book_ids=lambda: ["A", "B"], scope_state=registry,
                  _autonomy_mode=lambda uid: "full", _persist=persist,
                  _pull_approved=approved, read_market_regime=regime):
        out = _run(asa.AdaptiveScopeAgent().tick())
    assert [m.payload["user_id"] for m in out] == ["B"]
    assert [a.user_id for a in persisted] == ["B"]
    assert registry.view("B").regime == "trending_up"


def test_expired_scope_does_not_keep_a_stale_risk_off_regime():
    registry = scope._BookScopeState()
    registry.for_book("A").set_posture(_posture(
        "A", trigger="regime:risk_off", tcs_bump=15,
        created_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()))
    registry.for_book("B").set_posture(_posture("B", tcs_bump=3))
    assert registry.view("A").tcs_bump == 0
    assert registry.view("A").regime == "choppy"
    assert registry.view("B").tcs_bump == 3


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return call
    def execute(self):
        return SimpleNamespace(data=self.rows)


class Client:
    def __init__(self, rows):
        self.query = Query(rows)
    def table(self, name):
        assert name == "strategy_scope_adjustments"
        return self.query


def test_approved_scope_query_filters_ownership_and_rejects_legacy_rows():
    now = datetime.now(timezone.utc).isoformat()
    rows = [dict(id="new", user_id="B", created_at=now, tcs_bump=5),
            dict(id="wrong", user_id="A", created_at=now, tcs_bump=15),
            dict(id="legacy", created_at=now, tcs_bump=15),
            dict(id="old", user_id="B", created_at=now, tcs_bump=1)]
    client = Client(rows)
    with _patched(asa, _supabase=lambda: client, _CONSUMED_IDS=set()):
        approved = _run(asa._pull_approved("B"))
        assert _run(asa._pull_approved("B")) == []
        assert _run(asa._pull_approved("")) == []
    assert [(a.user_id, a.tcs_bump) for a in approved] == [("B", 1), ("B", 5)]
    assert ("eq", ("user_id", "B"), {}) in client.query.calls


def test_persisted_adjustment_carries_its_book_and_original_creation_time():
    client = Client([])
    adj = _posture("B")
    with _patched(asa, _supabase=lambda: client):
        _run(asa._persist(adj))
    row = next(args[0] for name, args, kw in client.query.calls if name == "insert")
    assert row["user_id"] == "B"
    assert row["created_at"] == adj.created_at


def test_real_risk_path_a_paused_book_does_not_pause_its_sibling():
    from tests.test_risk_manager_bookkeyed import _desk, _signal, TWO_OPEN
    registry = scope._BookScopeState()
    registry.for_book("A").set_posture(_posture("A", paused_strategies=("crypto_swing",)))
    with _patched(scope, scope_state=registry), _desk(states=TWO_OPEN) as (agent, _):
        out = _run(agent.on_message(_signal()))
    verdicts = {m.payload["user_id"]: m for m in out if m.kind in ("approve", "veto")}
    assert set(verdicts) == {"A", "B"}
    assert verdicts["A"].kind == "veto" and "paused by Adaptive Scope" in verdicts["A"].payload["reason"]
    assert verdicts["B"].kind == "approve" and verdicts["B"].payload["book_scoped"] is True


def test_real_risk_path_uses_own_tuning_and_stop_geometry():
    from tests.test_risk_manager_bookkeyed import _desk, _signal, TWO_OPEN
    registry = scope._BookScopeState()
    registry.for_book("A").set_posture(_posture("A", tcs_bump=5, stop_multiplier=.5))
    with _patched(scope, scope_state=registry), _desk(states=TWO_OPEN) as (agent, _):
        out = _run(agent.on_message(_signal(tcs=38)))
    verdicts = {m.payload["user_id"]: m for m in out if m.kind in ("approve", "veto")}
    assert verdicts["A"].kind == "veto"
    assert verdicts["B"].kind == "approve"
    with _patched(scope, scope_state=registry), _desk(states=TWO_OPEN) as (agent, _):
        out = _run(agent.on_message(_signal(tcs=90)))
    verdicts = {m.payload["user_id"]: m for m in out if m.kind == "approve"}
    assert verdicts["A"].payload["stop_pct"] == .01
    assert verdicts["B"].payload["stop_pct"] == .02


def test_real_risk_path_one_disabled_book_never_disables_another():
    from tests.test_risk_manager_bookkeyed import _desk, _signal, TWO_OPEN
    books = {"A": settings.BotSettings(auto_trade_enabled=False),
             "B": settings.BotSettings(auto_trade_enabled=True)}
    with _desk(states=TWO_OPEN, books=books) as (agent, _):
        out = _run(agent.on_message(_signal()))
    verdicts = {m.payload["user_id"]: m for m in out if m.kind in ("approve", "veto")}
    assert verdicts["A"].kind == "veto" and "auto-trade is OFF" in verdicts["A"].payload["reason"]
    assert verdicts["B"].kind == "approve"


def test_real_risk_path_unknown_settings_do_not_enable_a_book_or_change_others():
    from tests.test_risk_manager_bookkeyed import _desk, _signal, TWO_OPEN
    books = {"A": settings._DEFAULTS, "B": settings.BotSettings()}
    with _desk(states=TWO_OPEN, books=books) as (agent, _):
        out = _run(agent.on_message(_signal()))
    verdicts = {m.payload["user_id"]: m for m in out if m.kind in ("approve", "veto")}
    assert verdicts["A"].kind == "veto"
    assert "settings unavailable" in verdicts["A"].payload["reason"]
    assert verdicts["B"].kind == "approve"


if __name__ == "__main__":
    import sys
    sys.exit(_bootstrap.run_tests(dict(globals())))
