"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

type Adjustment = {
  id: string;
  action: string;
  scope: string;
  reason: string;
  trigger?: string;
  severity: "low" | "medium" | "high";
  status: string;
  created_at: string;
};

type Resp = { rows?: Adjustment[]; error?: string };

const SEEN_KEY = "trezo.regime.lastSeenId";
// Content fingerprint — `action|scope` — captures the actual signal
// instead of the row id, so re-emits of the same regime flip stay
// dismissed. Cleared automatically when action or scope changes.
const SEEN_SIG_KEY = "trezo.regime.lastSeenSignature";

function signatureOf(row: Adjustment): string {
  return `${row.action || ""}|${row.scope || ""}`;
}

/**
 * Regime-change popup banner.
 *
 * Mike asked: when Strategy Engine flips scope (regime change, ticker
 * flag, pause a strategy), it should NOT be buried in the activity feed.
 * This client banner polls /api/admin/scope-adjustments every 30s and
 * pops up a sticky notice for an APPLIED change the user hasn't seen
 * yet. Dismissal is keyed on a content signature (action+scope) so the
 * Strategy Engine re-emitting the same posture every tick doesn't make
 * the banner reappear over and over — only a genuinely new regime
 * surface does.
 */
export function RegimeAlertBanner() {
  const [latest, setLatest] = useState<Adjustment | null>(null);
  const [dismissed, setDismissed] = useState(false);

  async function fetchLatest() {
    try {
      const r = await fetch("/api/admin/scope-adjustments?limit=1", { cache: "no-store" });
      const j = (await r.json()) as Resp;
      const row = (j.rows && j.rows[0]) || null;
      if (!row) return;
      if (typeof window === "undefined") return;
      const lastSeenSig = window.localStorage.getItem(SEEN_SIG_KEY);
      const lastSeenId = window.localStorage.getItem(SEEN_KEY);
      const sig = signatureOf(row);
      // Suppress if the underlying signal (action+scope) is identical
      // to what the user already dismissed. Fall back to id match for
      // first-load compatibility with the older storage key.
      if (sig === lastSeenSig) return;
      if (row.id === lastSeenId) return;
      setLatest(row);
      setDismissed(false);
    } catch {
      // silent
    }
  }

  useEffect(() => {
    fetchLatest();
    const t = setInterval(fetchLatest, 30_000);
    return () => clearInterval(t);
  }, []);

  if (!latest || dismissed) return null;

  function dismiss() {
    if (latest && typeof window !== "undefined") {
      window.localStorage.setItem(SEEN_KEY, latest.id);
      window.localStorage.setItem(SEEN_SIG_KEY, signatureOf(latest));
    }
    setDismissed(true);
  }

  const sev = latest.severity || "low";
  const toneClass =
    sev === "high"
      ? "border-red-300 bg-red-50 text-red-900"
      : sev === "medium"
      ? "border-amber-300 bg-amber-50 text-amber-900"
      : "border-weave-300 bg-treasure-50 text-weave-800";

  return (
    <div
      className={cn(
        "fixed inset-x-4 top-4 z-50 rounded-xl border shadow-lg p-3 sm:p-4 flex items-start gap-3 backdrop-blur",
        toneClass
      )}
      role="alert"
    >
      <span className="text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5 bg-white/60 shrink-0 mt-0.5">
        Strategy Engine · {sev}
      </span>
      <div className="flex-1 min-w-0">
        <p className="font-medium text-sm">
          {latest.action.replace(/_/g, " ")} on {latest.scope}
        </p>
        <p className="text-xs leading-relaxed mt-0.5">{latest.reason}</p>
      </div>
      <Link
        href="/dashboard/strategy"
        className="text-xs underline shrink-0"
      >
        View
      </Link>
      <button
        type="button"
        onClick={dismiss}
        className="text-xs underline shrink-0"
        aria-label="Dismiss"
      >
        Dismiss
      </button>
    </div>
  );
}
