# Rebuilding the engine from nothing

**The point of this document is that you never need a backup of the
server.** If the instance is deleted, corrupted, or you simply want a
cheaper one somewhere else, you do not restore it — you build a new one
and point it at the things that were never on it in the first place.

Written 2026-08-18, after the engine sat dead for fifteen hours and the
question "what happens if I lose this box" turned out to have a better
answer than anyone had written down.

---

## Where everything actually lives

| Thing | Lives in | Survives losing the VM |
|---|---|---|
| Ledger: positions, accounts, outcomes, kill-switch state | Supabase | yes |
| Code | GitHub `aynvmike/trezo-platform` + Mike's PC | yes |
| Broker positions and cash | Alpaca | yes |
| Agent memories | mem0 | yes |
| Activity logs, runtime caches | the VM → archived hourly to Supabase Storage, weekly to Dropbox | yes, since 8/18 |
| **Credentials (`agents/.env`)** | **the VM and Mike's PC only** | **only if the PC copy exists** |

That last row is the one thing a rebuild genuinely needs and cannot
fetch for itself. It is deliberately not in git. Keep a copy somewhere
you trust — a password manager entry is ideal.

Everything else is either in a service or reproducible from the repo.

---

## Rebuild, start to finish

**1. New instance.** Lightsail → Windows Server 2022. Any size; 2 GB is
enough to run the engine, 4 GB is comfortable. Paste
`vm-migration/PASTE-1-when-creating-the-server.txt` into the launch
script box — it installs Python, Node, git, NSSM and the firewall.

**2. Get the code.** On the new box, in PowerShell as Administrator:

```
mkdir C:\Trezo; cd C:\Trezo
git clone https://x-access-token:<READ_ONLY_TOKEN>@github.com/aynvmike/trezo-platform.git
```

No copying from anywhere. No SSH from a laptop. No 4 GB tarball.

**3. Put the credentials back.** Create `C:\Trezo\trezo-platform\agents\.env`
from your saved copy. `.env.example` in the repo lists every key with a
comment explaining what it does, so a missing one is obvious.

**4. Build and install the services.** Paste
`vm-migration-windows/PASTE-3-on-the-server.ps1`. It creates the venv,
installs dependencies, builds web and api, and registers TrezoAgents,
TrezoApi and TrezoWeb under NSSM with auto-start.

**5. Start the engine — after confirming nothing else is running.**

> **The one hard rule: never two engines on one Alpaca account.** Two
> processes managing the same positions will fight, double-sell, and
> trip the kill-switches. Before starting, make sure the old box is
> stopped and your PC's engine is stopped.

```
C:\ProgramData\chocolatey\bin\nssm.exe start TrezoAgents
```

**6. Confirm it is alive**, from any browser:

```sql
select max(ts), now() - max(ts) as age from ops_log_tail;
```

Minutes, not hours. You should also get an "Engine started" message in
your Discord channel within five minutes.

**7. Adopt the positions.** The first reconcile writes ledger rows for
anything Alpaca holds that the books do not know about, so a new engine
picks up the existing positions rather than ignoring them. Watch for
`position_adopted` in the log.

Twenty minutes, most of it waiting on npm.

---

## What this buys

You can treat the instance as disposable. Downgrade it, move it to
another provider, delete it in a panic at 3am — none of those are
decisions that risk data, because the data was never there. The only
irreplaceable thing is `agents/.env`, and that is one file you can keep
in a password manager.

## The one thing to check monthly

That the archive is actually running. A backup nobody verifies is a
belief, not a backup:

```sql
select name, created_at, round((metadata->>'size')::numeric / 1024) as kb
from   storage.objects
where  bucket_id = 'trezo-archive'
order  by created_at desc limit 5;
```

If the newest is older than a couple of hours, the archivist has stopped
and you would be relying on a copy that no longer exists.
