import { cn } from "@/lib/utils";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type Snap = {
  configured: boolean;
  level?: number;
  description?: string;
  wheel_ready?: boolean;
  note?: string;
};

/**
 * Surfaces the user's Alpaca options trading approval level so the
 * Dividend Wheel + Live Trading pages can say plainly whether the
 * bot can route real options orders yet. Approval lives on Alpaca's
 * side — the user has to apply there — so this card explains what
 * level is needed and what each level enables.
 */
export async function OptionsApprovalCard() {
  let snap: Snap | null = null;
  try {
    const r = await fetch(`${AGENTS_BASE}/account/options-approval`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    if (r.ok) snap = (await r.json()) as Snap;
  } catch {
    snap = null;
  }
  if (!snap) return null;

  if (!snap.configured) {
    return (
      <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-4 text-sm text-weave-600">
        <p className="font-medium text-weave-800">
          Options approval — Alpaca not connected
        </p>
        <p className="beginner-only mt-1 leading-relaxed">
          Connect Alpaca on Settings → Connections (or set the env
          keys) to read your options trading approval level. The Wheel
          needs at least Level 1.
        </p>
      </div>
    );
  }

  const level = snap.level ?? 0;
  const ready = !!snap.wheel_ready;

  return (
    <div
      className={cn(
        "rounded-xl border p-4 space-y-1.5",
        ready
          ? "border-emerald-200 bg-emerald-50/60"
          : "border-amber-200 bg-amber-50/60"
      )}
    >
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <p className="font-medium text-weave-800">
          Options approval · Level {level}
        </p>
        <span
          className={cn(
            "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
            ready
              ? "bg-emerald-100 text-emerald-800"
              : "bg-amber-100 text-amber-800"
          )}
        >
          {ready ? "Wheel ready" : "Not approved yet"}
        </span>
      </div>
      <p className="text-sm text-weave-700 leading-relaxed">
        {snap.description}
      </p>
      <p className="beginner-only text-xs text-weave-500 leading-relaxed">
        Approval is granted by Alpaca, not Trezo. Apply from your
        Alpaca dashboard → Account → Options to lift your level.{" "}
        Level 1 covers cash-secured puts and covered calls (the
        Wheel). Level 2 adds long calls/puts and simple spreads.
        Level 3 is uncovered + advanced multi-leg.
      </p>
    </div>
  );
}
