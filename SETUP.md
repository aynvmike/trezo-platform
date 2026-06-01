# Trezo — Setup Walkthrough (plain English)

> One-time setup for the project. Do this once; after that you only need to start the dev servers.

## What you need first

Two things installed on your computer. If you don't have them, install them, restart your machine, and come back.

1. **Node.js (version 20 or higher)** — <https://nodejs.org/>. Pick "LTS." Run the installer with default options.
2. **Python (version 3.11 or higher)** — <https://www.python.org/downloads/>. **Important on Windows:** on the very first installer screen, check the box that says **"Add Python to PATH"** before clicking Install.

To check they installed correctly:

- Press the Windows key, type `powershell`, open it.
- Type `node --version` and press Enter. You should see something like `v20.10.0`.
- Type `python --version` and press Enter. You should see something like `Python 3.11.5`.

If either command errors, the install didn't finish. Try again.

## Option A — One-click setup (easiest)

1. Open File Explorer to `C:\Trezo\trezo-platform\`.
2. Right-click `setup.ps1` → **"Run with PowerShell"**.
3. If Windows asks about execution policy, type `Y` and press Enter.
4. Wait. It takes 2–5 minutes the first time. You'll see green "OK" lines as each step finishes.
5. When it says "Setup complete!", you're done with this part.

## Option B — Step by step (if Option A errors)

Open PowerShell, then:

```powershell
cd C:\Trezo\trezo-platform
npm install
```

That installs everything for the web app **and** the API at the same time (they share dependencies via "workspaces"). It takes a few minutes the first time.

Then set up Python:

```powershell
cd agents
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..
```

That's it.

## Database setup (one time)

Trezo uses Supabase as its database and auth provider. The schema files are already written — you just need to run them.

1. Go to <https://supabase.com/dashboard/project/cvtxbyjtytoxlpkifbcs/sql>.
2. Click **"+ New query"**.
3. Open `C:\Trezo\trezo-platform\db\migrations\0001_initial_schema.sql` in Notepad, select all (Ctrl+A), copy (Ctrl+C), and paste into the Supabase SQL editor.
4. Click **"Run"** (bottom right).
5. Click **"+ New query"** again. Repeat with `0002_rls_policies.sql`.
6. Done. Your database now has all the tables Trezo needs.

## Starting the app (every day)

Open **three** PowerShell windows. In each, navigate to the project:

```powershell
cd C:\Trezo\trezo-platform
```

Then in each window, start one of the three services:

| Window | Command | What it does |
|---|---|---|
| 1 | `npm run dev:web` | The website at http://localhost:3000 |
| 2 | `npm run dev:api` | The backend API at http://localhost:8000/health |
| 3 | `cd agents` then `.\.venv\Scripts\Activate.ps1` then `uvicorn app.main:app --reload --port 8001` | The agents service at http://localhost:8001/health |

Once all three are running, open your browser to <http://localhost:3000> and you should see the Trezo landing page.

## To try the full Phase 1 flow

1. Click **"Begin weaving"** on the landing page.
2. Enter an email and password (8+ characters).
3. If you set up Supabase to require email confirmation: check your inbox for the verification link.
4. After confirming, you'll land on the onboarding wizard — fill in the four steps.
5. You'll be sent to a placeholder dashboard.
6. Click "Sign out" in the top right — you should return to the landing page.

## To stop the servers

In each PowerShell window, press `Ctrl+C`. Close the windows when you're done.

## If something goes wrong

- **"npm: command not found"** — Node.js isn't installed or wasn't added to PATH. Reinstall it.
- **"python: command not found"** — Python isn't installed or you forgot to check "Add Python to PATH." Reinstall it.
- **Port already in use** — another program is using 3000, 8000, or 8001. Close other dev tools or restart your computer.
- **Anything else** — tell Nova exactly what the red error message says and which window it appeared in.
