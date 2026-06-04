"use client";

import { useState, useTransition } from "react";

/**
 * OptionsTrimButton — small inline button on options Exit Advisor
 * alerts. Posts to /api/paper/options/positions/[id]/trim to close
 * a fraction of the options position.
 *
 * V1 default: close half the contracts (rounded down, min 1). For
 * positions with 1 contract, this is the same as a full close — the
 * server-side handles the rollover.
 *
 * Task #29, 2026-06-02. UI matches the stock TrimDialog visual
 * language: weave outline button, expands to inline confirmation.
 */
export function OptionsTrimButton({
  positionId,
  currentContracts,
}: {
  positionId: string;
  currentContracts?: number | null;
}) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const total = Math.max(1, Math.floor(Number(currentContracts ?? 1)));
  const [n, setN] = useState<number>(Math.max(1, Math.floor(total / 2)));

  async function submit() {
    setError(null);
    setDone(null);
    startTransition(async () => {
      try {
        const r = await fetch(
          `/api/paper/options/positions/${positionId}/trim`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              contracts_to_close: n,
              reason: "exit_advisor_trim",
            }),
          }
        );
        const data = await r.json();
        if (!r.ok || !data.ok) {
          setError(String(data.error ?? "Trim failed"));
          return;
        }
        const realized = data.realized_pnl_usd ?? 0;
        setDone(
          `Closed ${data.contracts_closed} contract(s) for ` +
            `$${Number(realized).toFixed(0)} realized. ` +
            (data.full_close
              ? "Position fully closed."
              : `${data.contracts_remaining} contract(s) remain.`)
        );
        // Reload after a beat so the alert disappears (dismiss is
        // separate, but the underlying alert may stop re-firing).
        setTimeout(() => window.location.reload(), 1400);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Network error");
      }
    });
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[11px] rounded border border-current/30 px-2 py-0.5 hover:bg-current/10"
      >
        Trim ▾
      </button>
    );
  }

  return (
    <div className="flex items-baseline gap-2 text-[11px]">
      <label className="opacity-80">
        Close{" "}
        <input
          type="number"
          min={1}
          max={total}
          step={1}
          value={n}
          onChange={(e) =>
            setN(
              Math.max(1, Math.min(total, Math.floor(Number(e.target.value) || 1)))
            )
          }
          className="w-12 rounded border border-current/30 bg-transparent px-1 py-0.5 font-mono text-center"
        />{" "}
        of {total}
      </label>
      <button
        type="button"
        onClick={submit}
        disabled={pending}
        className="rounded bg-current/20 px-2 py-0.5 hover:bg-current/30 disabled:opacity-50"
      >
        {pending ? "…" : "Apply"}
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="opacity-60 hover:opacity-100 underline"
      >
        Cancel
      </button>
      {error ? <span className="text-red-700">⚠ {error}</span> : null}
      {done ? <span className="text-emerald-700">✓ {done}</span> : null}
    </div>
  );
}
