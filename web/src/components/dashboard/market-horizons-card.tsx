import { cn } from "@/lib/utils";

type Asset = {
  ticker: string;
  label: string;
  price: number;
  change_5d_pct: number;
  sparkline: number[];
};

type Correlation = {
  a: string;
  b: string;
  a_label: string;
  b_label: string;
  rho: number;
  window_bars: number;
  note: string;
};

type Snapshot = {
  assets?: Record<string, Asset>;
  correlations?: Correlation[];
  summary?: string;
  error?: string;
};

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type MacroSnap = {
  configured: boolean;
  source?: string | null;
  attribution?: string;
  note?: string;
  regime?: "growth" | "neutral" | "risk_off";
  reason?: string;
  vix?: number | null;
  yield_spread_10y3m?: number | null;
  fed_funds_rate?: number | null;
  observation_dates?: Record<string, string>;
};

async function loadSnapshot(): Promise<Snapshot | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/markets/pulse`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    if (!r.ok) return null;
    return (await r.json()) as Snapshot;
  } catch {
    return null;
  }
}

async function loadMacro(): Promise<MacroSnap | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/macro/snapshot`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    if (!r.ok) return null;
    return (await r.json()) as MacroSnap;
  } catch {
    return null;
  }
}

/**
 * Market Horizons inline card — folded into the Paper Trading page so
 * the user sees the cross-asset read alongside their account, without
 * needing a dedicated /dashboard/markets route (Mike consolidated it).
 *
 * Sections: asset-class pulse (6 sparklines) + cross-asset relationships
 * (correlation cards). The "Investment vehicles to know" educational
 * section moved to /dashboard/help as a disclosure.
 */
