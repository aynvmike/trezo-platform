import { RefreshCw, Info } from "lucide-react";

/**
 * Trading view — Neo Obsidian layout. Renders LIVE data when a `data`
 * prop is supplied (see dashboard/trading-preview/page.tsx) and falls
 * back to a clearly-labelled sample when it is not.
 */

/**
 * GEOMETRY -- the shape of a trade's risk and reward (Mike 2026-08-05).
 *
 * Reward-to-risk decides how often you have to be right to make money.
 * At 1:2 you can lose most of your trades and still profit; below 1:1 the
 * arithmetic is against you no matter how good the entry was. This was
 * invisible until a rescale in the crypto scalp lane quietly turned a
 * designed 1:2 into 1:1.67 and nobody could see it for weeks.
 *
 * Derived from entry/stop/target already on the row -- no new data.
 */
function geometryOf(entry: number, stop?: number | null, target?: number | null) {
  if (!entry || entry <= 0 || stop == null || target == null) return null;
  const riskPct = Math.abs(entry - stop) / entry;
  const rewardPct = Math.abs(target - entry) / entry;
  if (riskPct <= 0 || rewardPct <= 0) return null;
  const rr = rewardPct / riskPct;
  return {
    riskPct: riskPct * 100,
    rewardPct: rewardPct * 100,
    rr,
    // The break-even win rate this geometry demands. Makes the ratio concrete.
    needWin: 100 / (1 + rr),
    tone:
      rr >= 2 ? "text-emerald-500"
      : rr >= 1.5 ? "text-[rgb(var(--muted-foreground))]"
      : rr >= 1 ? "text-amber-500"
      : "text-red-500",
    label: rr >= 2 ? "healthy" : rr >= 1.5 ? "workable" : rr >= 1 ? "thin" : "upside down",
  };
}

export type TVPosition = {
  id: string | number;
  ticker: string;
  side: string;
  layer: string;
  chip: number;
  entry: number;
  current: number | null;
  qty: number;
  pnl: number | null;
  pct: number | null;
  flag?: "live" | "modeled" | "unconfirmed";
  stop?: number | null;
  target?: number | null;
  heldSince?: string;
  why?: string;
  plan?: string;
  locked?: boolean;
  // Agent recommendation (Mike 2026-07-28) + where the position lives.
  verdict?: "BANK" | "TIGHTEN" | "CUT" | "TRIM" | "WATCH" | "HOLD";
  verdictWhy?: string;
  verdictAction?: string;
  assetKind?: "Crypto" | "Stock" | "Forex" | "Option";
  atBroker?: boolean | null;
};

// Verdict colours: act-now verdicts read hot, HOLD stays quiet.
export const VERDICT_STYLE: Record<string, string> = {
  BANK: "text-emerald-600 bg-emerald-500/15 border-emerald-500/40",
  TIGHTEN: "text-amber-600 bg-amber-500/15 border-amber-500/40",
  CUT: "text-red-600 bg-red-500/15 border-red-500/40",
  TRIM: "text-sky-600 bg-sky-500/15 border-sky-500/40",
  WATCH: "text-violet-600 bg-violet-500/15 border-violet-500/40",
  HOLD: "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))] border-[rgb(var(--border))]",
};

// Asset kind reads at a glance -- Mike 2026-07-28: "so I can tell what is
// going on better than trying to recognize if the item is a Stock or crypto".
export const KIND_STYLE: Record<string, string> = {
  Crypto: "text-orange-600 bg-orange-500/10",
  Stock: "text-blue-600 bg-blue-500/10",
  Forex: "text-teal-600 bg-teal-500/10",
  Option: "text-purple-600 bg-purple-500/10",
};

export type TVFeed = {
  id: string | number;
  time: string;
  agent: string;
  action: string;
  reason: string;
  layer: number;
  type: string;
};

export type TVMarket = { label: string; value: string; delta: string; up: boolean };

export type TradingData = {
  portfolioValue: number;
  todayPnl: number;
  todayPct: number | null;
  deployed: number;
  deployedPct: number | null;
  openCount: number;
  pnlSeries: number[];
  positions: TVPosition[];
  feed: TVFeed[];
  market: TVMarket[];
  paperMode: boolean;
  autoTrade: boolean;
  riskLimit: number;
  asOf: string;
  live: boolean;
};

