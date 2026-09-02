import { redirect } from "next/navigation";
import { LayerHero } from "@/components/dashboard/layer-hero";
import { PremiumQualityCard } from "@/components/dashboard/premium-quality-card";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

import { Disclosure } from "@/components/ui/disclosure";
import { WheelLiveQuotes } from "@/components/dashboard/wheel-live-quotes";
import { WheelLivePositions } from "@/components/dashboard/wheel-live-positions";
import { WheelReconcileButton } from "@/components/dashboard/wheel-reconcile-button";
import { WheelUniversePanel } from "@/components/dashboard/wheel-universe-panel";
import { OpenOptionsTable } from "@/components/dashboard/open-options-table";
import { WheelAcquisitionQueue } from "@/components/dashboard/wheel-acquisition-queue";
import { OptionsApprovalBadge } from "@/components/dashboard/options-approval-badge";
import { LoadError, loadResult } from "@/components/dashboard/load-error";
import { getOwnerBookKeys, bookQueryKeys, withBooks } from "@/lib/books";
import { fetchAlpacaSnapshot } from "@/lib/alpaca-snapshot";
import {
  fetchWheelLiveSnapshot,
  summariseLiveWheel
} from "@/lib/wheel-snapshot";

export const dynamic = "force-dynamic";

function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {
    style: "currency",
    currency: "USD"
  });
}

function pct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

// Loose US-equities market-hours check. ET wall-clock 9:30 AM-4:00 PM
// weekdays. Skipped-holiday refinement is a future Phase 13 item;
// for now this is good enough to tell "the wheel is idle because the
// market is closed" vs "the wheel is idle for another reason."
function isUSMarketOpen(now: Date): boolean {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour12: false,
    weekday: "short",
    hour: "numeric",
    minute: "numeric"
  });
  const parts = fmt.formatToParts(now);
  const wkMap: Record<string, number> = {
    Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6
  };
  const wk = wkMap[parts.find((p) => p.type === "weekday")?.value ?? "Sun"] ?? 0;
  if (wk === 0 || wk === 6) return false;
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  const minutes = h * 60 + m;
  return minutes >= 9 * 60 + 30 && minutes < 16 * 60;
}

// The wheel watchlist - diverse dividend payers across REITs, BDCs,
// telcos, energy, pharma, consumer staples, banks, and tech. Chosen
// for: (1) liquid options markets so CSPs/CCs actually fill,
// (2) varied price tiers for cash efficiency, (3) names you'd be ok
// owning if assigned. Mike 2026-06-01: blue-chip-only was too narrow
// and too cash-expensive per CSP. See agents/app/strategies/wheel.py
// for the matching server-side list and tier rationale.
const WHEEL_WATCHLIST = [
  // Tier A - REITs / BDCs
  "O", "MAIN", "STAG", "NLY", "ARCC",
  // Tier B - cheap CSPs, high yield
  "F", "T", "KMI", "VZ", "MO", "INTC",
  // Tier C - mid-cap dividends
  "PFE", "KHC", "CSCO", "BMY", "KEY", "HPQ",
];

// Modeled trailing annual dividend yields used to estimate income while
// shares are held. Rounded; real dividend tracking from a live feed is
// a later phase. Numbers approximate to typical recent yields.
const DIVIDEND_YIELDS: Record<string, number> = {
  // Tier A - REITs / BDCs (high yield)
  O:    0.055, MAIN: 0.060, STAG: 0.045, NLY:  0.130, ARCC: 0.090,
  // Tier B - cheap CSPs, high yield
  F:    0.060, T:    0.065, KMI:  0.060, VZ:   0.065, MO:   0.080, INTC: 0.015,
  // Tier C - mid-cap dividends
  PFE:  0.060, KHC:  0.050, CSCO: 0.030, BMY:  0.045, KEY:  0.050, HPQ:  0.030,
};

// A typical Fully Paid Securities Lending rebate on liquid large-caps —
// small, but real income if your broker offers FPSL on the shares you
// hold between calls. Modeled here for completeness.
const FPSL_YIELD = 0.001;

const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  closed_expired: "Expired — credit kept",
  closed_assigned: "Assigned",
  closed_manual: "Closed",
  closed_profit: "Closed — profit lock"
};

const STATUS_COLOR: Record<string, string> = {
  open: "bg-weave-100 text-weave-800",
  closed_expired: "bg-emerald-100 text-emerald-800",
  closed_assigned: "bg-amber-100 text-amber-800",
  closed_manual: "bg-weave-50 text-weave-500",
  closed_profit: "bg-emerald-100 text-emerald-800"
};

