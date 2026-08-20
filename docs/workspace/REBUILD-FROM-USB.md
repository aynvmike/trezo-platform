# REBUILD C:\Trezo FROM THIS USB

You are holding a complete mirror of the Trezo workspace: every doc,
every script, and the trezo-platform repo WITH its full git history
(the .git folder is on this stick). If this file is all you and Claude
have, the rebuild works. Steps, in order, on the new PC:

## 1. Copy the folder
Copy E:\Trezo to C:\Trezo. Plain Explorer copy is fine. Everything
below assumes C:\Trezo\trezo-platform exists afterwards.

## 2. The keys
C:\Trezo\trezo-platform\agents\.env came along on the stick. Confirm
it is there. (If this stick was ever lost or out of your control,
ROTATE the Alpaca and Supabase keys before trading again — the stick
carries them.) A second copy lives in Mike's password manager.

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

Keep the stick current: & C:\Trezo\BACKUP-USB.ps1 before you leave.
