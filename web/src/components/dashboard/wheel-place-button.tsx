"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

type Leg = "csp" | "cc";

type PlaceResp = {
  ok: boolean;
  error?: string;
  routed?: string;
  occ?: string;
  alpaca_order_id?: string;
  alpaca_order_status?: string;
  // From /api/wheel/place-leg: did Trezo also log the leg into
  // options_positions for the modeled planner?
  recorded?: boolean;
  record_error?: string;
};

/**
 * Per-row "Place" button on the Wheel page's live pricing table.
 * One click → confirm prompt → POSTs to /api/wheel/place-leg, which
 * lands a real Alpaca paper sell-to-open AND logs it into Trezo's
 * options_positions so the modeled Wheel planner stays in sync.
 *
 * The result text replaces the button so the table doesn't shift.
 */
export function WheelPlaceButton({
  leg,
  underlying,
  targetStrike,
  targetExp,
  premium
}: {
  leg: Leg;
  underlying: string;
  targetStrike: number;
  targetExp: string;
  premium?: number;
}) {
  const router = useRouter();
  const [stage, setStage] = useState<"idle" | "confirm" | "sending" | "done" | "error">("idle");
  const [reply, setReply] = useState<PlaceResp | null>(null);
  const [contracts] = useState(1);

  async function send() {
    setStage("sending");
    try {
      const r = await fetch("/api/wheel/place-leg", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          leg,
          underlying,
          target_strike: targetStrike,
          target_exp: targetExp,
          contracts,
          limit_price: premium && premium > 0 ? Number(premium.toFixed(2)) : undefined
        })
      });
      const j = (await r.json()) as PlaceResp;
      setReply(j);
      setStage(j.ok ? "done" : "error");
      if (j.ok) router.refresh();
    } catch (e) {
      setReply({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  if (stage === "done" && reply?.ok) {
    const statusBit = reply.alpaca_order_status ? ` · ${reply.alpaca_order_status}` : "";
    const recordBit = reply.recorded
      ? " · logged"
      : reply.record_error
      ? " · log failed"
      : "";
    const tooltip = [
      reply.occ ? `OCC ${reply.occ}` : null,
      reply.alpaca_order_id ? `Alpaca order ${reply.alpaca_order_id}` : null,
      reply.recorded
        ? "Recorded in Trezo planner"
        : reply.record_error
        ? `Planner log failed: ${reply.record_error}`
        : null
    ]
      .filter(Boolean)
      .join(" · ");
    return (
      <span className="text-[11px] text-emerald-700 font-medium" title={tooltip || undefined}>
        ✓ Placed{statusBit}
        {recordBit}
      </span>
    );
  }
  if (stage === "error") {
    return (
      <span
        className="text-[11px] text-red-700 font-medium cursor-help"
        title={reply?.error ?? "Order rejected"}
      >
        ✗ Failed
      </span>
    );
  }
  if (stage === "sending") {
    return <span className="text-[11px] text-weave-500">Placing…</span>;
  }
  if (stage === "confirm") {
    return (
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={send}
          className="rounded-md bg-weave-600 px-2 py-0.5 text-[11px] font-medium text-treasure-50 hover:bg-weave-700"
        >
          Confirm
        </button>
        <button
          type="button"
          onClick={() => setStage("idle")}
          className="rounded-md border border-weave-200 px-2 py-0.5 text-[11px] text-weave-600 hover:bg-weave-50"
        >
          Cancel
        </button>
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setStage("confirm")}
      className={cn(
        "rounded-md border px-2 py-0.5 text-[11px] font-medium transition",
        leg === "csp"
          ? "border-weave-300 text-weave-700 hover:bg-weave-50"
          : "border-treasure-300 text-treasure-700 hover:bg-treasure-50"
      )}
      title={
        leg === "csp"
          ? "Sell to open: short put at this strike + expiration. Also logged into Trezo's planner."
          : "Sell to open: covered call at this strike + expiration. Also logged into Trezo's planner."
      }
    >
      Place {leg.toUpperCase()}
    </button>
  );
}
