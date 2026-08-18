"""Archivist -- ships the box's memory somewhere the box cannot reach.

Hourly: activity logs + runtime caches + book state -> Supabase Storage.
Weekly (Sunday): the same bundle, every log we still have, -> Dropbox.

Two vendors on purpose. Keeping the ledger and its only backup with one
provider is not redundancy, it is a single point of failure with a
comforting name.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .base import Agent, AgentMessage


class ArchivistAgent(Agent):
    name = "archivist"
    tick_interval_seconds = 900        # every 15 min; gated below

    _last_hourly: str = ""             # YYYYmmddHH
    _last_full: str = ""               # YYYY-Www

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        try:
            from app.runtime.archive import enabled, run_archive
        except Exception:  # noqa: BLE001
            return out
        if not enabled():
            return out

        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y%m%d%H")
        week_key = now.strftime("%G-W%V")

        # Weekly full run first, so a week boundary does not also spend
        # the hourly slot on a second upload of the same data.
        want_full = (now.weekday() == 6 and week_key != type(self)._last_full)
        if want_full:
            type(self)._last_full = week_key
            rep = await run_archive(full=True)
            out.append(AgentMessage(agent=self.name, kind="info",
                                    payload={"event": "archive_full", **rep}))
            type(self)._last_hourly = hour_key
            return out

        if hour_key != type(self)._last_hourly:
            type(self)._last_hourly = hour_key
            rep = await run_archive(full=False)
            out.append(AgentMessage(agent=self.name, kind="info",
                                    payload={"event": "archive_hourly", **rep}))
        return out
