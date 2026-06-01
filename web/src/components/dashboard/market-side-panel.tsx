"use client";

import { useState } from "react";
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
};

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

/**
 * Market data side panel - Mike feedback 2026-05-30. Three tabs:
 *   Macro          (regime classification + VIX / 10Y-3M / Fed Funds)
 *   Pulse          (6 asset-class sparklines)
 *   Correlations   (cross-asset relationships + small sparklines)
 *
 * Designed to live in a sticky right rail on /dashboard/paper so the
 * main content gets more room and the user can scroll independently
 * of the market reads.
 */
export function MarketSidePanel({
  snapshot,
  macro
}: {
  snapshot: Snapshot | null;
  macro: MacroSnap | null;
}) {
  const [tab, setTab] = useState<"macro" | "pulse" | "corr">(
    macro?.configured ? "macro" : "pulse"
  );

  const assets = snapshot?.assets ?? {};
  const assetEntries = Object.entries(assets);
  const corr = snapshot?.correlations ?? [];

  const hasMacro = !!macro?.configured;
  const hasPulse = assetEntries.length > 0;
  const hasCorr = corr.length > 0;

  // If literally nothing to show, render nothing.
  if (!hasMacro && !hasPulse && !hasCorr) return null;

  return (
    <aside className="rounded-xl border border-weave-100 bg-white">
      <div className="flex items-center gap-1 border-b border-weave-100 px-2 py-2">
        <h3 className="font-serif text-sm text-weave-800 px-2 mr-auto">
          Market data
        </h3>
        <TabButton
          active={tab === "macro"}
          disabled={!hasMacro}
          onClick={() => setTab("macro")}
          label="Macro"
        />
        <TabButton
          active={tab === "pulse"}
          disabled={!hasPulse}
          onClick={() => setTab("pulse")}
          label="Pulse"
        />
        <TabButton
          active={tab === "corr"}
          disabled={!hasCorr}
          onClick={() => setTab("corr")}
          label="Cross"
        />
      </div>

      <div className="p-3">
        {tab === "macro" && hasMacro && <MacroTab macro={macro!} />}
        {tab === "pulse" && hasPulse && (
          <PulseTab assets={assetEntries} summary={snapshot?.summary} />
        )}
        {tab === "corr" && hasCorr && (
          <CorrTab corr={corr} assets={assets} />
        )}
      </div>
    </aside>
  );
}

function TabButton({
  active,
  disabled,
  onClick,
  label
}: {
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "text-[11px] uppercase tracking-widest rounded-md px-2 py-1 transition",
        active
          ? "bg-weave-600 text-treasure-50"
          : disabled
            ? "text-weave-300 cursor-not-allowed"
            : "text-weave-600 hover:bg-weave-50"
      )}
    >
      {label}
    </button>
  );
}

function MacroTab({ macro }: { macro: MacroSnap }) {
  const tone =
    macro.regime === "growth"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : macro.regime === "risk_off"
        ? "border-red-200 bg-red-50 text-red-900"
        : "border-weave-100 bg-weave-50 text-weave-800";

  const vix = macro.vix ?? null;
  const spread = macro.yield_spread_10y3m ?? null;
  const fed = macro.fed_funds_rate ?? null;

  return (
    <div className={cn("rounded-lg border p-3 space-y-3", tone)}>
      <div>
        <p className="text-[10px] uppercase tracking-widest opacity-70">
          Regime · {macro.source ?? "unknown"}
        </p>
        <p className="mt-0.5 text-sm font-medium">
          {macro.regime === "growth"
            ? "Growth — risk-on"
            : macro.regime === "risk_off"
              ? "Risk-off — defensive"
              : "Neutral"}
        </p>
      </div>
      <div className="grid grid-cols-3 gap-1.5 text-xs">
        <Tile label="VIX" value={vix !== null ? vix.toFixed(1) : "—"} />
        <Tile
          label="10Y-3M"
          value={spread !== null ? `${spread >= 0 ? "+" : ""}${spread.toFixed(2)}%` : "—"}
        />
        <Tile label="Fed" value={fed !== null ? `${fed.toFixed(2)}%` : "—"} />
      </div>
      {macro.reason && (
        <p className="text-[10px] leading-relaxed opacity-80">{macro.reason}</p>
      )}
      {macro.attribution && (
        <p className="text-[10px] leading-relaxed opacity-60 pt-2 border-t border-current/10">
          {macro.attribution}
        </p>
      )}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-white/60 p-1.5">
      <p className="text-[9px] uppercase tracking-widest opacity-70">{label}</p>
      <p className="mt-0.5 font-mono text-xs font-medium">{value}</p>
    </div>
  );
}

