"""Archive -- get everything off the box, so the box stops mattering.

WHY (Mike, 2026-08-18, after the engine sat dead for 15 hours)
"I do not want to lose access to the data and information because of a
crash... having to rely on the VM to update the data and information is
not sitting too well."

Fair. But the useful version of that instinct is not "back up the
server". It is: NOTHING SHOULD EXIST ONLY ON THE SERVER. Then the
server is disposable, you rebuild rather than restore, and downgrading
or replacing it stops being a decision at all.

Most of Trezo already passes that test. The ledger, accounts, outcomes
and kill-switch state live in Supabase. The code lives in GitHub and on
Mike's PC. Positions live at Alpaca. Agent memories live in mem0. If
this instance were deleted mid-tick, none of that would be lost.

What does NOT pass, and what this module exists for:

  * `logs/activity-*.jsonl` -- the full activity log. Supabase only ever
    received a rolling 10-minute tail capped at 120 lines, which is why
    the 8/17 forensics had to be done against files on the box. The most
    valuable diagnostic record we own was the least protected.
  * the runtime caches: _proposals.json, _digest_history.json,
    _research_seen.json, crypto_discovered.json
  * a point-in-time copy of the book state, so a Supabase mistake is
    survivable too

TWO TIERS, deliberately different vendors:
  * hourly -> Supabase Storage. The engine already holds that key, so
    this costs no new credential and starts working immediately.
  * weekly -> Dropbox. Because putting the ledger and its backups with
    the same provider is not a backup, it is a bigger single point of
    failure wearing a reassuring name.

Never raises. An archive that can take the trading loop down would be a
worse bug than the data loss it prevents.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(os.getenv("TREZO_REPO_DIR", r"C:\Trezo\trezo-platform"))
LOG_DIR = REPO / "logs"
BUCKET = os.getenv("TREZO_ARCHIVE_BUCKET", "trezo-archive")

# Files that exist ONLY on the box. Anything added here is, by
# definition, something we would otherwise lose.
RUNTIME_FILES = [
    "agents/app/knowledge/_proposals.json",
    "agents/app/knowledge/_digest_history.json",
    "agents/app/knowledge/_research_seen.json",
    "agents/app/data/crypto_discovered.json",
]


def enabled() -> bool:
    return os.getenv("TREZO_ARCHIVE_ENABLED", "1") != "0"


def _supabase():
    from app.config import get_settings
    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


# ---- building the bundle ---------------------------------------------

async def _book_state(client) -> dict:
    """A readable point-in-time copy of what each book holds. This is the
    part that survives a mistake in Supabase itself -- a bad migration, a
    wrong UPDATE, a dropped row. The database is our source of truth, and
    a source of truth with no copy is just a single point of failure."""
    out: dict = {"captured_at": datetime.now(timezone.utc).isoformat()}
    import asyncio
    for table, cols in (
        ("paper_accounts", "*"),
        ("paper_positions", "*"),
        ("trade_outcomes", "*"),
    ):
        try:
            def _q(t=table, c=cols):
                q = client.table(t).select(c)
                if t != "paper_accounts":
                    q = q.order("id", desc=True).limit(5000)
                return q.execute()
            out[table] = (await asyncio.to_thread(_q)).data or []
        except Exception as e:  # noqa: BLE001
            out[table] = {"error": str(e)[:200]}
    return out


async def build_bundle(full: bool = False) -> tuple[str, bytes]:
    """(filename, zip bytes). `full` includes every log file we still
    have rather than just today's and yesterday's."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"trezo-{'full' if full else 'hourly'}-{stamp}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # 1) activity logs -- the record that was least protected and
        #    most needed.
        try:
            files = sorted(LOG_DIR.glob("activity-*.jsonl"))
            if not full:
                files = files[-2:]
            for f in files:
                try:
                    z.write(f, f"logs/{f.name}")
                except OSError:
                    pass
        except Exception:  # noqa: BLE001
            pass

        # 2) runtime caches that live nowhere else
        for rel in RUNTIME_FILES:
            p = REPO / rel
            try:
                if p.exists():
                    z.write(p, rel)
            except OSError:
                pass

        # 3) book state from Supabase
        client = _supabase()
        if client is not None:
            try:
                state = await _book_state(client)
                z.writestr("state/books.json",
                           json.dumps(state, indent=2, default=str))
            except Exception as e:  # noqa: BLE001
                z.writestr("state/books.error.txt", str(e)[:500])

        # 4) a note to whoever opens this in six months
        z.writestr("README.txt", (
            "Trezo archive.\n\n"
            "logs/     the engine's activity log (the diagnostic record)\n"
            "state/    point-in-time copy of accounts, positions, outcomes\n"
            "*.json    runtime caches that exist nowhere else\n\n"
            "NOT here, on purpose: credentials (agents/.env) and code.\n"
            "Code lives in github.com/aynvmike/trezo-platform. To rebuild\n"
            "the server you do not need this archive -- you need the repo\n"
            "and the .env. This is the history, not the system.\n"))
    return name, buf.getvalue()