const SAMPLE: TradingData = {
  portfolioValue: 142380,
  todayPnl: 2147,
  todayPct: 1.53,
  deployed: 8420,
  deployedPct: 5.9,
  openCount: 6,
  pnlSeries: [0, 420, 310, 780, 650, 920, 1100, 870, 1350, 1580, 1420, 1760, 1890, 2147],
  positions: [
    { id: 1, ticker: "NVDA", side: "LONG", layer: "Stock", chip: 2, entry: 874.2, current: 891.45, qty: 10, pnl: 172.5, pct: 1.97 },
    { id: 2, ticker: "BTC-PERP", side: "LONG", layer: "Crypto", chip: 1, entry: 67240, current: 68910, qty: 0.25, pnl: 417.5, pct: 2.49 },
    { id: 3, ticker: "SPY 560C 06/21", side: "LONG", layer: "Options", chip: 3, entry: 3.8, current: 5.1, qty: 5, pnl: 650, pct: 34.21 },
    { id: 4, ticker: "AAPL", side: "SHORT", layer: "Stock", chip: 2, entry: 192.4, current: 189.15, qty: 15, pnl: 48.75, pct: 1.69 },
    { id: 5, ticker: "ETH-PERP", side: "LONG", layer: "Crypto", chip: 1, entry: 3185, current: 3090, qty: 1.5, pnl: -142.5, pct: -2.98 },
    { id: 6, ticker: "MSFT 420P 06/28", side: "LONG", layer: "Options", chip: 3, entry: 2.15, current: 1.8, qty: 3, pnl: -105, pct: -16.28 },
  ],
  feed: [
    { id: 1, time: "15:47", agent: "Crypto Bot", action: "Opened BTC-PERP long", reason: "RSI reset at 4H support, MACD bullish cross", layer: 1, type: "open" },
    { id: 2, time: "14:32", agent: "Stock Bot", action: "Partial exit NVDA x5", reason: "Price reached first target, locking 50% gain", layer: 2, type: "exit" },
    { id: 3, time: "13:15", agent: "Options Bot", action: "Opened SPY 560C x5", reason: "IV rank low, momentum aligning with the weekly trend", layer: 3, type: "open" },
    { id: 4, time: "12:58", agent: "Wheel Bot", action: "Closed TSLA CSP, expired worthless", reason: "Option expired OTM, premium captured in full", layer: 5, type: "exit" },
    { id: 5, time: "11:20", agent: "Stock Bot", action: "Opened AAPL short x15", reason: "Overbought on the daily, rejection at resistance", layer: 2, type: "open" },
    { id: 6, time: "10:04", agent: "Crypto Bot", action: "Risk alert on ETH volatility spike", reason: "Trailing stop tightened automatically to -4%", layer: 1, type: "alert" },
  ],
  market: [
    { label: "SPY", value: "557.82", delta: "+0.84%", up: true },
    { label: "QQQ", value: "478.14", delta: "+1.12%", up: true },
    { label: "VIX", value: "13.4", delta: "-1.8", up: false },
    { label: "BTC", value: "$68,910", delta: "+2.49%", up: true },
    { label: "10Y", value: "4.28%", delta: "+0.03%", up: true },
    { label: "DXY", value: "104.2", delta: "-0.21%", up: false },
  ],
  paperMode: true,
  autoTrade: false,
  riskLimit: 500,
  asOf: "Thu Jun 18, 2026 · US Market Open",
  live: false,
};

const LAYER_CHIP: Record<number, string> = {
  1: "text-treasure-400 bg-treasure-400/10",
  2: "text-sky-500 bg-sky-500/10",
  3: "text-amber-500 bg-amber-500/10",
  4: "text-violet-500 bg-violet-500/10",
  5: "text-emerald-500 bg-emerald-500/10",
  7: "text-treasure-500 bg-treasure-500/10",
};
const DOT: Record<string, string> = { open: "bg-emerald-500", exit: "bg-sky-500", alert: "bg-amber-500" };