type WheelRow = {
  id: string;
  underlying: string;
  strategy: string;
  strike: number | null;
  expiration: string | null;
  contracts: number;
  net_premium_usd: number;
  status: string;
  realized_pnl_usd: number | null;
  opened_at?: string | null;
  closed_at?: string | null;
};

type CycleState =
  | "idle"
  | "csp_open"
  | "assigned"
  | "cc_open"
  | "called_away";

type Cycle = {
  underlying: string;
  state: CycleState;
  activeStop: 1 | 2 | 3 | 4;
  description: string;
  next: string;
  open_csp?: WheelRow;
  open_cc?: WheelRow;
  last?: WheelRow;
  dividend_yield: number;
  fpsl_yield: number;
};

const CYCLE_STOPS = [
  { id: "put", label: "Sell put", short: "Sell put" },
  { id: "wait", label: "Wait for expiry or assignment", short: "Wait" },
  { id: "hold", label: "Hold shares · sell call", short: "Hold & call" },
  { id: "reset", label: "Called away · cycle resets", short: "Reset" }
];

type IdleReason = {
  marketOpen: boolean;
  optionsScannerEnabled: boolean;
  lastTickMinutesAgo: number | null;
  optionsApprovalLevel: number | null;
};

function describeIdle(reason: IdleReason): {
  description: string;
  next: string;
} {
  // Mike feedback 2026-05-29: when a wheel card is idle, the user
  // wants to know WHY — is the market closed? is the agent disabled?
  // is the broker not approved? Cycle through the most blocking
  // reason first, then surface "awaiting next tick" as the fallback.
  if (reason.optionsApprovalLevel !== null && reason.optionsApprovalLevel < 1) {
    return {
      description:
        "Waiting on broker — your Alpaca account is not approved for options yet.",
      next: "Next: apply for Level 1+ on Alpaca (Account → Configure → Options). The Wheel needs at least covered (Level 1)."
    };
  }
  if (!reason.optionsScannerEnabled) {
    return {
      description:
        "Wheel scanner is paused — turn it back on in Bot Tuning to resume.",
      next: "Next: enable the Options Scanner under Bot Tuning → Strategies."
    };
  }
  if (!reason.marketOpen) {
    return {
      description:
        "Market is closed — the Wheel will resume placing puts at the next regular session open.",
      next: "Next: the bot scans every 30 minutes and places its first put after the 9:30 AM ET open."
    };
  }
  if (reason.lastTickMinutesAgo === null) {
    return {
      description:
        "Waiting on the first Options Scanner tick — running for the first time today.",
      next: "Next: the scanner ticks every 30 minutes. Hit Run scanner now on /paper to force one."
    };
  }
  if (reason.lastTickMinutesAgo > 35) {
    return {
      description: `The Options Scanner has not ticked in ${reason.lastTickMinutesAgo} minutes — it may be stuck.`,
      next: "Next: check the Agents page; the scanner should run every 30 minutes."
    };
  }
  return {
    description:
      "Idle — the scanner just ran but no qualifying setup. The bot is being selective.",
    next: "Next: the bot will sell a put ~5% below spot when conditions line up."
  };
}

