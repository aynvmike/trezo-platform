# REBUILD C:\Trezo FROM THIS USB

You are holding a mirror of the Trezo workspace: every doc, every
script, and the trezo-platform repo WITH its full git history (the
.git folder is on this stick). Deliberately NOT on this stick: the
.env secret files — since 2026-08-27 the backup strips them, so a
lost stick no longer means rotating every key. If this file is all
you and Claude have, the rebuild still works. Steps, in order, on
the new PC:

## 1. One double-click
Run **RESTORE-FROM-USB.cmd** at the root of this stick. It copies
E:\Trezo → C:\Trezo, recreates every .env as an empty-valued skeleton
from the .template files on the stick, and prints exactly which keys
you must fill in. (Manual alternative: Explorer-copy E:\Trezo to
C:\Trezo, then run C:\Trezo\RESTORE-FROM-USB.ps1 yourself.)

## 2. The keys
The stick carries NO keys, by design. Every value lives in Mike's
password manager — fill in the skeletons the restore just listed
(trezo-platform\agents\.env, trezo-platform\api\.env,
trezo-platform\web\.env.local). Only rotate keys if the password
manager itself is in doubt, not because the stick traveled.

## 3. Reinstall the machine-specific parts (skipped by the mirror)
In PowerShell:

    cd C:\Trezo\trezo-platform\agents
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt

    cd C:\Trezo\trezo-platform\web
    npm install

## 4. Reconnect to GitHub (for future pushes)
The repo's remote is already configured:
https://github.com/aynvmike/trezo-platform (private).
Run `git fetch origin` once — Windows will prompt a GitHub sign-in the
first time. Then `git pull --ff-only origin main` in case the stick was
older than the remote.

## 5. Re-arm the automation
    & C:\Trezo\AUTO-PUSH.ps1 -Register      # pushes commits every 10 min

## 6. Reconnect Claude
Install the Claude desktop app, connect the C:\Trezo folder, and the
Chrome extension if you use it. Tell Nova: "read the Trezo project
memory" — the deploy path, server details, and all context are stored
there and on GitHub in docs/workspace/.

## What this stick can NOT rebuild
The production SERVER (Lightsail, 98.81.100.112) is not on this stick —
it doesn't need to be; it rebuilds from GitHub (see docs/workspace/
SERVER-SETUP.txt). The Supabase database lives in Supabase's cloud.

Keep the stick current: double-click C:\Trezo\RUN-USB-BACKUP.cmd
(or run & C:\Trezo\BACKUP-USB.ps1) before you leave.
