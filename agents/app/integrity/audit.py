"""Integrity audit — compare Trezo's open paper positions to the REAL
Alpaca broker truth, and report (optionally quarantine) phantom rows:
positions Trezo shows as open that the broker does not actually hold.

Standalone + fail-safe by design:
  * The running agents service NEVER imports this module, so creating or
    running it cannot affect live trading. Run it any time.
  * READ-ONLY by default. `--repair` quarantines only confirmed STOCK
    phantoms (status='closed_phantom', realized 0) so they leave the live
    book with a distinct, auditable label (UI shows "Closed by: phantom").

Phantom detection reuses the proven reconcile guards:
  * trust gate — never treat "symbol absent at Alpaca" as phantom unless
    the fetch SUCCEEDED and returned >=1 equity position (kills the
    empty-read phantom-close bug, 2026-06-15).
  * 5-minute grace for just-submitted orders still filling.
  * Crypto rows are MODELED by design (Alpaca can't trade most ISO 20022
    coins), so they are reported "modeled", never phantom.
  * Options are reported for review, never auto-repaired (OCC matching is
    error-prone; conservative on purpose).

Usage (from trezo-platform/agents, with the venv):
  uv run python -m app.integrity.audit            # report only
  uv run python -m app.integrity.audit --repair   # + quarantine stock phantoms
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("integrity.audit")

GRACE_MIN = 5.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minutes_since(iso) -> float:
    if not iso:
        return 1e9
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 60.0
    except Exception:
        return 1e9


async def audit_all(repair: bool = False) -> dict:
    from app.config import get_settings
    from app.brokers.alpaca import alpaca_configured, get_positions, UserToken
    from app.integrations.web_tokens import get_user_broker_token

    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return {"ok": False, "error": "Supabase not configured."}
    if not alpaca_configured():
        return {"ok": False, "error": "Alpaca keys not configured."}

    from supabase import create_client
    client = create_client(s.supabase_url, s.supabase_service_role_key)

    def _users():
        return client.table("paper_accounts").select("user_id").execute()
    users = (await asyncio.to_thread(_users)).data or []

    keys = ["confirmed", "modeled", "phantom", "unverified", "options_review", "repaired"]
    totals = {k: 0 for k in keys}
    phantoms: list[dict] = []
    per_user: list[dict] = []

    for u in users:
        uid = u.get("user_id")
        if not uid:
            continue

        bt = await get_user_broker_token(uid, "alpaca")
        token = UserToken(
            access_token=bt.access_token,
            refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None

        fetch_ok = True
        try:
            ap = await get_positions(token=token)
        except Exception:
            ap, fetch_ok = [], False

        eq_syms: set[str] = set()
        opt_syms: set[str] = set()
        crypto_syms: set[str] = set()
        for p in ap:
            ac = str(p.get("asset_class") or "us_equity").lower()
            sym = str(p.get("symbol", "")).upper()
            if not sym:
                continue
            if ac == "us_equity":
                eq_syms.add(sym)
            elif "option" in ac:
                opt_syms.add(sym)
            elif ac == "crypto":
                crypto_syms.add(sym)

        # Only trust "absent = phantom" for stocks when the read succeeded
        # AND returned at least one equity position.
        trust = fetch_ok and bool(eq_syms)

        def _open(_uid=uid):
            return (
                client.table("paper_positions")
                .select("id, ticker, asset_type, side, quantity, entry_price, strategy, entry_at")
                .eq("user_id", _uid)
                .eq("status", "open")
                .execute()
            )
        rows = (await asyncio.to_thread(_open)).data or []

        u_counts = {k: 0 for k in keys}
        for r in rows:
            at = str(r.get("asset_type") or "stock").lower()
            sym = str(r.get("ticker") or "").upper()
            age = _minutes_since(r.get("entry_at"))

            if at == "crypto":
                cls = "confirmed" if any(sym in c or c.startswith(sym) for c in crypto_syms) else "modeled"
            elif at in ("option", "options"):
                if any(sym in o or o.startswith(sym) for o in opt_syms):
                    cls = "confirmed"
                else:
                    cls = "options_review" if fetch_ok else "unverified"
            else:  # stock
                if sym in eq_syms:
                    cls = "confirmed"
                elif not trust or age < GRACE_MIN:
                    cls = "unverified"
                else:
                    cls = "phantom"

            u_counts[cls] += 1
            totals[cls] += 1

            if cls == "phantom":
                pid = r.get("id")
                phantoms.append({
                    "user_id": uid, "id": pid, "ticker": sym,
                    "strategy": r.get("strategy"), "entry_at": r.get("entry_at"),
                    "age_min": round(age, 1),
                })
                if repair:
                    def _quar(rid=pid):
                        return (
                            client.table("paper_positions")
                            .update({
                                "status": "closed_phantom",
                                "exit_price": None,
                                "realized_pnl_usd": 0,
                                "exit_at": _now_iso(),
                            })
                            .eq("id", rid)
                            .eq("status", "open")
                            .execute()
                        )
                    try:
                        await asyncio.to_thread(_quar)
                        u_counts["repaired"] += 1
                        totals["repaired"] += 1
                    except Exception as e:  # noqa: BLE001
                        logger.warning("quarantine failed for %s: %s", pid, e)

        per_user.append({"user_id": uid, "fetch_ok": fetch_ok, "trust": trust, **u_counts})

    return {
        "ok": True, "as_of": _now_iso(), "repair": repair,
        "totals": totals, "phantoms": phantoms, "per_user": per_user,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Trezo integrity audit (open positions vs Alpaca truth).")
    ap.add_argument("--repair", action="store_true",
                    help="Quarantine confirmed stock phantoms (status=closed_phantom, realized 0).")
    args = ap.parse_args()

    rep = asyncio.run(audit_all(repair=args.repair))
    print(json.dumps(rep, indent=2, default=str))
    if rep.get("ok"):
        t = rep["totals"]
        print(
            "\nSUMMARY  confirmed=%d  modeled=%d  PHANTOM=%d  unverified=%d  options_review=%d  repaired=%d"
            % (t["confirmed"], t["modeled"], t["phantom"], t["unverified"], t["options_review"], t["repaired"])
        )
        try:
            os.makedirs("logs", exist_ok=True)
            path = os.path.join("logs", "integrity-audit-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
            with open(path, "w") as f:
                json.dump(rep, f, indent=2, default=str)
            print("Saved report -> " + path)
        except Exception as e:  # noqa: BLE001
            print("(could not write report file: %s)" % e)


if __name__ == "__main__":
    main()