function computeCycle(
  underlying: string,
  positions: WheelRow[],
  idleReason: IdleReason
): Cycle {
  const sorted = positions
    .slice()
    .sort(
      (a, b) =>
        new Date(b.opened_at ?? 0).getTime() -
        new Date(a.opened_at ?? 0).getTime()
    );
  const open_csp = sorted.find(
    (p) => p.strategy === "wheel_csp" && p.status === "open"
  );
  const open_cc = sorted.find(
    (p) => p.strategy === "wheel_cc" && p.status === "open"
  );
  const last = sorted[0];
  const lastCsp = sorted.find((p) => p.strategy === "wheel_csp");
  const lastCc = sorted.find((p) => p.strategy === "wheel_cc");

  let state: CycleState = "idle";
  let activeStop: 1 | 2 | 3 | 4 = 1;
  const idleCopy = describeIdle(idleReason);
  let description = idleCopy.description;
  let next = idleCopy.next;

  if (open_cc) {
    state = "cc_open";
    activeStop = 3;
    description =
      "Holding shares and selling a covered call against them. Premium collected; if called away on expiry, the cycle resets.";
    next = `Next: wait for expiry on ${open_cc.expiration ?? "—"}.`;
  } else if (open_csp) {
    state = "csp_open";
    activeStop = 2;
    description =
      "Sold a cash-secured put. If it expires out-of-the-money the credit is kept; if it assigns, you own 100 shares.";
    next = `Next: wait for expiry on ${open_csp.expiration ?? "—"}.`;
  } else if (lastCsp?.status === "closed_assigned" && (!lastCc || lastCc.status !== "open")) {
    state = "assigned";
    activeStop = 3;
    description =
      "Shares were assigned to you. The bot will write a covered call against them on the next tick.";
    next = "Next: a covered call ~5% above spot will be opened.";
  } else if (lastCc?.status === "closed_assigned") {
    state = "called_away";
    activeStop = 4;
    description =
      "Shares were called away on the covered call — the cycle is complete. A new put will start it again.";
    next = "Next: the wheel turns — a fresh cash-secured put begins the cycle.";
  } else if (last && (last.status === "closed_expired" || last.status === "closed_profit")) {
    if (last.strategy === "wheel_csp") {
      state = "idle";
      activeStop = 1;
      description = "Last put expired worthless and the premium was kept.";
      next = "Next: a fresh cash-secured put will be opened on the next tick.";
    } else {
      state = "assigned";
      activeStop = 3;
      description = "Last covered call expired worthless; the shares are still yours.";
      next = "Next: another covered call against the shares you still hold.";
    }
  }

  return {
    underlying,
    state,
    activeStop,
    description,
    next,
    open_csp,
    open_cc,
    last,
    dividend_yield: DIVIDEND_YIELDS[underlying] ?? 0.02,
    fpsl_yield: FPSL_YIELD
  };
}

