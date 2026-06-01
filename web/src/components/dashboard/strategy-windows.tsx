import { cn } from "@/lib/utils";

type WindowSpec = {
  name: string;
  short: string;
  startHourEt: number;
  endHourEt: number;
  weekdayOnly: boolean;
  note: string;
};

// All strategy windows in one place. ET wall-clock hours; the activity
// check uses Eastern Time so DST is honoured.
const WINDOWS: WindowSpec[] = [
  {
    name: "Market Horizons",
    short: "24/7",
    startHourEt: 0,
    endHourEt: 24,
    weekdayOnly: false,
    note: "Cross-asset read (stocks/crypto/gold/dollar/bonds) — runs every 15 min, always on."
  },
  {
    name: "Pattern Detection",
    short: "24/7",
    startHourEt: 0,
    endHourEt: 24,
    weekdayOnly: false,
    note: "Scans watchlist + market-wide pool every 60s. Pre-market candles feed it whenever the data feed has them."
  },
  {
    name: "STMS (small-cap momentum)",
    short: "7:00 – 11:00 AM ET",
    startHourEt: 7,
    endHourEt: 11,
    weekdayOnly: true,
    note: "Catches the morning gainers ($1–$20, +10% on 5x volume). Includes pre-market hour."
  },
  {
    name: "ORB (opening range breakout)",
    short: "8:30 AM – 12:00 PM ET",
    startHourEt: 8.5,
    endHourEt: 12.0,
    weekdayOnly: true,
    note: "Trades the first 5-min range breakout. Includes pre-market opening range so the bot has more daylight to confirm a continuation."
  },
  {
    name: "Extended Strategy (swing)",
    short: "8:30 AM – 6:30 PM ET",
    startHourEt: 8.5,
    endHourEt: 18.5,
    weekdayOnly: true,
    note: "The multi-day swing layer — sees pre-market news AND after-hours moves (post-close earnings, guidance), so it can react before the next-day open instead of waiting for it."
  },
  {
    name: "Options Scanner / Wheel",
    short: "every 30 min",
    startHourEt: 0,
    endHourEt: 24,
    weekdayOnly: false,
    note: "Settles + reconciles + emits Wheel and options ideas. Runs around the clock."
  },
  {
    name: "Crypto Scanner",
    short: "24/7",
    startHourEt: 0,
    endHourEt: 24,
    weekdayOnly: false,
    note: "XRP / ETH / SOL momentum scanner. Crypto markets never close."
  }
];

function nowEtHour(): { hour: number; weekday: number } {
  // Eastern-time slice via Intl — no zoneinfo dep on the client.
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour12: false,
    weekday: "short",
    hour: "numeric",
    minute: "numeric"
  });
  const parts = fmt.formatToParts(new Date());
  const wkMap: Record<string, number> = {
    Sun: 0,
    Mon: 1,
    Tue: 2,
    Wed: 3,
    Thu: 4,
    Fri: 5,
    Sat: 6
  };
  const wk = wkMap[parts.find((p) => p.type === "weekday")?.value ?? "Sun"] ?? 0;
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  return { hour: h + m / 60, weekday: wk };
}

function isOpen(w: WindowSpec, now: { hour: number; weekday: number }): boolean {
  if (w.weekdayOnly && (now.weekday === 0 || now.weekday === 6)) return false;
  return now.hour >= w.startHourEt && now.hour <= w.endHourEt;
}

/**
 * Strategy Windows — a single panel that shows every scanner's trading
 * window and which are LIVE right now (Eastern Time). Resolves the
 * common confusion of "is the agent idle because the window is closed
 * or because something is broken?"
 *
 * Includes a callout that DATA FEEDS run 24/7 (pre-market candles,
 * news, fundamentals, cross-asset reads) — only the TRADE-firing
 * windows are time-gated. Pattern Detection still observes pre-market
 * even when STMS / ORB / Extended are idle.
 */
export function StrategyWindows() {
  const now = nowEtHour();
  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">Strategy windows today</h2>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-1">
            Every scanner runs on its own clock. Green = trading window
            open right now, amber = window closed but still observing.
            Pre-market data feeds run regardless — Pattern Detection and
            Market Horizons see the tape from 4 AM ET.
          </p>
        </div>
        <span className="text-[11px] uppercase tracking-widest text-weave-500">
          Now: {now.hour.toFixed(2).replace(".", ":").padStart(5, "0")} ET ·{" "}
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][now.weekday]}
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {WINDOWS.map((w) => {
          const open = isOpen(w, now);
          return (
            <div
              key={w.name}
              className={cn(
                "rounded-lg border p-3 space-y-1",
                open
                  ? "border-emerald-200 bg-emerald-50/60"
                  : "border-weave-100 bg-weave-50/40"
              )}
            >
              <div className="flex items-baseline justify-between gap-2 flex-wrap">
                <p className="font-medium text-weave-800 text-sm">{w.name}</p>
                <span
                  className={cn(
                    "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                    open ? "bg-emerald-100 text-emerald-800" : "bg-weave-100 text-weave-600"
                  )}
                >
                  {open ? "Trading" : "Observing"}
                </span>
              </div>
              <p className="text-xs font-mono text-weave-500">{w.short}</p>
              <p className="text-xs text-weave-600 leading-relaxed">{w.note}</p>
            </div>
          );
        })}
      </div>
      <p className="text-[11px] text-weave-500 leading-relaxed">
        <span className="font-medium">Data is always on.</span> Even when
        a strategy&apos;s trade window is closed, its data feeds
        (candles, news, fundamentals, cross-asset reads) still pull
        every tick. The Extended swing layer, for example, lets
        pre-market news shape its first signal of the day.
      </p>
    </section>
  );
}
