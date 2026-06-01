"use client";

import { useEffect, useState } from "react";
import { TcsBadge } from "@/components/widgets/tcs-badge";
import { MiniChart } from "@/components/widgets/mini-chart";
import { cn } from "@/lib/utils";
import { patternInfo, factorLabel, factorInfo } from "@/lib/pattern-glossary";

type Bar = { o: number; h: number; l: number; c: number };

type Scan = {
  ticker: string;
  asset_type: string;
  score: number;
  tcs: number;
  dominant_pattern: string | null;
  direction: "bullish" | "bearish" | "neutral";
  detected_patterns: string[];
  breakdown: Record<string, number>;
  candle_count: number;
  confluence: { bonus: number; shared_patterns: { pattern: string; timeframes: string[] }[] };
  candles: Bar[];
};

type State = { status: "idle" | "loading" | "ok" | "error"; scan?: Scan; error?: string };
type Level = "beginner" | "standard" | "expert";

const LEVELS: { id: Level; label: string; hint: string }[] = [
  { id: "beginner", label: "Learning", hint: "Full explanations on every pattern and score factor" },
  { id: "standard", label: "Standard", hint: "Patterns and the score, balanced detail" },
  { id: "expert", label: "Pro", hint: "Just the signal — ticker, score, chart" }
];