export default async function WheelPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/wheel");

  // rv:web-pages sweep: options_positions is keyed by BOOK (0047); read
  // every book the person owns. (bot_settings below stays keyed by the
  // caller's own key: it is one book's dial, chosen on the settings page.)
  const booksLoad = await getOwnerBookKeys(supabase, user.id);
  const keys = bookQueryKeys(booksLoad.data);

  const [rowsRes, botRes, lastTickRes, alpacaSnap, wheelLive] = await Promise.all([
    supabase
      .from("options_positions")
      .select(
        "id, underlying, strategy, strike, expiration, contracts, net_premium_usd, status, realized_pnl_usd, opened_at, closed_at"
      )
      .in("user_id", keys)
      .in("strategy", ["wheel_csp", "wheel_cc"])
      .order("opened_at", { ascending: false }),
    supabase
      .from("bot_settings")
      .select("pattern_enabled")
      .eq("user_id", user.id)
      .maybeSingle(),
    supabase
      .from("agent_messages")
      .select("created_at")
      .eq("agent_name", "options_scanner")
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    fetchAlpacaSnapshot(),
    fetchWheelLiveSnapshot(user.id)
  ]);
  // Live broker totals — when present, these override the modeled
  // numbers from `options_positions` on the headline tiles. Falls
  // through to modeled when Alpaca isn't connected or has no option
  // legs in the account yet.
  const liveSummary = summariseLiveWheel(wheelLive);

  // PAGES-03: keep "read failed" distinct from "nothing there". A failed
  // options_positions read blanks the modeled tiles/sections below; the
  // live (Alpaca-backed) panels have their own snapshot and still render.
  const rowsLoad = withBooks(booksLoad, loadResult<WheelRow[]>("options_positions", rowsRes, []));
  const positions = rowsLoad.data ?? [];

  // Idle reason — Mike feedback 2026-05-29. The cards used to all say
  // "Idle — ready to start the cycle" with no hint why. Now they
  // surface the actual blocker (market closed / scanner disabled /
  // broker not approved / awaiting tick).
  const marketOpen = isUSMarketOpen(new Date());
  const lastTickIso = (lastTickRes.data as { created_at?: string } | null)
    ?.created_at;
  const lastTickMinutesAgo = lastTickIso
    ? Math.round((Date.now() - new Date(lastTickIso).getTime()) / 60_000)
    : null;
  const optionsApprovalLevel = alpacaSnap?.configured && alpacaSnap.account
    ? Number(alpacaSnap.account.options_approved_level ?? 0)
    : null;
  const idleReason = {
    marketOpen,
    optionsScannerEnabled: Boolean(botRes.data?.pattern_enabled ?? true),
    lastTickMinutesAgo,
    optionsApprovalLevel
  };

  const byUnderlying: Record<string, WheelRow[]> = {};
  for (const p of positions) {
    (byUnderlying[p.underlying] ??= []).push(p);
  }
  const cycles = WHEEL_WATCHLIST.map((u) =>
    computeCycle(u, byUnderlying[u] ?? [], idleReason)
  );

  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status !== "open");

  const creditOpen = open.reduce(
    (s, p) => s + Number(p.net_premium_usd ?? 0),
    0
  );
  const realized = closed.reduce(
    (s, p) => s + Number(p.realized_pnl_usd ?? 0),
    0
  );
  const cashSecured = open
    .filter((p) => p.strategy === "wheel_csp")
    .reduce(
      (s, p) => s + Number(p.strike ?? 0) * 100 * Number(p.contracts ?? 1),
      0
    );

  // Modeled annual income while holding shares — dividends + FPSL on the
  // names currently in the held / assigned / covered-call state.
  let modeledAnnualHeldIncome = 0;
  for (const c of cycles) {
    if (c.state === "assigned" || c.state === "cc_open") {
      const ref = c.open_cc?.strike ?? c.last?.strike ?? 0;
      const notional = Number(ref) * 100;
      modeledAnnualHeldIncome += notional * (c.dividend_yield + c.fpsl_yield);
    }
  }

  // PAGES-05: the hero used to get no count and defaulted to "active".
  // Live broker legs win when present; otherwise the modeled book; and
  // undefined (-> idle, "—") when the modeled read failed.
  const heroOpenCount = liveSummary
    ? liveSummary.open_csps + liveSummary.open_ccs
    : rowsLoad.failure
      ? undefined
      : open.length;

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <LayerHero id={5} openCount={heroOpenCount} />

      {rowsLoad.failure ? <LoadError {...rowsLoad.failure} /> : null}

      {/* Headline tiles — when Alpaca is connected and reports open
          option legs, these read from the broker (LIVE). Otherwise
          they fall back to the modeled `options_positions` table. The
          live badge tells the user which side of the line they're on. */}
      {rowsLoad.failure && !liveSummary ? null : (
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="Open contracts"
          value={String(
            liveSummary
              ? liveSummary.open_csps + liveSummary.open_ccs
              : open.length
          )}
          live={Boolean(liveSummary)}
        />
        <StatCard
          label="Premium at work"
          value={usd(liveSummary?.premium_at_work_usd ?? creditOpen)}
          tone={
            (liveSummary?.premium_at_work_usd ?? creditOpen) > 0
              ? "good"
              : undefined
          }
          live={Boolean(liveSummary)}
        />
        <StatCard
          label="Cash secured"
          value={usd(liveSummary?.cash_secured_usd ?? cashSecured)}
          live={Boolean(liveSummary)}
        />
        <StatCard
          label="Realized P&L"
          value={rowsLoad.failure ? "—" : usd(realized)}
          tone={rowsLoad.failure ? undefined : realized >= 0 ? "good" : "bad"}
        />
      </section>
      )}
      <p className="-mt-4 text-[11px] text-weave-500">
        Tiles reflect <span className="font-medium">currently open</span> legs
        only. Reconciled / settled legs roll into Realized P&L.
      </p>

      <OptionsApprovalBadge />

      <WheelReconcileButton />

      <WheelUniversePanel userId={user.id} />

      <WheelLivePositions userId={user.id} />

      {/* Task #28: complete options book with bucket badges (wheel /
          income / hopeful) and DTE color-coding. Bucket-aware view -
          shows hopeful holds and other non-Wheel options alongside the
          Wheel. */}
      <OpenOptionsTable />

      <WheelLiveQuotes underlyings={WHEEL_WATCHLIST} />

      {/* Task #35: Acquisition Queue replaces the example-grid as the
          primary signal of what the bot is actually queueing. The full
          17-name example planner moves into a collapsed disclosure
          below for those who still want the reference. */}
      <WheelAcquisitionQueue />

      <Disclosure title="Show full example planner (all watchlist names)">
        <section className="space-y-3">
          <div className="flex items-baseline justify-between gap-3 flex-wrap">
            <div>
              <p className="text-sm text-weave-500 leading-relaxed">
                This is the bot&apos;s <span className="font-medium">modeled
                plan</span> for every watchlist name, not your real broker
                positions. Use this as a reference for how the wheel cycle
                LOOKS — for active picks, see the Acquisition Queue above.
              </p>
            </div>
            <span className="text-[10px] uppercase tracking-widest rounded-full bg-weave-100 text-weave-600 px-2 py-0.5 shrink-0">
              Modeled · not broker
            </span>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {cycles.map((c) => (
              <CycleCard key={c.underlying} cycle={c} />
            ))}
          </div>
        </section>
      </Disclosure>

      {/* Income breakdown — premium + dividends + FPSL */}
      <section className="space-y-3">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Where the income comes from
          </h2>
          <p className="beginner-only mt-1 text-sm text-weave-500">
            The wheel is not just option premium. Every name that gets
            assigned starts paying dividends, and shares you hold can earn
            small lending income (FPSL). The total is what makes the wheel
            quietly compound.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <IncomeCard
            label="Premium at work"
            sub={
              liveSummary
                ? "Open option credit (live Alpaca)"
                : "Open option credit (modeled)"
            }
            value={usd(liveSummary?.premium_at_work_usd ?? creditOpen)}
            tone="good"
          />
          {/* REVIEW PAGES-03 (2026-09-01): these two are derived only from
              the options_positions read, so on a failed read they printed
              a confident "$0.00". Blank them like the headline tile above. */}
          <IncomeCard
            label="Realized P&L"
            sub="Closed legs"
            value={rowsLoad.failure ? "—" : usd(realized)}
            tone={rowsLoad.failure ? "neutral" : realized >= 0 ? "good" : "bad"}
          />
          <IncomeCard
            label="Modeled hold income"
            sub="Dividend + FPSL (annualised on shares currently held)"
            value={rowsLoad.failure ? "—" : usd(modeledAnnualHeldIncome)}
            tone={modeledAnnualHeldIncome > 0 ? "good" : "neutral"}
          />
        </div>
      </section>

      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Open wheel positions{" "}
          <span className="text-sm text-weave-500">({open.length})</span>
        </h2>
        {rowsLoad.failure ? (
          <LoadError {...rowsLoad.failure} />
        ) : open.length === 0 ? (
          <EmptyCard>
            No open wheel positions yet. The Options Scanner opens a modeled
            cash-secured put on each quality name every 30 minutes once your
            paper account is live.
          </EmptyCard>
        ) : (
          <WheelTable rows={open} showRealized={false} />
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Settled positions{" "}
          <span className="text-sm text-weave-500">({closed.length})</span>
        </h2>
        {rowsLoad.failure ? (
          <LoadError {...rowsLoad.failure} />
        ) : closed.length === 0 ? (
          <EmptyCard>
            Nothing has settled yet. A wheel leg settles on its expiration date.
          </EmptyCard>
        ) : (
          <WheelTable rows={closed} showRealized={true} />
        )}
      </section>

      <div className="beginner-only">
        <Disclosure title="How the wheel turns — a walk-through">
          <div className="space-y-3">
            <p>
              <span className="font-medium text-weave-800">Stop 1 — Sell a put.</span>{" "}
              The bot picks a quality dividend name and sells a cash-secured
              put ~5% below the current price. You collect premium today.
              &ldquo;Cash-secured&rdquo; means you hold enough cash to buy
              100 shares per contract if it assigns.
            </p>
            <p>
              <span className="font-medium text-weave-800">Stop 2 — Wait.</span>{" "}
              Two ways the put can end. If the stock stays above the strike at
              expiry, the put expires worthless and you keep the full premium —
              the cycle resets to Stop 1. If the stock dips below the strike,
              the put assigns and you buy 100 shares at the strike. Either
              way, the premium is yours.
            </p>
            <p>
              <span className="font-medium text-weave-800">
                Stop 3 — Hold shares and sell a call.
              </span>{" "}
              Now you own the shares. The bot writes a covered call ~5% above
              the current price — more premium today. Meanwhile, the shares
              themselves are paying you:
            </p>
            <ul className="ml-4 list-disc space-y-1">
              <li>
                <span className="font-medium text-weave-800">Dividends</span> —
                quarterly cash from the company. WMT, KO, JNJ, PG, CSCO, VZ,
                INTC are all dividend payers; that&apos;s why they are on the wheel
                watchlist.
              </li>
              <li>
                <span className="font-medium text-weave-800">
                  FPSL (Fully Paid Securities Lending)
                </span>{" "}
                — your broker can lend the shares you own to short-sellers and
                pay you a small interest rebate. It is small but real income
                while you are holding.
              </li>
            </ul>
            <p>
              <span className="font-medium text-weave-800">
                Stop 4 — Called away.
              </span>{" "}
              If the stock rises through your call strike, the shares get
              called away at the strike. You keep the call premium and walk
              away with a clean profit. The wheel resets to Stop 1.
            </p>
            <p className="text-weave-500">
              On a quality name, you can ride this cycle for years —
              collecting premium every revolution, plus dividends and
              securities-lending income whenever you are holding. That is the
              quiet compounding the wheel is known for.
            </p>
          </div>
        </Disclosure>
      </div>

      <Disclosure title="The watchlist, strikes & modeled pricing">
        <div className="space-y-2">
          <p>
            <span className="font-medium text-weave-800">The watchlist:</span>{" "}
            {WHEEL_WATCHLIST.join(" · ")} — liquid, lower-beta dividend payers
            chosen because they are names worth owning if a put assigns.
          </p>
          <p>
            <span className="font-medium text-weave-800">How strikes are set:</span>{" "}
            puts are sold about 5% below spot and calls about 5% above, on a
            roughly monthly (30-day) cycle.
          </p>
          <p>
            <span className="font-medium text-weave-800">Modeled income:</span>{" "}
            premiums use a Black-Scholes pricer (no live options chain yet).
            Dividend and FPSL income are estimated from typical yields — real
            dividend tracking from a live feed is a later phase. The intent is
            to make the full picture visible: option income is one slice, not
            the whole pie.
          </p>
        </div>
      </Disclosure>

      {/* Natenberg, 2026-08-05: selling premium is selling volatility, and
          nothing in Trezo measured whether the volatility was worth selling.
          Observation only -- these verdicts gate no decision yet. */}
      <PremiumQualityCard />
    </div>
  );
}