function PulseTab({
  assets,
  summary
}: {
  assets: [string, Asset][];
  summary?: string;
}) {
  return (
    <div className="space-y-2">
      {assets.map(([key, a]) => {
        const up = a.change_5d_pct >= 0;
        return (
          <div
            key={key}
            className="rounded-md border border-weave-100 bg-weave-50/40 p-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[9px] uppercase tracking-widest text-weave-500">
                  {a.label}
                </p>
                <p className="font-mono text-[11px] text-weave-700 truncate">
                  {a.ticker} · ${a.price.toFixed(2)}
                </p>
              </div>
              <span
                className={cn(
                  "font-mono text-[11px] font-medium shrink-0",
                  up ? "text-emerald-700" : "text-red-700"
                )}
              >
                {up ? "+" : ""}
                {a.change_5d_pct}%
              </span>
            </div>
            <Spark points={a.sparkline} positive={up} />
          </div>
        );
      })}
      {summary && (
        <p className="text-[10px] text-weave-500 leading-relaxed pt-2 border-t border-weave-50">
          {summary}
        </p>
      )}
    </div>
  );
}

function CorrTab({
  corr,
  assets
}: {
  corr: Correlation[];
  assets: Record<string, Asset>;
}) {
  return (
    <div className="space-y-2">
      <p className="text-[10px] text-weave-500 leading-relaxed">
        +1.00 = lockstep · −1.00 = opposite · 0 = independent
      </p>
      {corr.map((c) => {
        const rho = c.rho;
        const tone =
          rho >= 0.3
            ? "text-emerald-700"
            : rho <= -0.3
              ? "text-treasure-700"
              : "text-weave-500";
        const aA = assets[c.a];
        const aB = assets[c.b];
        return (
          <div
            key={`${c.a}-${c.b}`}
            className="rounded-md border border-weave-100 bg-weave-50/40 p-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-[11px] font-medium text-weave-800 leading-tight">
                {c.a_label} vs {c.b_label}
              </p>
              <span className={cn("font-mono text-[11px] font-medium", tone)}>
                ρ {rho >= 0 ? "+" : ""}
                {rho}
              </span>
            </div>
            <p className="text-[10px] text-weave-500 leading-relaxed mt-1">
              {c.note}
            </p>
            {(aA || aB) && (
              <div className="grid grid-cols-2 gap-1 pt-1.5">
                {aA && <Spark points={aA.sparkline} positive={aA.change_5d_pct >= 0} compact />}
                {aB && <Spark points={aB.sparkline} positive={aB.change_5d_pct >= 0} compact />}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Spark({
  points,
  positive,
  compact = false
}: {
  points: number[];
  positive: boolean;
  compact?: boolean;
}) {
  if (!points || points.length < 2) {
    return <div className="h-6 rounded bg-weave-50/40" />;
  }
  const W = 200;
  const H = compact ? 16 : 22;
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
      className="w-full mt-1 rounded bg-white/60"
      style={{ height: H }}
      role="img"
      aria-label="Recent price"
    >
      <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.5} />
    </svg>
  );
}
