import Link from "next/link";
import { cn } from "@/lib/utils";
import { fetchAlpacaSnapshot } from "@/lib/alpaca-snapshot";

/**
 * Options approval badge — reads the user's CURRENT approved level
 * straight from the Alpaca account snapshot (same source the rest of
 * the dashboard uses), so it stays in sync. Levels:
 *   0 = none, 1 = covered (CSP + CC), 2 = long + spreads, 3 = uncovered.
 * Mike has Level 3 — anywhere that hardcodes "Level 0 NOT APPROVED" is
 * stale UI; switch to this component.
 */
export async function OptionsApprovalBadge() {
  const snap = await fetchAlpacaSnapshot();
  if (!snap || !snap.configured || !snap.account) return null;
  const level = snap.account.options_approved_level ?? 0;
  const labels = [
    "Not approved",
    "Level 1 · covered (CSP + CC)",
    "Level 2 · long + spreads",
    "Level 3 · uncovered"
  ];
  const ok = level >= 1;
  return (
    <div
      className={cn(
        "rounded-xl border p-4 flex items-center justify-between gap-3 flex-wrap",
        ok ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"
      )}
    >
      <div>
        <p className={cn("text-sm font-medium", ok ? "text-emerald-900" : "text-amber-900")}>
          Alpaca options approval — {labels[Math.max(0, Math.min(3, level))]}
        </p>
        <p className={cn("text-xs mt-0.5", ok ? "text-emerald-800/80" : "text-amber-900/80")}>
          {ok
            ? "Options orders (CSP + CC and beyond per your level) can route to the broker."
            : "Apply on Alpaca (Account → Configure → Options trading). Level 1 unlocks the Wheel."}
        </p>
      </div>
      <span className={cn("text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5", ok ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800")}>
        {ok ? "Approved" : "Not eligible"}
      </span>
    </div>
  );
}