function CycleCard({ cycle }: { cycle: Cycle }) {
  const last = cycle.last;
  const strikeForCalc =
    cycle.open_cc?.strike ?? cycle.open_csp?.strike ?? last?.strike ?? 0;
  const notional = Number(strikeForCalc) * 100;
  const annualDiv = notional * cycle.dividend_yield;
  const annualFpsl = notional * cycle.fpsl_yield;
  const annualPremium = Number(last?.net_premium_usd ?? 0) * 12; // ~monthly cycle
  const showHoldIncome =
    cycle.state === "assigned" || cycle.state === "cc_open";

  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <p className="font-mono font-medium text-weave-800 text-lg">
            {cycle.underlying}
          </p>
          <p className="text-[11px] uppercase tracking-widest text-weave-500">
            Stop {cycle.activeStop} of 4 ·{" "}
            {CYCLE_STOPS[cycle.activeStop - 1].short}
          </p>
        </div>
        <span className="text-[10px] uppercase tracking-widest rounded-full bg-treasure-100 text-treasure-700 px-2 py-0.5">
          Yield {pct(cycle.dividend_yield)} div
        </span>
      </div>
      <CycleStrip active={cycle.activeStop} />
      <p className="text-sm text-weave-700 leading-relaxed">{cycle.description}</p>
      <p className="text-xs text-weave-500">{cycle.next}</p>

      <div className="rounded-lg border border-weave-100 bg-treasure-100/30 p-3 text-xs text-weave-600 space-y-1">
        {strikeForCalc > 0 ? (
          <>
            <p>
              Modeled premium per cycle:{" "}
              <span className="font-mono text-weave-800">
                {usd(Number(last?.net_premium_usd ?? 0))}
              </span>
              {annualPremium > 0 && (
                <span className="text-weave-400">
                  {" "}
                  · ~{usd(annualPremium)} annualised
                </span>
              )}
            </p>
            {showHoldIncome && (
              <>
                <p>
                  Dividend on 100 shares:{" "}
                  <span className="font-mono text-weave-800">
                    {usd(annualDiv)}
                  </span>{" "}
                  / year ({pct(cycle.dividend_yield)})
                </p>
                <p>
                  FPSL on 100 shares:{" "}
                  <span className="font-mono text-weave-800">
                    {usd(annualFpsl)}
                  </span>{" "}
                  / year ({pct(cycle.fpsl_yield)})
                </p>
              </>
            )}
          </>
        ) : (
          <p className="text-weave-400">
            No leg has opened yet on {cycle.underlying} — income figures
            appear once the wheel begins turning.
          </p>
        )}
      </div>
    </div>
  );
}

