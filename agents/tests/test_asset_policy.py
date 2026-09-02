"""Guard tests: no asset class may be managed by accident.

The bug these exist to prevent (2026-08-17): the profit ladder was gated
on `at == "stock"`, so Alpaca-routed crypto could never bank a slice of a
winner. Nobody decided that. It was true because stocks were the only
asset class when the line was written, and no test would have noticed.

Run: pytest agents/tests/test_asset_policy.py
 or: python -m agents.tests.test_asset_policy
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, quiet_activity_log, run_tests  # noqa: E402

ap = load_module("app.runtime.asset_policy")


# --- every asset class the code actually uses must be registered ----------

def test_every_asset_type_in_the_codebase_has_a_policy():
    """Grep the source for asset_type comparisons and require a policy for
    each. This is the test that would have caught `at == "stock"` standing
    in for a decision."""
    root = Path(__file__).resolve().parents[1] / "app"
    seen: set[str] = set()
    pattern = re.compile(
        r'asset_type["\']?\s*(?:==|!=)\s*["\']([a-z_0-9]+)["\']'
        r'|at\s*(?:==|!=)\s*["\']([a-z_0-9]+)["\']')
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pattern.finditer(text):
            val = m.group(1) or m.group(2)
            if val:
                seen.add(val)
    missing = sorted(v for v in seen
                     if not ap.is_registered(v) and v not in ap.SENTINELS)
    assert not missing, (
        f"asset types compared in code with no AssetPolicy: {missing}. "
        f"Add one in app/runtime/asset_policy.py -- an unregistered class "
        f"is managed defensively and never stepped, which is safe but "
        f"probably not what you meant.")


def test_sentinels_are_not_mistaken_for_asset_classes():
    """`auto` reads like an asset type in a comparison but means "detect
    it". It must stay UNREGISTERED -- if someone ever gives it a policy,
    positions would be managed under a class that does not exist."""
    # 2026-09-02: policy_for() on an unregistered class writes an
    # asset_policy_missing receipt. Captured, not written -- 'AUTO' was
    # landing in the live feed on every deploy-gate run (run_all's net).
    with quiet_activity_log():
        for s in ap.SENTINELS:
            assert not ap.is_registered(s), (
                f"{s!r} is a sentinel, not an asset class -- it must not have "
                f"a policy")
            assert ap.policy_for(s) is ap.UNKNOWN_POLICY


def test_the_classes_we_promised_are_all_there():
    for t in ("stock", "crypto", "option", "forex", "future", "bond", "fund"):
        assert ap.is_registered(t), f"{t} lost its policy"


def test_unknown_asset_type_fails_closed():
    with quiet_activity_log() as said:
        pol = ap.policy_for("dogecoin_futures_on_the_moon")
    assert pol is ap.UNKNOWN_POLICY
    # 2026-09-02: the miss must be SAID -- the receipt is how a forgotten
    # policy gets noticed -- and captured here, never written from a test.
    assert [(e, t) for e, t, _ in said] == [
        ("asset_policy_missing", "DOGECOIN_FUTURES_ON_THE_MOON")], said
    assert pol.client_side_exits is True, "we must still watch it"
    assert pol.supports_partial_step is False, "we must not invent behaviour"
    assert pol.adoptable is False


def test_strict_mode_raises_instead_of_guessing():
    os.environ["TREZO_ASSET_POLICY_STRICT"] = "1"
    try:
        raised = False
        try:
            ap.policy_for("not_a_real_class")
        except KeyError:
            raised = True
        assert raised, "strict mode must raise on an unregistered class"
    finally:
        os.environ.pop("TREZO_ASSET_POLICY_STRICT", None)


# --- the specific defects, encoded so they cannot return ------------------

def test_crypto_can_step_out_of_a_winner():
    """The 2026-08-17 defect: broker-routed crypto was excluded from the
    profit ladder by an `at == "stock"` gate."""
    pol = ap.policy_for("crypto")
    assert pol.supports_partial_step is True
    assert pol.fractional is True
    assert pol.session_gated is False, "crypto trades 24/7"
    assert pol.native_brackets is False, (
        "Alpaca holds no bracket on crypto -- if this ever becomes True, "
        "the client-side exit path in position_monitor is dead code and "
        "coins are relying on a stop that does not exist")


def test_a_coin_slice_does_not_round_to_zero():
    pol = ap.policy_for("crypto")
    assert pol.slice_size(44.34, 0.5) > 0
    assert pol.slice_size(0.0031, 0.5) > 0, (
        "rounding a coin slice to a whole number is how a fractional "
        "position silently stops stepping")


def test_a_share_slice_is_whole_and_leaves_a_remainder():
    pol = ap.policy_for("stock")
    assert pol.slice_size(5, 0.5) == 2.0
    assert pol.slice_size(1, 0.5) == 0.0, "cannot split a single share"
    assert pol.can_step(1) is False
    assert pol.can_step(2) is True


def test_one_option_contract_cannot_be_split():
    pol = ap.policy_for("option")
    assert pol.slice_size(1, 0.5) == 0.0
    assert pol.slice_size(4, 0.5) == 2.0


def test_buy_and_hold_classes_are_left_alone_on_purpose():
    for t in ("bond", "fund"):
        pol = ap.policy_for(t)
        assert pol.supports_partial_step is False
        assert pol.can_step(1000) is False


def test_401k_and_ira_resolve_to_the_fund_policy():
    for alias in ("401k", "ira", "retirement", "mutual_fund"):
        assert ap.policy_for(alias).asset_type == "fund"


def test_broker_spellings_resolve():
    assert ap.policy_for("us_equity").asset_type == "stock"
    assert ap.policy_for("us_option").asset_type == "option"
    assert ap.policy_for("fx").asset_type == "forex"


# --- trail policy ---------------------------------------------------------

def test_dca_now_has_the_continuous_trail():
    """The XRP giveback: DCA had rungs starting at +3% against a ~6%
    target and nothing at all protecting a gain below the first rung."""
    assert ap.trail_policy_for("crypto_dca").continuous_trail is True


def test_swing_and_scalp_keep_theirs():
    assert ap.trail_policy_for("crypto_swing").continuous_trail is True
    assert ap.trail_policy_for("crypto_scalp").continuous_trail is True
    assert ap.trail_policy_for("crypto_scalp").arm_breakeven_at_cost is True


def test_hodl_is_deliberately_not_trailed():
    pol = ap.trail_policy_for("crypto_hodl")
    assert pol.continuous_trail is False, (
        "a HODL is meant to ride; it has its own +40%/20% trail. If you "
        "are changing this, change it on purpose and say so here")


def test_an_unnamed_strategy_still_gets_protection():
    """A new strategy must not inherit 'nothing' by being forgotten."""
    assert ap.trail_policy_for("some_new_lane_2027").continuous_trail is True
    assert ap.trail_policy_for("").continuous_trail is True
    assert ap.trail_policy_for(None).continuous_trail is True


def test_bare_mode_names_resolve():
    assert ap.trail_policy_for("dca").continuous_trail is True
    assert ap.trail_policy_for("swing").continuous_trail is True


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