export async function MarketHorizonsCard() {
  const [snap, macro] = await Promise.all([loadSnapshot(), loadMacro()]);
  const assets = snap?.assets ?? {};
  const assetEntries = Object.entries(assets);
  const corr = snap?.correlations ?? [];

  if (assetEntries.length === 0 && corr.length === 0 && !macro?.configured) {
    return null; // silently hide when agents service is warming
  }

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-5">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">Market Horizons</h2>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-1">
            The whole landscape — six asset classes and the relationships
            between them. The agents read this when deciding posture, so
            you can see what they see.
          </p>
        </div>
        <p className="text-[11px] uppercase tracking-widest text-weave-500">
          5-day change · refreshed every 15 min
        </p>
      </div>

      {macro?.configured && <MacroPanel macro={macro} />}

      {assetEntries.length > 0 && (
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-3">
          {assetEntries.map(([key, a]) => (
            <AssetCard key={key} asset={a} />
          ))}
        </div>
      )}
      {snap?.summary && (
        <p className="beginner-only text-xs text-weave-500 leading-relaxed">
          {snap.summary}
        </p>
      )}

      {corr.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-weave-700">
            Cross-asset relationships
          </h3>
          <p className="beginner-only text-[11px] text-weave-500 leading-relaxed">
            +1.00 = lockstep, −1.00 = opposite, near 0 = independent.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {corr.map((c) => (
              <CorrelationCard
                key={`${c.a}-${c.b}`}
                corr={c}
                assetA={assets[c.a]}
                assetB={assets[c.b]}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function MacroPanel({ macro }: { macro: MacroSnap }) {
  const regimeTone =
    macro.regime === "growth"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : macro.regime === "risk_off"
        ? "border-red-200 bg-red-50 text-red-900"
        : "border-weave-200 bg-weave-50 text-weave-800";

  const vix = macro.vix ?? null;
  const spread = macro.yield_spread_10y3m ?? null;
  const fed = macro.fed_funds_rate ?? null;

  return (
    <div className={cn("rounded-lg border p-4 space-y-3", regimeTone)}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <p className="text-[10px] uppercase tracking-widest opacity-70">
            Macro regime · source: {macro.source ?? "unknown"}
          </p>
          <p className="mt-0.5 text-sm font-medium">
            {macro.regime === "growth"
              ? "Growth — risk-on"
              : macro.regime === "risk_off"
                ? "Risk-off — defensive"
                : "Neutral"}
          </p>
        </div>
        <span className="text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5 bg-white/60">
          {macro.regime}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <MacroTile
          label="VIX"
          value={vix !== null ? vix.toFixed(1) : "—"}
          hint={
            vix === null
              ? "not from this source"
              : vix > 25
                ? "scared"
                : vix < 16
                  ? "complacent"
                  : "normal"
          }
        />
        <MacroTile
          label="10Y - 3M"
          value={spread !== null ? `${spread >= 0 ? "+" : ""}${spread.toFixed(2)}%` : "—"}
          hint={
            spread === null
              ? "not from this source"
              : spread < 0
                ? "inverted"
                : spread > 1
                  ? "steep"
                  : "flat"
          }
        />
        <MacroTile
          label="Fed Funds"
          value={fed !== null ? `${fed.toFixed(2)}%` : "—"}
          hint={fed === null ? "not from this source" : "DFF"}
        />
      </div>
      {macro.reason && (
        <p className="text-[11px] leading-relaxed opacity-80">{macro.reason}</p>
      )}
      {macro.attribution && (
        <p className="text-[10px] leading-relaxed opacity-60 pt-2 border-t border-current/10">
          {macro.attribution}
        </p>
      )}
    </div>
  );
}

function MacroTile({
  label,
  value,
  hint
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded bg-white/60 p-2">
      <p className="text-[10px] uppercase tracking-widest opacity-70">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-medium">{value}</p>
      <p className="text-[10px] opacity-70">{hint}</p>
    </div>
  );
}

function AssetCard({ asset }: { asset: Asset }) {
  const up = asset.change_5d_pct >= 0;
  return (
    <div className="rounded-lg border border-weave-100 bg-weave-50/40 p-3 space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-widest text-weave-500">
            {asset.label}
          </p>
          <p className="mt-0.5 font-mono text-xs text-weave-700">
            {asset.ticker} · ${asset.price.toFixed(2)}
          </p>
        </div>
        <span
          className={cn(
            "font-mono text-xs font-medium",
            up ? "text-emerald-700" : "text-red-700"
          )}
        >
          {up ? "+" : ""}
          {asset.change_5d_pct}%
        </span>
      </div>
      <Sparkline points={asset.sparkline} positive={up} />
    </div>
  );
}

function CorrelationCard({
  corr,
  assetA,
  assetB
}: {
  corr: Correlation;
  assetA?: Asset;
  assetB?: Asset;
}) {
  const rho = corr.rho;
  const strength =
    Math.abs(rho) >= 0.6 ? "strong" : Math.abs(rho) >= 0.3 ? "moderate" : "weak";
  const sign = rho >= 0 ? "positive" : "negative";
  const toneClass =
    rho >= 0.3
      ? "text-emerald-700"
      : rho <= -0.3
      ? "text-treasure-700"
      : "text-weave-500";
  return (
    <div className="rounded-lg border border-weave-100 bg-weave-50/40 p-3 space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-medium text-weave-800">
          {corr.a_label} vs {corr.b_label}
        </p>
        <span className={cn("font-mono text-xs font-medium", toneClass)}>
          ρ {rho >= 0 ? "+" : ""}
          {rho}
        </span>
      </div>
      <p className="text-[11px] text-weave-500 leading-relaxed">
        {strength}, {sign} ({corr.window_bars} days). {corr.note}
      </p>
      {(assetA || assetB) && (
        <div className="grid grid-cols-2 gap-2 pt-1">
          {assetA && <Sparkline points={assetA.sparkline} positive={assetA.change_5d_pct >= 0} compact />}
          {assetB && <Sparkline points={assetB.sparkline} positive={assetB.change_5d_pct >= 0} compact />}
        </div>
      )}
    </div>
  );
}

function Sparkline({
  points,
  positive,
  compact = false
}: {
  points: number[];
  positive: boolean;
  compact?: boolean;
}) {
  if (!points || points.length < 2) {
    return <div className="h-10 rounded bg-weave-50/40" />;
  }
  const W = 200;
  const H = compact ? 24 : 36;
  const pad = 2;
  const hi = Math.max(...points);
  const lo = Math.min(...points);
  const span = hi - lo || 1;
  const n = points.length;
  const xf = (i: number) => pad + (i / (n - 1)) * (W - 2 * pad);
  const yf = (v: number) => pad + (1 - (v - lo) / span) * (H - 2 * pad);
  const line = points.map((v, i) => `${xf(i)},${yf(v)}`).join(" ");
  const stroke = positive ? "#10b981" : "#f87171";
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="w-full rounded bg-white/60"
      style={{ height: H }}
      role="img"
      aria-label="Recent price"
    >
      <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.5} />
    </svg>
  );
}