function CycleStrip({ active }: { active: 1 | 2 | 3 | 4 }) {
  return (
    <div className="flex items-center gap-2">
      {CYCLE_STOPS.map((stop, i) => {
        const idx = (i + 1) as 1 | 2 | 3 | 4;
        const isActive = idx === active;
        const isPast = idx < active;
        return (
          <div key={stop.id} className="flex-1 flex items-center gap-2">
            <div
              className={cn(
                "h-7 w-7 shrink-0 grid place-items-center rounded-full text-[10px] font-medium",
                isActive
                  ? "bg-weave-600 text-treasure-50"
                  : isPast
                    ? "bg-weave-200 text-weave-600"
                    : "bg-weave-50 text-weave-400"
              )}
              title={stop.label}
            >
              {idx}
            </div>
            <span
              className={cn(
                "text-[10px] uppercase tracking-widest truncate",
                isActive
                  ? "text-weave-800 font-medium"
                  : isPast
                    ? "text-weave-500"
                    : "text-weave-400"
              )}
            >
              {stop.short}
            </span>
            {i < CYCLE_STOPS.length - 1 && (
              <span
                className={cn(
                  "h-px flex-1 bg-weave-100",
                  isPast && "bg-weave-300"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function IncomeCard({
  label,
  sub,
  value,
  tone
}: {
  label: string;
  sub: string;
  value: string;
  tone?: "good" | "bad" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-1">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">
        {label}
      </p>
      <p
        className={cn(
          "font-mono text-lg font-medium",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-600",
          (tone === "neutral" || !tone) && "text-weave-800"
        )}
      >
        {value}
      </p>
      <p className="text-[11px] text-weave-500 leading-relaxed">{sub}</p>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
  live
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
  live?: boolean;
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[11px] uppercase tracking-widest text-weave-500">
          {label}
        </p>
        {live ? (
          <span
            className="text-[9px] uppercase tracking-widest rounded-full bg-emerald-100 text-emerald-800 px-1.5 py-0.5"
            title="Sourced from the live Alpaca account, not the modeled options_positions table."
          >
            Live
          </span>
        ) : null}
      </div>
      <p
        className={cn(
          "mt-1 font-mono text-lg font-medium",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-600",
          !tone && "text-weave-800"
        )}
      >
        {value}
      </p>
    </div>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
      {children}
    </div>
  );
}

function WheelTable({
  rows,
  showRealized
}: {
  rows: WheelRow[];
  showRealized: boolean;
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
            <th className="px-4 py-3">Name</th>
            <th className="px-4 py-3">Leg</th>
            <th className="px-4 py-3 text-right">Strike</th>
            <th className="px-4 py-3 text-right">Contracts</th>
            <th className="px-4 py-3 text-right">Premium</th>
            <th className="px-4 py-3">Expiration</th>
            <th className="px-4 py-3">Status</th>
            {showRealized && <th className="px-4 py-3 text-right">Realized</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const leg =
              p.strategy === "wheel_csp"
                ? "Cash-secured put"
                : p.strategy === "wheel_cc"
                  ? "Covered call"
                  : p.strategy;
            const realized = Number(p.realized_pnl_usd ?? 0);
            return (
              <tr key={p.id} className="border-b border-weave-50 last:border-0">
                <td className="px-4 py-3 font-mono font-medium text-weave-800">
                  {p.underlying}
                </td>
                <td className="px-4 py-3 text-weave-600">{leg}</td>
                <td className="px-4 py-3 text-right font-mono">{usd(p.strike)}</td>
                <td className="px-4 py-3 text-right font-mono">{p.contracts}</td>
                <td className="px-4 py-3 text-right font-mono text-emerald-700">
                  {usd(p.net_premium_usd)}
                </td>
                <td className="px-4 py-3 text-xs text-weave-500">
                  {p.expiration ?? "—"}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={cn(
                      "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                      STATUS_COLOR[p.status] ?? "bg-weave-50 text-weave-500"
                    )}
                  >
                    {STATUS_LABEL[p.status] ?? p.status}
                  </span>
                </td>
                {showRealized && (
                  <td
                    className={cn(
                      "px-4 py-3 text-right font-mono",
                      realized > 0 && "text-emerald-700",
                      realized < 0 && "text-red-600"
                    )}
                  >
                    {usd(realized)}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
