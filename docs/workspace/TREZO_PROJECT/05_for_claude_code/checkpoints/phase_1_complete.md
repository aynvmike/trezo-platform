# Phase 1 — Landing + Auth — COMPLETE

> Built by Nova, 2026-05-18.

## What shipped

### Landing page (`/`)
- `SiteNav` — Trezo wordmark + Sign in / Get started CTAs
- `Hero` — "Layer by Layer. Trade by Trade." tagline, woven-basket visual, dual CTA, "you own your accounts" reassurance
- `SevenLayers` — all seven layers as numbered cards with blurbs
- `SiteFooter` — Woven Basket philosophy quote, privacy / terms / contact links
- Mobile responsive (Tailwind breakpoints sm / lg)

### Authentication (Supabase)
| Route | Purpose |
|---|---|
| `/sign-up` | Email + password sign-up. Shows "check your inbox" when email confirmations are on, else routes to onboarding. |
| `/sign-in` | Password sign-in with `?redirect=` preserved. |
| `/forgot-password` | Sends Supabase reset email. |
| `/reset-password` | Sets new password using the token in the URL. |
| `/auth/callback` (GET) | Exchanges the OAuth/confirmation `?code=` for a session cookie. |
| `/auth/sign-out` (POST) | Clears the session and returns to `/`. |
| `src/middleware.ts` | On every request: refreshes the Supabase session, gates `/dashboard`, `/onboarding`, `/settings` to authed users, and bounces authed users away from `/sign-in` and `/sign-up`. |

### Profile setup wizard (`/onboarding`)
- Four-step form: Identity → Capital → Discipline → Tax
- Server action (`saveProfile`) validates with Zod, upserts to `profiles`, marks `onboarding_complete = true`
- Auto-skips users who already onboarded

### Dashboard placeholder (`/dashboard`)
- Server-rendered greeting using `display_name`
- Three KPI cards (stock capital, crypto holdings, daily target) sourced from `profiles`
- Sign-out form posting to `/auth/sign-out`
- Empty-state callout reminding the user that live data lands in Phase 2

## Exit criteria status

| Criterion | Status | Notes |
|---|---|---|
| Anonymous user sees landing page | ✅ | `/` renders without auth |
| User can sign up | ✅ | `/sign-up` — Supabase email/password |
| User can sign in / sign out | ✅ | `/sign-in` + `POST /auth/sign-out` |
| Profile data persists | ✅ | `saveProfile` → `profiles` upsert, then `/dashboard` reads it back |

## Decisions made (worth remembering)

1. **Auth runs through Supabase JS client directly** (not via our Express API). The API exists to verify Supabase JWTs for non-web clients (Phase 5+ agents UI, mobile later). One auth source of truth.
2. **Onboarding is a server action**, not a REST call. Less ceremony, atomic upsert, and the redirect-on-success works without a useEffect.
3. **Wizard is single-page progressive disclosure**, not separate routes. Lower friction; we can split later if any step grows.
4. **`/auth/callback` lives outside the (auth) route group** because it's a Route Handler, not a page — keeps middleware behavior predictable.
5. **Tax wording** stays advisory: "Trezo is not your tax advisor." Brand voice rule from `TREZO_README.md`.

## What the user needs to do before Phase 2

- Run Phase 0 setup steps if not already done (Supabase project + migrations, `.env` files, `npm install`).
- In Supabase Auth settings, decide whether to require email confirmation. Both flows are handled.
- Run `npm run dev:web` and walk through: landing → sign-up → email confirm (if on) → onboarding → dashboard → sign-out.

## Known issues / open items

- Reset-password page does not currently call `exchangeCodeForSession` because Supabase redirects from the email link land already authenticated for the recovery flow. If your Supabase project is older and uses the legacy `#access_token=` fragment, we'll need a tiny client-side parse — flag it during QA.
- Email-confirmation copy in `sign-up` assumes the user opens the email in the same browser; this is the default Supabase behavior.
- Privacy / Terms / Contact links in the footer are placeholders. Phase 11 wires them.

## Next phase starting point

→ Phase 2: Dashboard shell + CoinGecko/Finnhub integration + YieldMax tracker.
