"use client";

import { useEffect, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type Mode = "manual" | "split";
type Posture = "aggressive" | "balanced" | "conservative";

const AI_PRESETS: Record<Posture, [number, number, number]> = {
  // [stock %, crypto %, options %]
  aggressive: [50, 30, 20],
  balanced: [70, 15, 15],
  conservative: [85, 10, 5]
};

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

/**
 * Capital allocator. Two ways to express the same thing — the form
 * still submits stock_capital_usd / crypto_capital_usd / options_capital_usd
 * via hidden inputs, so the existing save action keeps working.
 *
 *   - "Match Alpaca + split"  — uses the live broker equity as the
 *     total, splits it by percentage (manually or via the AI presets).
 *   - "Manual dollars"        — the original behaviour for users who
 *     prefer to type the exact amounts.
 *
 * `liveEquity` is the connected Alpaca account's equity (paper or live),
 * or null when nothing is connected. The "Sync to Alpaca" button is
 * only enabled when liveEquity is a positive number.
 */
export function CapitalAllocator({
  initialStock,
  initialCrypto,
  initialOptions,
  liveEquity,
  liveLabel
}: {
  initialStock: number;
  initialCrypto: number;
  initialOptions: number;
  liveEquity: number | null;
  liveLabel?: string;
}) {
  const initialTotal = Math.max(
    0,
    initialStock + initialCrypto + initialOptions
  );
  const initialMode: Mode =
    initialTotal > 0 ? "split" : "manual";

  const [mode, setMode] = useState<Mode>(initialMode);
  const [total, setTotal] = useState<number>(initialTotal || (liveEquity ?? 10000));
  const [stockPct, setStockPct] = useState<number>(
    initialTotal > 0 ? Math.round((initialStock / initialTotal) * 100) : 70
  );
  const [cryptoPct, setCryptoPct] = useState<number>(
    initialTotal > 0 ? Math.round((initialCrypto / initialTotal) * 100) : 15
  );
  const [optionsPct, setOptionsPct] = useState<number>(
    initialTotal > 0 ? Math.round((initialOptions / initialTotal) * 100) : 15
  );
  const [stockUsd, setStockUsd] = useState<number>(initialStock || 0);
  const [cryptoUsd, setCryptoUsd] = useState<number>(initialCrypto || 0);
  const [optionsUsd, setOptionsUsd] = useState<number>(initialOptions || 0);

  const sumPct = stockPct + cryptoPct + optionsPct;
  const pctOk = sumPct === 100;

  // Compute the dollar splits whenever the percentages or total change.
  const split = useMemo(() => {
    const t = Math.max(0, total);
    if (sumPct === 0)
      return { stock: 0, crypto: 0, options: 0 };
    return {
      stock: Math.round((t * stockPct) / 100),
      crypto: Math.round((t * cryptoPct) / 100),
      options: Math.round((t * optionsPct) / 100)
    };
  }, [total, stockPct, cryptoPct, optionsPct, sumPct]);

  // The hidden inputs the form save action reads — populated by either
  // the split (when mode=split) or the manual dollar fields.
  const submittedStock =
    mode === "split" ? split.stock : Math.max(0, stockUsd);
  const submittedCrypto =
    mode === "split" ? split.crypto : Math.max(0, cryptoUsd);
  const submittedOptions =
    mode === "split" ? split.options : Math.max(0, optionsUsd);

  function applyPreset(p: Posture) {
    const [s, c, o] = AI_PRESETS[p];
    setStockPct(s);
    setCryptoPct(c);
    setOptionsPct(o);
  }

  function syncTotalToAlpaca() {
    if (liveEquity && liveEquity > 0) setTotal(Math.round(liveEquity));
  }

  // Keep the dollar fields in sync if user enters them in manual mode
  // and then flips to split — easier mental model.
  useEffect(() => {
    if (mode === "manual") return;
    // nothing — split mode is computed
  }, [mode]);

  return (
    <section className="space-y-4">
      <h2 className="font-medium text-weave-800">Capital</h2>

      {/* Live-account banner */}
      {liveEquity && liveEquity > 0 ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 leading-relaxed">
          {liveLabel ?? "Connected account"} equity:{" "}
          <span className="font-mono font-medium">{usd(liveEquity)}</span>.{" "}
          <button
            type="button"
            onClick={syncTotalToAlpaca}
            className="underline hover:no-underline"
          >
            Sync the Total below to this →
          </button>
        </div>
      ) : (
        <p className="text-sm text-weave-500 leading-relaxed">
          Connect Alpaca on{" "}
          <a
            className="underline hover:text-weave-700"
            href="/dashboard/settings/connections"
          >
            Settings → Connections
          </a>{" "}
          to sync capital to your real account equity automatically.
        </p>
      )}

      {/* Mode toggle */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-weave-500">Allocate by:</span>
        {(
          [
            { id: "split" as Mode, label: "Total + split" },
            { id: "manual" as Mode, label: "Manual dollars" }
          ]
        ).map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => setMode(m.id)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs transition",
              mode === m.id
                ? "border-weave-400 bg-weave-50 text-weave-800"
                : "border-weave-200 text-weave-500 hover:bg-weave-50"
            )}
          >
            {m.label}
          </button>
        ))}
      </div>

      {mode === "split" ? (
        <div className="space-y-4">
          <div className="grid sm:grid-cols-3 gap-4">
            <div className="space-y-2 sm:col-span-1">
              <Label htmlFor="cap-total">Total capital (USD)</Label>
              <Input
                id="cap-total"
                type="number"
                min={0}
                step="100"
                value={total}
                onChange={(e) => setTotal(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label className="text-xs">
                AI presets — picks a split based on the user&apos;s typical posture
              </Label>
              <div className="flex flex-wrap gap-2">
                {(
                  ["aggressive", "balanced", "conservative"] as Posture[]
                ).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => applyPreset(p)}
                    className="rounded-md border border-weave-200 px-3 py-1.5 text-xs text-weave-700 hover:bg-weave-50 capitalize"
                  >
                    {p} — {AI_PRESETS[p][0]} / {AI_PRESETS[p][1]} / {AI_PRESETS[p][2]}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-weave-500">
                Aggressive tilts more toward crypto + options. Conservative
                stays mostly in stocks. Pick one and tweak the percentages
                below if you want to.
              </p>
            </div>
          </div>

          <div className="grid sm:grid-cols-3 gap-4">
            <SplitRow label="Stock %"   pct={stockPct}   usd={split.stock}   onChange={setStockPct} />
            <SplitRow label="Crypto %"  pct={cryptoPct}  usd={split.crypto}  onChange={setCryptoPct} />
            <SplitRow label="Options %" pct={optionsPct} usd={split.options} onChange={setOptionsPct} />
          </div>

          <p
            className={cn(
              "text-xs leading-relaxed",
              pctOk ? "text-weave-500" : "text-amber-700"
            )}
          >
            {pctOk
              ? `Sum is 100%. The bot will size positions against ${usd(total)} split as ${stockPct} / ${cryptoPct} / ${optionsPct}.`
              : `Sum is ${sumPct}% — adjust until it adds to 100%. Until then the form saves these proportionally.`}
          </p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-3 gap-4">
          <DollarField label="Stock (USD)"   value={stockUsd}   onChange={setStockUsd} />
          <DollarField label="Crypto (USD)"  value={cryptoUsd}  onChange={setCryptoUsd} />
          <DollarField label="Options (USD)" value={optionsUsd} onChange={setOptionsUsd} />
        </div>
      )}

      {/* Hidden inputs that the form save action actually reads. */}
      <input type="hidden" name="stock_capital_usd"   value={submittedStock} />
      <input type="hidden" name="crypto_capital_usd"  value={submittedCrypto} />
      <input type="hidden" name="options_capital_usd" value={submittedOptions} />

      <p className="text-xs text-weave-500 leading-relaxed">
        Sum of stock + options funds the paper-trading account&apos;s
        starting capital (only at first onboarding — changes here
        don&apos;t retroactively re-seed the paper account).
      </p>
    </section>
  );
}

function SplitRow({
  label,
  pct,
  usd,
  onChange
}: {
  label: string;
  pct: number;
  usd: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        min={0}
        max={100}
        step={1}
        value={pct}
        onChange={(e) => onChange(Math.max(0, Math.min(100, Number(e.target.value))))}
      />
      <p className="text-[11px] text-weave-500 font-mono">
        ≈ ${usd.toLocaleString()}
      </p>
    </div>
  );
}

function DollarField({
  label,
  value,
  onChange
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        min={0}
        step="0.01"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}
