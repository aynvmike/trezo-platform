"""Fail-open activity ledger for gate decisions.

Every approve / veto the Risk Manager emits is appended as one JSON line to
logs/activity-YYYY-MM-DD.jsonl (relative to the repo root). The midday
snapshot reads this file directly, so it can report what the agents scanned
and gated without reaching the live backend.

Hard rule: this must NEVER raise. A logging failure cannot affect a trading
decision, so every path swallows errors. Set TREZO_ACTIVITY_LOG=0 to disable.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading

_LOCK = threading.Lock()


def _log_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # agents/app/agents/activity_log.py -> repo root is three levels up.
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    override = os.getenv("TREZO_ACTIVITY_LOG_DIR")
    return override if override else os.path.join(root, "logs")


def record(event: str, ticker: str, *, tcs=None, strategy=None,
           reason: str = "", iv_rank=None, extra=None) -> None:
    """Append one gate-decision record. Never raises."""
    try:
        if os.getenv("TREZO_ACTIVITY_LOG", "1") == "0":
            return
        now = _dt.datetime.now(_dt.timezone.utc)
        rec = {
            "ts": now.isoformat(),
            "event": str(event),
            "ticker": str(ticker or "").upper(),
            "tcs": tcs,
            "strategy": strategy or "unknown",
            "iv_rank": iv_rank,
            "reason": reason or "",
        }
        if extra:
            try:
                rec.update(extra)
            except Exception:
                pass
        d = _log_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"activity-{now.strftime('%Y-%m-%d')}.jsonl")
        line = json.dumps(rec, default=str)
        with _LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        # Logging must never break a trading decision.
        return
