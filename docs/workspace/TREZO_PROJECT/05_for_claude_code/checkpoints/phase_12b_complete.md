# Phase 12b — Dark mode (Neo Obsidian)

Date: 2026-05-23
Status: COMPLETE

Second part of the Phase 12 UX overhaul. The site had only a bright,
warm light theme — the user found the white glare distracting and asked
for a dark setting.

## Approach — theme-aware palette, not per-component dark: variants

The app uses ~1,200 hardcoded `treasure` / `weave` colour classes and
~100 `bg-white` cards. Rather than add `dark:` variants to every one,
the palette itself is now theme-aware:

- tailwind.config.ts — the `treasure` and `weave` scales and `white`
  (the card surface) are CSS-variable-backed
  (`rgb(var(--x) / <alpha-value>)`), alpha-utilities still work.
- globals.css — every `--treasure-*`, `--weave-*` and `--surface` token
  is defined under `:root` (light) and `.dark` (dark). Light values are
  the exact original hex — light mode is pixel-identical to before.
- So every existing `bg-treasure-50`, `text-weave-800`, `bg-white`
  class flips theme automatically. No page or component was restyled.

## Neo Obsidian — the dark palette

Per the user's style direction ("Neo Obsidian of the future" — a sleek
near-black volcanic-glass look, old-world warmth forging a path
forward, a duality of sharp and smooth):

- Page: a deep cool-charcoal obsidian black.
- Cards: a lifted obsidian surface a touch above the page, with a sharp
  thin border edge.
- Ink: crisp light sage-white.
- The weave green is kept as a luminous sage accent (buttons, body).
- A warm-gold glint on the eyebrow labels — the old-world thread.

The dark scales reverse luminance: the codebase uses low indexes for
surfaces and high indexes for ink, so in dark mode low = dark,
high = light.

## Toggle + no-flash

- components/dashboard/theme-toggle.tsx — a sun/moon button in the
  dashboard header. Flips the `.dark` class on <html>, remembers the
  choice in localStorage.
- app/layout.tsx — an inline <head> script applies the saved theme (or
  the OS preference) before first paint, so there is no flash;
  <html> carries suppressHydrationWarning.

## Verification

- globals.css: brace-balanced; every theme token present in both :root
  and .dark (checked programmatically).
- All edited/created files brace/paren-balanced.
- `white` is only ever used as `bg-white` (confirmed — no text-white /
  border-white), so overriding the `white` token is safe.
- No node_modules in the build sandbox — no tsc/visual run.

## Known v1 limits

- Semantic accents (emerald / red / amber for gains, losses, warnings)
  stay as Tailwind defaults — they still read correctly, though the
  pale `-50` status banners are a little bright on obsidian. Can be
  themed in a later polish pass if wanted.
- The theme toggle lives in the dashboard header; the marketing site
  inherits the saved theme but has no toggle of its own yet.

## User-side steps

- No migration. Restart the web app, then use the sun/moon button in
  the top bar.