# ---- tier 1: Supabase Storage ----------------------------------------

async def upload_supabase(name: str, data: bytes) -> tuple[bool, str]:
    client = _supabase()
    if client is None:
        return False, "supabase not configured"
    import asyncio

    def _up():
        return client.storage.from_(BUCKET).upload(
            path=name, file=data,
            file_options={"content-type": "application/zip",
                          "upsert": "true"})
    try:
        await asyncio.to_thread(_up)
        return True, f"{BUCKET}/{name}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


# ---- tier 2: Dropbox -------------------------------------------------

async def _dropbox_token() -> Optional[str]:
    """Dropbox issues SHORT-LIVED access tokens now. A refresh token plus
    the app key/secret keeps working forever; a raw token will quietly
    expire in four hours, which is the kind of backup that looks fine
    until the day you need it."""
    refresh = os.getenv("TREZO_DROPBOX_REFRESH_TOKEN", "").strip()
    key = os.getenv("TREZO_DROPBOX_APP_KEY", "").strip()
    secret = os.getenv("TREZO_DROPBOX_APP_SECRET", "").strip()
    if refresh and key and secret:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.post(
                    "https://api.dropbox.com/oauth2/token",
                    data={"grant_type": "refresh_token",
                          "refresh_token": refresh},
                    auth=(key, secret))
                if r.status_code == 200:
                    return r.json().get("access_token")
        except Exception:  # noqa: BLE001
            return None
        return None
    return os.getenv("TREZO_DROPBOX_TOKEN", "").strip() or None


async def upload_dropbox(name: str, data: bytes) -> tuple[bool, str]:
    token = await _dropbox_token()
    if not token:
        return False, "dropbox not configured"
    try:
        import httpx
        arg = json.dumps({"path": f"/trezo-archive/{name}",
                          "mode": "overwrite", "mute": True})
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                "https://content.dropboxapi.com/2/files/upload",
                headers={"Authorization": f"Bearer {token}",
                         "Dropbox-API-Arg": arg,
                         "Content-Type": "application/octet-stream"},
                content=data)
        if 200 <= r.status_code < 300:
            return True, f"/trezo-archive/{name}"
        return False, f"HTTP {r.status_code}: {r.text[:160]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


# ---- the operation ---------------------------------------------------

async def run_archive(full: bool = False) -> dict:
    """Build once, ship to both tiers. Returns a report; never raises."""
    if not enabled():
        return {"ok": False, "skipped": "TREZO_ARCHIVE_ENABLED=0"}
    try:
        name, data = await build_bundle(full=full)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"bundle failed: {str(e)[:200]}"}

    sb_ok, sb_note = await upload_supabase(name, data)
    dbx_ok, dbx_note = (await upload_dropbox(name, data) if full
                        else (False, "weekly tier only"))

    report = {"ok": sb_ok or dbx_ok, "file": name,
              "bytes": len(data), "supabase": sb_note, "dropbox": dbx_note,
              "full": full}
    try:
        from app.agents.activity_log import record
        record("archive", name,
               reason=(f"{len(data) / 1024:.0f} KB -> supabase:"
                       f"{'ok' if sb_ok else sb_note} dropbox:"
                       f"{'ok' if dbx_ok else dbx_note}"))
    except Exception:  # noqa: BLE001
        pass

    # Only shout when BOTH tiers fail on a full run -- a silent backup
    # failure is how people discover at restore time that they have none.
    if full and not sb_ok and not dbx_ok:
        try:
            from app.runtime.alerts import notify
            await notify("Archive failed on both tiers",
                         f"supabase: {sb_note}\ndropbox: {dbx_note}",
                         severity="urgent", key="archive_failed")
        except Exception:  # noqa: BLE001
            pass
    return report
