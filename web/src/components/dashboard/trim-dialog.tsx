"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type Preview = {
  fraction: number;
  slice_qty: number;
  remaining_qty: number;
  proceeds_usd: number;
  slice_pnl_usd: number;
};

type PreviewResponse = {
  ok: boolean;
  ticker?: string;
  asset_type?: string;
  side?: string;
  quantity?: number;
  entry_price?: number;
  current_price?: number;
  cost_basis_fraction?: number | null;
  recommended_fraction?: number | null;
  recommendation_kind?: string | null;
  presets?: {
    quarter?: Preview;
    half?: Preview;
    three_quarter?: Preview;
    cost_basis?: Preview | null;
  };
  error?: string;
};

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/**
 * TrimDialog - expandable inline panel replacing the simple "Trim 50%"
 * button on decayed_thesis alerts. Mike 2026-06-01:
 *
 *   - Four preset buttons: 25% / 50% / 75% / Cost-basis
 *     ("recover what was invested - everything left is profit")
 *   - A slider 5%-95% for any custom fraction
 *   - Live preview: shares to sell, proceeds, slice P&L, remaining
 *   - The bot's recommended fraction is highlighted with a small star
 *   - Apply button calls the trim API; refreshes on success
 *
 * "Cost-basis" is the house-money point: sell enough shares that the
 * proceeds equal your original cost, so the remaining position is
 * effectively free. Available only when the position is in profit.
 */
