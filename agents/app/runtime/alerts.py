"""Outbound alerts -- the channel the platform never had.

WHY THIS FILE EXISTS (2026-08-18)
On 8/17 the 25k and 75k books were found holding seventeen positions
that Trezo's ledger did not know about: no stop, no target, no ladder,
and on crypto no broker bracket either. They had been that way for five
days. Then the engine went down at 15:30 ET and nobody noticed for
fifteen hours.

None of that was undetected. `route_orphan` fired 46 times in two
hours. The reconciler logged 55 and 50 phantom closes. ops_watchdog
raised stuck-agent alerts at severity 'urgent'. The platform had been
saying so, continuously, in a table and a log file that nobody reads
unless they already suspect something is wrong.

So this module is not another detector. It is the missing exit: one
function that gets a message OUT of the machine and in front of a
person. Everything that already knows something is wrong can now say so
somewhere it will be seen.

DESIGN NOTES
- ONE env var to switch on: TREZO_ALERT_WEBHOOK. Discord and Slack are
  detected from the URL, because those two shapes cover almost every
  webhook a person actually has. Unset = silent no-op, so nothing here
  can break an engine that has not configured it.
- NEVER raises, never blocks a tick. An alerting path that can take the
  trading loop down is worse than no alerting path.
- DEDUPED by key, because the failure modes here repeat every tick.
  route_orphan fired 46 times in two hours; 46 identical pings would
  train the reader to ignore the channel, which returns us to exactly
  where we started.
- Severity decides urgency, not volume. 'urgent' repeats every 30 min
  while the condition holds; 'warn' every 4 hours; 'info' once a day.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

_SENT: dict[str, float] = {}

# How long a given alert key stays quiet after being sent, by severity.
_QUIET_S = {
    "urgent": 30 * 60,
    "warn": 4 * 60 * 60,
    "info": 24 * 60 * 60,
}

_COLOUR = {          # Discord embed colours
    "urgent": 0xE03131,
    "warn": 0xF08C00,
    "info": 0x1971C2,
    "good": 0x2F9E44,
}

_EMOJI = {"urgent": "🔴", "warn": "🟠", "info": "🔵", "good": "🟢"}


def webhook_url() -> str:
    # Settings FIRST (that is where agents/.env values actually live;
    # see config.py trezo_alert_webhook, 2026-08-28), env as fallback
    # for ad-hoc shells that export it.
    try:
        from app.config import get_settings
        v = (getattr(get_settings(), "trezo_alert_webhook", "") or "").strip()
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    return (os.getenv("TREZO_ALERT_WEBHOOK", "") or "").strip()


def configured() -> bool:
    return bool(webhook_url())


def _should_send(key: str, severity: str) -> bool:
    """Dedupe. An empty key always sends (deliberate one-offs)."""
    if not key:
        return True
    quiet = _QUIET_S.get(severity, 3600)
    last = _SENT.get(key, 0.0)
    if (time.time() - last) < quiet:
        return False
    _SENT[key] = time.time()
    return True


def _payload(url: str, severity: str, title: str, body: str,
             fields: Optional[dict]) -> dict:
    icon = _EMOJI.get(severity, "•")
    detail = body or ""
    if fields:
        detail += "\n" + "\n".join(f"**{k}:** {v}" for k, v in fields.items())
    if "slack.com" in url or "slack" in url:
        text = f"{icon} *{title}*\n{detail}"
        return {"text": text}
    # Discord (and anything Discord-compatible)
    return {
        "username": "Trezo",
        "embeds": [{
            "title": f"{icon} {title}"[:250],
            "description": detail[:3900],
            "color": _COLOUR.get(severity, _COLOUR["info"]),
        }],
    }


async def notify(title: str, body: str = "", *,
                 severity: str = "warn", key: str = "",
                 fields: Optional[dict] = None) -> bool:
    """Send one alert. Returns True if it actually went out.

    Safe to call from anywhere, including inside an except block: it
    swallows every error, because an alert that crashes the caller is a
    worse bug than the one it was reporting.
    """
    url = webhook_url()
    if not url:
        return False
    if not _should_send(key, severity):
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=_payload(
                url, severity, title, body, fields))
            ok = 200 <= r.status_code < 300
    except Exception:  # noqa: BLE001
        ok = False
    # Mirror into the activity log either way, so the local record is
    # complete even when the channel is down.
    try:
        from app.agents.activity_log import record
        record("alert_sent" if ok else "alert_failed", title[:40],
               reason=(body or "")[:280],
               extra={"severity": severity, "key": key})
    except Exception:  # noqa: BLE001
        pass
    return ok


def notify_sync(title: str, body: str = "", **kw) -> bool:
    """For call sites that are not async. Fire-and-forget."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(notify(title, body, **kw))
        except Exception:  # noqa: BLE001
            return False
    loop.create_task(notify(title, body, **kw))
    return True


async def send_test() -> dict:
    """Prove the channel works end to end. Used by the relay and by
    ops_watchdog on the first tick after a restart."""
    if not configured():
        return {"ok": False, "error": "TREZO_ALERT_WEBHOOK is not set"}
    ok = await notify(
        "Alert channel connected",
        "Trezo can now reach you when something breaks. This is the "
        "channel that did not exist on 2026-08-17, which is why five "
        "days of unmanaged positions and a fifteen-hour outage both "
        "went unnoticed.",
        severity="good", key="")
    return {"ok": ok}
