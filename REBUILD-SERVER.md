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

### The third category: state established ON the box

The table above answers "what survives losing the VM". It does not
answer the question that actually cost a day on 2026-08-18: **what has
to be TRUE on the server that lives neither in git nor in Supabase?**

| Established state | Set by | How it fails |
|---|---|---|
| `main` tracks `origin/main` | `git branch --set-upstream-to` | every `git pull --ff-only` silently pulls nothing |
| `node_modules` (ROOT — workspaces hoist) | `npm install` at the repo root | `next` not found; TrezoWeb dies MODULE_NOT_FOUND |
| `agents\.venv` | the setup script | the engine cannot start |
| `agents\.env` | copied by hand | nothing authenticates |
| TrezoAgents / TrezoWeb / TrezoApi services | the install-as-service scripts | tiers die on logoff instead of running at boot |
| `TrezoWebWatchdog`, health watchdog tasks | the register-\*-task scripts | nothing self-heals |
| NSSM stdout/stderr redirects + the log dirs | `nssm set AppStdout` / `mkdir` | failures leave no evidence at all |
| Migrations applied in Supabase | you, in the SQL editor | guards that exist in the repo never run |

Four of those were missing on 2026-08-18 and **not one of them
announced itself**. The deploy said `done`. The service said
`START_PENDING`. The alert never fired. The only symptom was money
moving in a book nobody was watching.

Which is the real lesson: each was verified at the wrong end — by
looking at Mike's PC, or at a status row, instead of at the box.

**So: run `verify-server.ps1` on the server.** It checks every line of
that table plus the guard suites, changes nothing, and reports what is
MISSING rather than what is fine. Run it after any rebuild, after any
deploy you are unsure about, and any time something works locally and
not in production — which is the moment this whole class of bug
announces itself, if you know to ask.

```
powershell -ExecutionPolicy Bypass -File C:\Trezo\trezo-platform\verify-server.ps1
```

A non-zero exit means something on this box is not established. The
script prints the fix next to each failure.

---

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

## The offline route: a flash drive

Mike, 2026-08-18: keep a physical path that needs no network. It earned
its place the same day — the server's `git pull` had been failing on
branch-tracking config for two days and the deploy channel was, in
practice, dead. A drive in a pocket does not care about tokens, DNS,
egress rules, or whether GitHub is up.

Copy a **bundle**, not a folder. A bundle is a single file containing
real git history that the server can fetch from exactly like a remote,
and git verifies it on the way in. A copied working directory gives you
none of that — you cannot tell what revision it is, whether it is
complete, or whether something was half-written mid-copy.

On the PC:

```
cd C:\Trezo\trezo-platform
git bundle create E:\trezo.bundle --all
git log --oneline -1        # note the revision you are carrying
```

On the server:

```
cd C:\Trezo\trezo-platform
git fetch E:\trezo.bundle main
git merge --ff-only FETCH_HEAD
git log --oneline -1        # must match what you noted
```

Then the same rule as any other deploy, because the channel changing
does not change what makes a deploy safe:

```
cd C:\Trezo\trezo-platform\agents
.\.venv\Scripts\python.exe -m tests.run_all
```

Green, then restart. Red, then do not.

**Also put `agents/.env` on the drive** — it is the one file a rebuild
cannot fetch for itself, and the table above says so. But be honest
about what that makes the drive: a removable object carrying live broker
credentials. Encrypt it (BitLocker To Go on Windows is two clicks) or
keep it somewhere you would keep a spare house key, not in a laptop bag.

### What this is and is not

It is a cold copy and an emergency channel. It is **not** the backup —
the hourly archive to Supabase Storage and the weekly one to Dropbox are
the backup, precisely because they happen whether or not anyone
remembers. A drive only holds what it held the last time someone plugged
it in, and the date on it is the date you actually get back. Refresh it
when you refresh anything else you would hate to lose.

---

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
