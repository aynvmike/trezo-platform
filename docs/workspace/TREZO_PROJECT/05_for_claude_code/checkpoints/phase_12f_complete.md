# Phase 12f — Agent chat (the "then chat" help follow-up)

Date: 2026-05-23
Status: COMPLETE — and with it, the whole Phase 12 UX overhaul.

The user chose "FAQ first, then chat" for the help system. Phase 12a
shipped the FAQ; 12f adds the chat assistant.

## Built

- **/api/help/chat/route.ts** — a POST endpoint, auth-guarded. Takes the
  conversation and calls the Claude API (Haiku) with a Trezo-context
  system prompt — the seven layers, paper-trading status, TCS, the
  agents, KINDRIP, tax, Budget Mirror, the safety brakes. The prompt
  tells it to be concise and plain-spoken, point to the right page,
  never give financial advice or promise returns, and defer to the FAQ
  when unsure. Fully graceful: no API key, a bad response, or a network
  failure all return a soft message pointing to the Help & FAQ — the
  chat can never hard-fail the page.

- **components/dashboard/help-chat.tsx** — a floating assistant. A
  round chat button bottom-right opens a panel with a greeting, the
  conversation, a "Thinking…" state, and an input (Enter to send). Each
  error becomes a calm assistant message, so the turn order stays valid
  and the user can keep going. A link to the Help & FAQ sits under the
  input.

- **app/dashboard/layout.tsx** — HelpChat rendered alongside HelpNudge.
- **help-nudge.tsx** — lifted to clear the new chat button.

## Phase 12 — UX overhaul, COMPLETE

12a help system + less scrolling · 12b dark mode (Neo Obsidian) ·
12c Pattern Engine visuals · 12d backtest upgrade ·
12e Budget Mirror audit · 12f agent chat. All six parts done.

## Verification

- All new/edited files brace/paren/bracket-balanced.
- The chat needs ANTHROPIC_API_KEY in web/.env.local (already added in
  an earlier phase). Without it the widget still loads and points to
  the FAQ.
- No node_modules in the sandbox — no tsc run.

## User-side steps

- No migration. Restart the web app. The chat button appears
  bottom-right on every dashboard page.
