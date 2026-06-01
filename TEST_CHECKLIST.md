# Trezo — End-to-End Test Checklist

> A shake-down pass before Phase 10 (real money). Everything below is
> still paper / modeled — no real funds are at risk. Work top to bottom.

## Step 1 — Make sure the database is current

In the Supabase SQL editor, confirm migrations **0012 through 0016** have
each been run (every phase checkpoint told you to apply one). If you are
not sure, they are safe to re-run — they use "if not exists".

- 0012 — options positions
- 0013 — adaptive scope
- 0014 — broker routing
- 0015 — account posture
- 0016 — kill-switches

**Do NOT re-run 0017 (KINDRIP)** — it is already applied, and re-running
it would erase any child you have added.

## Step 2 — Restart everything

1. Run `nuke-agent-cache.bat`. In the agents window, the startup line
   should read **`count=15`**. If it says anything lower, the agents are
   running stale code — close the window and run it again.
2. Close the Web window, run `start-web.bat`.
3. In the browser, hard-refresh (Ctrl+Shift+R).

## Step 3 — Walk every page

Open each page from the sidebar and confirm it loads with no error.

Core:
- [ ] Overview
- [ ] Paper Trading
- [ ] Performance      (new — win rate, kill-switch state)
- [ ] Pattern Engine
- [ ] Watchlists

The Woven Basket (Layers 1-7):
- [ ] Crypto Bot
- [ ] Stock Bot (STMS)
- [ ] Options Engine
- [ ] Dividend Wheel
- [ ] Dividends
- [ ] KINDRIP          (new — add a test child here)

Settings:
- [ ] Profile
- [ ] Bot Tuning       (check the Capital allocation + Autonomy sections)
- [ ] Agents           (should list 15 agents)
- [ ] Strategy Engine
- [ ] Tax Optimizer
- [ ] Ethical Filters

## Step 4 — Try the new controls

- [ ] Bot Tuning — drag a slider, change the posture, change autonomy,
      hit Save. It should say it saved.
- [ ] KINDRIP — add a child (name + birth year). Set a contribution and
      an allocation, hit Save settings. The child card should update.
- [ ] Agents page — confirm all 15 agents show, none stuck in an error.

## Step 5 — Let it run

Leave the agents running for 15-30 minutes (crypto scanning is 24/7, so
this works any time of day). Then check:

- [ ] The Overview activity feed is scrolling new agent messages.
- [ ] If any paper trades opened, they show on Paper Trading, and the
      Performance page begins to populate.
- [ ] Nothing on the Agents page is stuck red with an error.

## What "healthy" looks like

- Every page loads.
- The agent count is 15.
- The activity feed moves.
- No agent is parked in a persistent error.

If anything fails here, note which step and which page — that is exactly
what to hand back to Nova to fix before Phase 10.