export function TrimDialog({ positionId }: { positionId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fraction, setFraction] = useState<number>(0.5);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Lazy load the preview when the user opens the dialog.
  useEffect(() => {
    if (!open || preview) return;
    setLoading(true);
    fetch(`/api/paper/positions/${positionId}/trim-preview`, { cache: "no-store" })
      .then((r) => r.json())
      .then((data: PreviewResponse) => {
        setPreview(data);
        if (data.ok) {
          // Default to bot recommendation if present, else 50%.
          const f =
            data.recommended_fraction ??
            data.cost_basis_fraction ??
            0.5;
          setFraction(f);
        }
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [open, positionId, preview]);

  async function apply() {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`/api/paper/positions/${positionId}/trim`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fraction,
          reason: "decayed_thesis_trim",
        }),
      });
      const j = await r.json();
      if (!j.ok) {
        setErr(j.error || "Trim failed");
      } else {
        setOpen(false);
        router.refresh();
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[11px] rounded-md border border-current px-2 py-0.5 opacity-90 hover:opacity-100"
        title="Open trim controls"
      >
        Trim ▾
      </button>
    );
  }

  // Compute live preview from current fraction client-side using the
  // backend's snapshot - avoids a fetch on every slider tick.
  let livePreview: Preview | null = null;
  if (preview?.ok && preview.quantity && preview.current_price && preview.entry_price) {
    const isCrypto = preview.asset_type === "crypto";
    const rawSlice = preview.quantity * fraction;
    const sliceQty = isCrypto ? rawSlice : Math.floor(rawSlice);
    const proceeds = sliceQty * preview.current_price;
    const slicePnl =
      preview.side === "short"
        ? sliceQty * (preview.entry_price - preview.current_price)
        : sliceQty * (preview.current_price - preview.entry_price);
    livePreview = {
      fraction,
      slice_qty: sliceQty,
      remaining_qty: preview.quantity - sliceQty,
      proceeds_usd: Math.round(proceeds * 100) / 100,
      slice_pnl_usd: Math.round(slicePnl * 100) / 100,
    };
  }

  const presets = preview?.presets ?? {};
  const recommended = preview?.recommended_fraction ?? null;

  return (
    <div className="rounded-lg border border-current/40 bg-white p-3 mt-2 space-y-3 text-weave-900 min-w-[280px]">
      <div className="flex items-baseline justify-between">
        <p className="text-[11px] uppercase tracking-widest text-weave-500">
          Trim {preview?.ticker ?? ""}
        </p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-[11px] text-weave-500 hover:text-weave-800"
        >
          Cancel
        </button>
      </div>

      {loading ? (
        <p className="text-xs text-weave-500">Loading preview...</p>
      ) : !preview?.ok ? (
        <p className="text-xs text-red-700">{preview?.error || err || "Failed to load."}</p>
      ) : (
        <>
          {/* Preset buttons */}
          <div className="flex flex-wrap gap-1.5 text-xs">
            <PresetButton
              label="25%"
              f={0.25}
              active={Math.abs(fraction - 0.25) < 0.01}
              isRecommended={recommended === 0.25}
              onClick={() => setFraction(0.25)}
            />
            <PresetButton
              label="50%"
              f={0.5}
              active={Math.abs(fraction - 0.5) < 0.01}
              isRecommended={recommended === 0.5}
              onClick={() => setFraction(0.5)}
            />
            <PresetButton
              label="75%"
              f={0.75}
              active={Math.abs(fraction - 0.75) < 0.01}
              isRecommended={recommended === 0.75}
              onClick={() => setFraction(0.75)}
            />
            {presets.cost_basis ? (
              <PresetButton
                label={`Cost-basis (${Math.round((presets.cost_basis.fraction ?? 0) * 100)}%)`}
                f={presets.cost_basis.fraction}
                active={
                  Math.abs(fraction - presets.cost_basis.fraction) < 0.01
                }
                isRecommended={recommended === presets.cost_basis.fraction}
                onClick={() => setFraction(presets.cost_basis!.fraction)}
                title="Sell enough to recover what was invested. What's left is pure profit (house money)."
              />
            ) : null}
          </div>

          {/* Slider */}
          <div className="space-y-1">
            <div className="flex items-baseline justify-between text-[11px] text-weave-500">
              <span>Custom</span>
              <span className="font-mono text-weave-800">
                {(fraction * 100).toFixed(0)}%
              </span>
            </div>
            <input
              type="range"
              min={5}
              max={95}
              step={1}
              value={Math.round(fraction * 100)}
              onChange={(e) => setFraction(Number(e.target.value) / 100)}
              className="w-full accent-treasure-600"
            />
          </div>

          {/* Live preview */}
          {livePreview ? (
            <div className="rounded border border-weave-100 bg-weave-50/40 p-2 text-[11px] font-mono space-y-0.5">
              <div className="flex items-baseline justify-between">
                <span className="text-weave-500">Sell</span>
                <span className="text-weave-800">
                  {livePreview.slice_qty} {preview.asset_type === "crypto" ? "" : "shares"}
                </span>
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-weave-500">Proceeds</span>
                <span className="text-weave-800">{usd(livePreview.proceeds_usd)}</span>
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-weave-500">Slice P&amp;L</span>
                <span
                  className={
                    livePreview.slice_pnl_usd >= 0
                      ? "text-emerald-700"
                      : "text-red-700"
                  }
                >
                  {usd(livePreview.slice_pnl_usd)}
                </span>
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-weave-500">Remaining</span>
                <span className="text-weave-800">
                  {livePreview.remaining_qty} {preview.asset_type === "crypto" ? "" : "shares"}
                </span>
              </div>
            </div>
          ) : null}

          {recommended !== null && Math.abs(fraction - recommended) > 0.01 ? (
            <p className="text-[10px] text-weave-500 italic">
              Bot suggests {Math.round(recommended * 100)}% for this
              position&apos;s decay pattern.
            </p>
          ) : null}

          {err ? <p className="text-[11px] text-red-700">{err}</p> : null}

          <button
            type="button"
            onClick={apply}
            disabled={busy}
            className="w-full rounded-md bg-treasure-600 hover:bg-treasure-700 text-white px-3 py-1.5 text-xs font-medium disabled:opacity-50"
          >
            {busy
              ? "Trimming..."
              : `Trim ${Math.round(fraction * 100)}% now`}
          </button>
        </>
      )}
    </div>
  );
}

function PresetButton({
  label,
  active,
  isRecommended,
  onClick,
  title,
}: {
  label: string;
  f: number;
  active: boolean;
  isRecommended: boolean;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={
        "rounded-full px-2.5 py-0.5 border transition " +
        (active
          ? "border-treasure-600 bg-treasure-600 text-white"
          : "border-weave-200 bg-white text-weave-700 hover:bg-weave-50")
      }
    >
      {isRecommended ? <span className="mr-1">★</span> : null}
      {label}
    </button>
  );
}
