"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const PRESETS = [1_000, 5_000, 10_000, 25_000, 100_000];

function fmt(v: number) {
  return v.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/**
 * Reset the paper account to a chosen starting equity. Lets the user
 * see how the agents behave at $1k vs $10k vs $100k without leaving
 * the dashboard — open positions are closed and YTD P&L is zeroed so
 * the new run is clean.
 *
 * When `brokerConnected` is true (per-user Alpaca OAuth or env keys
 * present), the reset surface is hidden entirely. The broker is the
 * source of truth for cash and YTD P&L; resetting Trezo's internal
 * book would create modeled/broker drift the reconciler then has to
 * untangle. A short note replaces the form so the user knows why
 * it's gone. Mike 2026-06-01.
 */
export function AccountSizeSim({
  brokerConnected = false,
}: {
  brokerConnected?: boolean;
} = {}) {
  if (brokerConnected) {
    return (
      <section className="rounded-xl border border-weave-100 bg-weave-50/40 p-4 text-xs text-weave-600 leading-relaxed">
        <p className="font-medium text-weave-800 mb-0.5">
          Test the bot at a different account size
        </p>
        <p>
          Disabled while a broker is connected. The broker holds the
          real account; resetting Trezo&apos;s book here would drift
          from broker truth. To experiment with different account
          sizes, disconnect the broker on Settings → Connections
          first, or use Strategy Lab for backtesting at any equity.
        </p>
      </section>
    );
  }

  const router = useRouter();
  const [picked, setPicked] = useState<number>(10_000);
  const [custom, setCustom] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState<{ equity: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const target = (() => {
    const c = Number(custom);
    if (Number.isFinite(c) && c >= 100 && c <= 10_000_000) return c;
    return picked;
  })();

  async function doReset() {
    setRunning(true);
    setError(null);
    try {
      const r = await fetch("/api/paper/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ equity: target }),
      });
      const j = await r.json();
      if (!j.ok) {
        setError(j.error ?? "Reset failed.");
      } else {
        setDone({ equity: target });
        router.refresh();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setRunning(false);
      setConfirming(false);
    }
  }

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
      <div>
        <h2 className="font-medium text-weave-800">
          Test the bot at a different account size
        </h2>
        <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
          See how the agents adapt at $1k, $5k, $10k, $25k, or $100k.
          Resetting closes every open paper position and zeroes YTD
          P&amp;L so the new run starts clean. The posture map
          (growth / balanced / income) picks itself based on the new
          equity.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 items-end">
        {PRESETS.map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => {
              setPicked(v);
              setCustom("");
            }}
            className={cn(
              "rounded border px-3 py-1.5 text-xs",
              picked === v && !custom
                ? "border-weave-600 bg-weave-50 text-weave-800"
                : "border-weave-200 text-weave-600 hover:bg-weave-50"
            )}
          >
            {fmt(v)}
          </button>
        ))}
        <div className="flex flex-col gap-1">
          <Label htmlFor="custom" className="text-[11px] text-weave-500">
            Custom amount (USD)
          </Label>
          <Input
            id="custom"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="e.g. 7500"
            className="h-8 w-32 text-sm"
          />
        </div>
        <p className="pb-2 text-sm text-weave-600">
          Target:{" "}
          <span className="font-mono font-medium text-weave-800">
            {fmt(target)}
          </span>
        </p>
      </div>

      {confirming ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 space-y-2">
          <p>
            This will close every open paper position and reset YTD
            P&amp;L to zero. The new run starts at {fmt(target)}.
            Confirm?
          </p>
          <div className="flex gap-2">
            <Button onClick={doReset} disabled={running}>
              {running ? "Resetting..." : `Yes, reset to ${fmt(target)}`}
            </Button>
            <Button
              variant="outline"
              onClick={() => setConfirming(false)}
              disabled={running}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button onClick={() => setConfirming(true)} disabled={running}>
          Reset paper account to {fmt(target)}
        </Button>
      )}

      {done ? (
        <p className="text-xs text-emerald-700">
          Paper account reset to {fmt(done.equity)}. Dashboard refreshed.
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-red-700">{error}</p>
      ) : null}
    </section>
  );
}