function money(n: number) {
  return (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function money0(n: number) {
  return (n < 0 ? "-" : "") + "$" + Math.abs(Math.round(n)).toLocaleString();
}
function signed0(n: number) {
  return (n >= 0 ? "+" : "-") + "$" + Math.abs(Math.round(n)).toLocaleString();
}
function price(n: number) {
  return n > 1000 ? "$" + n.toLocaleString() : "$" + n.toFixed(2);
}

function Sparkline({ data }: { data: number[] }) {
  const w = 600;
  const h = 140;
  const pad = 8;
  const safe = data.length >= 2 ? data : [0, 0];
  const min = Math.min(...safe);
  const max = Math.max(...safe);
  const span = max - min || 1;
  const pts = safe.map((v, i) => {
    const x = (i / (safe.length - 1)) * w;
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return x.toFixed(1) + " " + y.toFixed(1);
  });
  const line = "M " + pts.join(" L ");
  const area = line + " L " + w + " " + h + " L 0 " + h + " Z";
  return (
    <svg viewBox={"0 0 " + w + " " + h} className="w-full" style={{ height: 140 }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="pnlg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgb(var(--emerald-500))" stopOpacity={0.22} />
          <stop offset="100%" stopColor="rgb(var(--emerald-500))" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#pnlg)" />
      <path d={line} fill="none" stroke="rgb(var(--emerald-500))" strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Kpi(props: { label: string; value: string; sub: string; pill?: string; pillClass?: string; delta?: string; up?: boolean }) {
  return (
    <div className="depth-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-[rgb(var(--muted-foreground))]">{props.label}</span>
        {props.pill ? (
          <span className={"rounded-full px-1.5 py-0.5 font-mono text-[10px] " + (props.pillClass || "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]")}>{props.pill}</span>
        ) : null}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono text-[22px] text-[rgb(var(--foreground))]" style={{ fontWeight: 600 }}>{props.value}</span>
        {props.delta ? <span className={"font-mono text-[12px] " + (props.up ? "text-emerald-500" : "text-red-500")}>{props.up ? "▲" : "▼"} {props.delta}</span> : null}
      </div>
      <p className="mt-1 text-[11px] text-[rgb(var(--muted-foreground))]">{props.sub}</p>
    </div>
  );
}

export function TradingViewRedesign({ data, closeAction }: { data?: TradingData; closeAction?: (formData: FormData) => Promise<void> }) {
  const d = data ?? SAMPLE;
  const net = d.positions.reduce((a, p) => a + (p.pnl ?? 0), 0);
  const winning = d.positions.filter((p) => (p.pnl ?? 0) > 0).length;
  const losing = d.positions.filter((p) => (p.pnl ?? 0) < 0).length;
  const unconfirmed = d.positions.filter((p) => p.flag === "unconfirmed").length;
  const showMarket = d.market.length > 0;
  const sessionFacts: TVMarket[] = [
    { label: "Open positions", value: String(d.openCount), delta: "", up: true },
    { label: "Net unrealized", value: signed0(net), delta: "", up: net >= 0 },
    { label: "Deployed", value: money0(d.deployed), delta: d.deployedPct != null ? d.deployedPct.toFixed(1) + "%" : "", up: true },
    { label: "Mode", value: d.paperMode ? "Paper" : "Live", delta: "", up: true },
  ];
  return (
    <div className="space-y-8 depth-page">
      {d.live ? null : (
        <div className="rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 px-4 py-2 text-[12px] text-[rgb(var(--muted-foreground))]">
          Design preview &mdash; the Neo Obsidian Trading layout with sample data. Sign in and open this page with the agents service running to see it live.
        </div>
      )}

      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-serif text-[28px] text-[rgb(var(--foreground))]">Trading</h1>
          <p className="mt-1 text-[13px] text-[rgb(var(--muted-foreground))]">{d.live ? "Live session" : "Sample session"} &middot; {d.asOf}</p>
        </div>
        <span className="flex items-center gap-1.5 rounded-lg border border-[rgb(var(--border))] px-3 py-1.5 text-[12px] text-[rgb(var(--muted-foreground))]">
          <RefreshCw size={12} /> {d.live ? "Auto-refreshes on reload" : "Preview"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Portfolio Value" value={money0(d.portfolioValue)} sub="Cash + vault, across all 7 layers" pill={d.paperMode ? "Paper" : "Live"} pillClass="text-emerald-500 bg-emerald-500/10" />
        <Kpi label="Today's P&L" value={signed0(d.todayPnl)} delta={d.todayPct != null ? d.todayPct.toFixed(2) + "%" : undefined} up={d.todayPnl >= 0} sub={d.live ? "Realized — trades closed today" : "Since market open at 9:30 AM"} />
        <Kpi label="Open Risk" value={money0(d.deployed)} sub="Capital deployed in open positions" pill={d.deployedPct != null ? d.deployedPct.toFixed(1) + "% deployed" : undefined} pillClass="text-sky-500 bg-sky-500/10" />
        <Kpi label="Open Positions" value={String(d.openCount)} sub={winning + " winning · " + losing + " losing"} pill={d.openCount > 0 ? "live" : "flat"} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="depth-card p-4 md:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-[13px] font-medium text-[rgb(var(--foreground))]">{"Intraday P&L"}</h3>
              <p className="text-[11px] text-[rgb(var(--muted-foreground))]">{d.live ? "Cumulative realized P&L today" : "Cumulative gain/loss since market open"}</p>
            </div>
            <span className={"font-mono text-[13px] " + (d.todayPnl >= 0 ? "text-emerald-500" : "text-red-500")}>{signed0(d.todayPnl)}</span>
          </div>
          <Sparkline data={d.pnlSeries} />
        </div>
        <div className="depth-card p-4">
          <h3 className="mb-3 text-[13px] font-medium text-[rgb(var(--foreground))]">{showMarket ? "Market Context" : "This Session"}</h3>
          <div className="space-y-2.5">
            {(showMarket ? d.market : sessionFacts).map((m) => (
              <div key={m.label} className="flex items-center justify-between">
                <span className="font-mono text-[12px] text-[rgb(var(--muted-foreground))]">{m.label}</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[12px] text-[rgb(var(--foreground))]">{m.value}</span>
                  {m.delta ? <span className={"font-mono text-[11px] " + (m.up ? "text-emerald-500" : "text-red-500")}>{m.delta}</span> : null}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 border-t border-[rgb(var(--border))] pt-3">
            <p className="text-[11px] text-[rgb(var(--muted-foreground))]">{showMarket ? "Low VIX means a calm market — your options strategies tend to do better here." : "These are your live account figures, refreshed each time you open the page."}</p>
          </div>
        </div>
      </div>

      <div className="overflow-hidden depth-card">
        <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-5 py-4">
          <div>
            <h3 className="text-[13px] font-medium text-[rgb(var(--foreground))]">Open Positions</h3>
            <p className="mt-0.5 text-[11px] text-[rgb(var(--muted-foreground))]">{d.positions.length} open &mdash; {winning} winning, {losing} losing{unconfirmed > 0 ? <span className="text-amber-500"> &middot; {unconfirmed} unconfirmed</span> : null}</p>
          </div>
          <span className={"font-mono text-[12px] font-medium " + (net >= 0 ? "text-emerald-500" : "text-red-500")}>Net {net >= 0 ? "+" : ""}{money(net)}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-[rgb(var(--border))]">
                {["Ticker", "Layer", "Side", "Entry", "Current", "Qty", "P&L", ""].map((c, i) => (
                  <th key={i} className="px-5 py-3 text-left font-mono font-medium tracking-wide text-[rgb(var(--muted-foreground))]">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.positions.length === 0 ? (
                <tr><td colSpan={8} className="px-5 py-8 text-center text-[rgb(var(--muted-foreground))]">No open positions. When an approved signal fires, it lands here.</td></tr>
              ) : d.positions.flatMap((p) => [
                <tr key={String(p.id) + "-m"} className="border-b border-[rgb(var(--border))] last:border-0 hover:bg-[rgb(var(--muted))]">
                  <td className="px-5 py-3 font-mono font-medium text-[rgb(var(--foreground))]">
                    <span className="inline-flex items-center gap-1.5">
                      {p.ticker}
                      {p.assetKind ? (
                        <span title={p.assetKind} className={"rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide " + (KIND_STYLE[p.assetKind] || "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]")}>{p.assetKind}</span>
                      ) : null}
                      {p.atBroker === false ? (
                        <span title="Modeled on Trezo's paper engine using live market data — this position does NOT appear on your Alpaca screen (the venue does not list it)" className="rounded px-1 py-0.5 text-[9px] font-normal uppercase tracking-wide text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]">not at broker</span>
                      ) : p.atBroker === true ? (
                        <span title="Real order held at Alpaca — visible on your Alpaca screen" className="rounded px-1 py-0.5 text-[9px] font-normal uppercase tracking-wide text-emerald-600 bg-emerald-500/10">at broker</span>
                      ) : p.flag === "unconfirmed" ? (
                        <span title="No matching position at Alpaca — unconfirmed (a just-submitted order, a modeled fill, or a phantom row to reconcile)" className="rounded px-1 py-0.5 text-[9px] font-normal uppercase tracking-wide text-amber-500 bg-amber-500/10">unconfirmed</span>
                      ) : p.flag === "modeled" ? (
                        <span title="Modeled — runs on Trezo's paper engine, not held at Alpaca" className="rounded px-1 py-0.5 text-[9px] font-normal uppercase tracking-wide text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]">modeled</span>
                      ) : null}
                      {p.verdict && p.verdict !== "HOLD" ? (
                        <span title={p.verdictAction || ""} className={"rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide " + (VERDICT_STYLE[p.verdict] || "")}>{p.verdict}</span>
                      ) : null}
                    </span>
                  </td>
                  <td className="px-5 py-3"><span className={"rounded-md px-2 py-0.5 font-mono text-[11px] " + (LAYER_CHIP[p.chip] || "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]")}>{p.chip} &middot; {p.layer}</span></td>
                  <td className="px-5 py-3"><span className={"rounded px-1.5 py-0.5 font-mono text-[11px] " + (p.side === "LONG" ? "text-emerald-500 bg-emerald-500/10" : "text-red-500 bg-red-500/10")}>{p.side}</span></td>
                  <td className="px-5 py-3 font-mono text-[rgb(var(--muted-foreground))]">{price(p.entry)}</td>
                  <td className="px-5 py-3 font-mono text-[rgb(var(--foreground))]">{p.current == null ? "—" : price(p.current)}</td>
                  <td className="px-5 py-3 font-mono text-[rgb(var(--muted-foreground))]">{p.qty}</td>
                  <td className="px-5 py-3">
                    {p.pnl == null ? (
                      <span className="font-mono text-[rgb(var(--muted-foreground))]">—</span>
                    ) : (
                      <div className="flex flex-col">
                        <span className={"font-mono font-medium " + (p.pnl >= 0 ? "text-emerald-500" : "text-red-500")}>{p.pnl >= 0 ? "+" : ""}{money(p.pnl)}</span>
                        {p.pct != null ? <span className={"font-mono text-[10px] opacity-75 " + (p.pct >= 0 ? "text-emerald-500" : "text-red-500")}>{p.pct >= 0 ? "+" : ""}{p.pct.toFixed(2)}%</span> : null}
                      </div>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {d.live && closeAction ? (
                      <form action={closeAction}>
                        <input type="hidden" name="position_id" value={String(p.id)} />
                        <button type="submit" className="rounded-md border border-[rgb(var(--border))] px-2.5 py-1 text-[11px] text-[rgb(var(--muted-foreground))] transition hover:border-red-500/50 hover:text-red-500">Close</button>
                      </form>
                    ) : (
                      <span className="rounded-md border border-[rgb(var(--border))] px-2 py-1 text-[11px] text-[rgb(var(--muted-foreground))]">{p.layer}</span>
                    )}
                  </td>
                </tr>,
                (p.why || p.plan || p.verdict || p.stop != null || p.target != null) ? (
                  <tr key={String(p.id) + "-why"} className="border-b border-[rgb(var(--border))] last:border-0">
                    <td colSpan={8} className="px-5 pb-3 pt-0">
                      <div className="rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--muted))] px-3 py-2">
                        {p.verdict ? (
                          <p className="mb-1 text-[11px]">
                            <span className={"mr-1.5 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide " + (VERDICT_STYLE[p.verdict] || "")}>{p.verdict}</span>
                            <span className="text-[rgb(var(--foreground))]">{p.verdictWhy}</span>
                            {p.verdictAction ? <span className="text-[rgb(var(--muted-foreground))]"> {p.verdictAction}</span> : null}
                          </p>
                        ) : null}
                        {p.why ? <p className="text-[11px] text-[rgb(var(--foreground))]">{p.why}</p> : null}
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-[rgb(var(--muted-foreground))]">
                          {p.heldSince ? <span>Held {p.heldSince}</span> : null}
                          {p.stop != null ? <span>Stop {price(p.stop)}</span> : null}
                          {p.target != null ? <span>Target {price(p.target)}</span> : null}
                          {(() => {
                            const g = geometryOf(p.entry, p.stop, p.target);
                            return g ? (
                              <span
                                className={g.tone}
                                title={`Risk ${g.riskPct.toFixed(1)}% to make ${g.rewardPct.toFixed(1)}%. At 1:${g.rr.toFixed(2)} you need to be right about ${g.needWin.toFixed(0)}% of the time just to break even.`}
                              >
                                Geometry 1:{g.rr.toFixed(2)} ({g.label})
                              </span>
                            ) : null;
                          })()}
                          {p.locked ? <span className="text-emerald-500">● Profit locked</span> : null}
                        </div>
                        {p.plan ? <p className="mt-1 text-[11px] text-[rgb(var(--muted-foreground))]">{p.plan}</p> : null}
                      </div>
                    </td>
                  </tr>
                ) : null,
              ])}
            </tbody>
          </table>
        </div>
      </div>

      <div className="overflow-hidden depth-card">
        <div className="border-b border-[rgb(var(--border))] px-5 py-4">
          <h3 className="text-[13px] font-medium text-[rgb(var(--foreground))]">Agent Activity</h3>
          <p className="mt-0.5 text-[11px] text-[rgb(var(--muted-foreground))]">What your bots have been doing today, in plain English</p>
        </div>
        <div>
          {d.feed.length === 0 ? (
            <div className="px-5 py-8 text-center text-[12px] text-[rgb(var(--muted-foreground))]">No agent activity yet. When the agents service runs, its plain-English updates appear here.</div>
          ) : d.feed.map((r) => (
            <div key={r.id} className="flex items-start gap-4 border-b border-[rgb(var(--border))] px-5 py-3.5 last:border-0 hover:bg-[rgb(var(--muted))]">
              <span className="mt-0.5 min-w-[36px] shrink-0 font-mono text-[11px] text-[rgb(var(--muted-foreground))]">{r.time}</span>
              <div className={"mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full " + (DOT[r.type] || "bg-[rgb(var(--muted-foreground))]")} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-medium text-[rgb(var(--foreground))]">{r.action}</span>
                  <span className={"rounded px-1.5 py-0.5 font-mono text-[10px] " + (LAYER_CHIP[r.layer] || "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]")}>{r.layer ? r.layer + " · " : ""}{r.agent}</span>
                </div>
                {r.reason ? <p className="mt-0.5 text-[12px] text-[rgb(var(--muted-foreground))]">{r.reason}</p> : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="depth-card p-5">
        <div className="mb-4 flex items-center gap-2">
          <h3 className="text-[13px] font-medium text-[rgb(var(--foreground))]">Session Settings</h3>
          <span className="rounded-full border border-dashed border-amber-500/40 px-2 py-0.5 font-mono text-[11px] text-amber-500">{d.paperMode ? "Paper Mode" : "Live Mode"}</span>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {[
            { label: "Trading Mode", value: d.paperMode ? "Paper" : "Live", note: d.paperMode ? "No real orders. Safe to test." : "Live brokerage routing." },
            { label: "Auto-Trade", value: d.autoTrade ? "ON" : "OFF", note: d.autoTrade ? "Bots execute approved signals." : "Bots signal but do not execute." },
            { label: "Risk Limit / Day", value: money0(d.riskLimit), note: "Max realized loss before bots pause." },
          ].map((it) => (
            <div key={it.label} className="rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--muted))] p-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[11px] text-[rgb(var(--muted-foreground))]">{it.label}</span>
                <Info size={11} className="text-[rgb(var(--muted-foreground))]" />
              </div>
              <div className="font-mono text-[13px] font-medium text-[rgb(var(--foreground))]">{it.value}</div>
              <p className="mt-1 text-[11px] text-[rgb(var(--muted-foreground))]">{it.note}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