export function PatternsBoard({ symbols }: { symbols: string[] }) {
  const [scans, setScans] = useState<Record<string, State>>(() =>
    Object.fromEntries(symbols.map((s) => [s, { status: "idle" }]))
  );
  const [level, setLevel] = useState<Level>("standard");
  const [openCard, setOpenCard] = useState<string | null>(null);

  useEffect(() => {
    try {
      const v = localStorage.getItem("trezo_pattern_detail");
      if (v === "beginner" || v === "standard" || v === "expert") setLevel(v);
    } catch {
      /* ignore */
    }
  }, []);

  function pickLevel(l: Level) {
    setLevel(l);
    try {
      localStorage.setItem("trezo_pattern_detail", l);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function scanOne(symbol: string) {
      setScans((p) => ({ ...p, [symbol]: { status: "loading" } }));
      try {
        const r = await fetch(`/api/patterns/${encodeURIComponent(symbol)}`);
        if (cancelled) return;
        if (!r.ok) {
          const j = await r.json();
          setScans((p) => ({ ...p, [symbol]: { status: "error", error: j.error ?? `HTTP ${r.status}` } }));
          return;
        }
        const j = (await r.json()) as Scan;
        setScans((p) => ({ ...p, [symbol]: { status: "ok", scan: j } }));
      } catch (e) {
        if (!cancelled) {
          setScans((p) => ({
            ...p,
            [symbol]: { status: "error", error: e instanceof Error ? e.message : "fetch failed" }
          }));
        }
      }
    }

    (async () => {
      for (const s of symbols) {
        if (cancelled) break;
        await scanOne(s);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [symbols]);

  if (symbols.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-600">
        Your default watchlist is empty.
      </div>
    );
  }

  const ordered = [...symbols].sort((a, b) => {
    const sa = scans[a]?.scan?.tcs ?? -1;
    const sb = scans[b]?.scan?.tcs ?? -1;
    return sb - sa;
  });
  const done = ordered.filter((s) => scans[s]?.status === "ok").length;

  return (
    <div className="space-y-3">
      {/* Detail level — beginners see explanations, pros see just the signal */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-weave-500">Detail level:</span>
        {LEVELS.map((l) => (
          <button
            key={l.id}
            type="button"
            onClick={() => pickLevel(l.id)}
            title={l.hint}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs transition",
              level === l.id
                ? "border-weave-400 bg-weave-50 text-weave-800"
                : "border-weave-200 text-weave-500 hover:bg-weave-50"
            )}
          >
            {l.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-weave-500">
        {done} of {symbols.length} scanned · sorted by Trade Confidence Score · tap a card for the full breakdown
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {ordered.map((sym) => (
          <PatternCard
            key={sym}
            symbol={sym}
            state={scans[sym]}
            level={level}
            open={openCard === sym}
            onToggle={() => setOpenCard(openCard === sym ? null : sym)}
          />
        ))}
      </div>
    </div>
  );
}

function PatternCard({
  symbol,
  state,
  level,
  open,
  onToggle
}: {
  symbol: string;
  state: State;
  level: Level;
  open: boolean;
  onToggle: () => void;
}) {
  if (state.status === "loading" || state.status === "idle") {
    return (
      <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-mono font-medium text-weave-800">{symbol}</span>
          <span className="text-xs text-weave-400">Scanning…</span>
        </div>
        <div className="h-[76px] rounded-lg border border-weave-100 bg-weave-50/40 animate-pulse" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-mono font-medium text-weave-800">{symbol}</span>
          <span className="text-xs text-amber-700" title={state.error}>
            No data
          </span>
        </div>
        <div className="flex h-[76px] items-center justify-center rounded-lg border border-dashed border-weave-200 bg-weave-50/40 text-[11px] text-weave-400">
          Could not reach price data
        </div>
      </div>
    );
  }

  const s = state.scan!;
  const arrow = s.direction === "bullish" ? "▲" : s.direction === "bearish" ? "▼" : "•";
  const dirClass =
    s.direction === "bullish"
      ? "text-emerald-600"
      : s.direction === "bearish"
        ? "text-red-500"
        : "text-weave-400";
  const breakdown = Object.entries(s.breakdown ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
      {/* Header — click to expand the full breakdown */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full text-left"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono font-medium text-weave-800">{symbol}</span>
              <span className={cn("text-sm", dirClass)}>{arrow}</span>
              <span className={cn("text-xs capitalize", dirClass)}>{s.direction}</span>
            </div>
            <p
              className="mt-0.5 text-xs text-weave-500 truncate"
              title={s.dominant_pattern ? patternInfo(s.dominant_pattern) : undefined}
            >
              {s.dominant_pattern
                ? s.dominant_pattern.replace(/_/g, " ")
                : "No dominant pattern"}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <TcsBadge tcs={s.tcs} label="TCS" />
            <svg
              className={cn(
                "h-4 w-4 text-weave-400 transition-transform",
                open && "rotate-180"
              )}
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>
      </button>

      <MiniChart
        candles={s.candles ?? []}
        highlightLast={s.dominant_pattern ? 3 : 0}
      />

      {/* Learning mode — explain the dominant pattern inline */}
      {level === "beginner" && s.dominant_pattern && (
        <p className="text-xs text-weave-500 leading-relaxed">
          {patternInfo(s.dominant_pattern)}
        </p>
      )}

      {/* Detected pattern tags — hidden in Pro, hover for an explanation */}
      {level !== "expert" && s.detected_patterns.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {s.detected_patterns.map((p) => (
            <span
              key={p}
              title={patternInfo(p)}
              className="cursor-help text-[10px] uppercase tracking-widest rounded-full bg-weave-50 text-weave-600 px-2 py-0.5"
            >
              {p.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {level !== "expert" && s.confluence?.bonus > 0 && (
        <p className="text-[11px] text-treasure-700">
          Confluence bonus +{s.confluence.bonus}
        </p>
      )}

      {/* Expanded — the full score breakdown */}
      {open && (
        <div className="border-t border-weave-50 pt-3 space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-weave-500">
            Score breakdown — {s.score} of 1000
          </p>
          {breakdown.length === 0 && (
            <p className="text-xs text-weave-400">No factor detail for this scan.</p>
          )}
          {breakdown.map(([k, v]) => (
            <div key={k}>
              <div className="flex items-baseline justify-between gap-3 text-xs">
                <span
                  className="cursor-help text-weave-600"
                  title={factorInfo(k)}
                >
                  {factorLabel(k)}
                </span>
                <span className="font-mono text-weave-700">{Math.round(Number(v))}</span>
              </div>
              {level === "beginner" && (
                <p className="mt-0.5 text-[11px] text-weave-400 leading-relaxed">
                  {factorInfo(k)}
                </p>
              )}
            </div>
          ))}
          {s.confluence?.shared_patterns?.length > 0 && (
            <p className="text-[11px] text-weave-500 leading-relaxed">
              Confluence:{" "}
              {s.confluence.shared_patterns
                .map((sp) => `${sp.pattern.replace(/_/g, " ")} on ${sp.timeframes.length} frames`)
                .join("; ")}
              .
            </p>
          )}
          <a
            href="/dashboard/stocks"
            className="inline-block text-[11px] text-weave-600 underline hover:text-weave-800"
          >
            View {symbol} quote →
          </a>
        </div>
      )}
    </div>
  );
}
