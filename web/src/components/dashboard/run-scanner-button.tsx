"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

type Resp = {
  ok: boolean;
  agent?: string;
  error?: string;
  summary?: string;
  messages_produced?: number;
  by_kind?: Record<string, number>;
};

/**
 * One-click "Run [agent] now" button. Posts to /api/agents/run-now/:name
 * which force-ticks the named scanner immediately. Surfaces the message
 * count + by-kind summary so Mike can see end-to-end (signal → approve →
 * execute) in a single click.
 *
 * Used on Paper Trading & Live Trading pages so he can pulse-test the
 * STMS / Pattern Detection / Crypto chains during the 7-11 AM window
 * without waiting on the 60-90s scheduler cadence.
 */
export function RunScannerButton({
  name,
  label,
  hint
}: {
  name: string;
  label: string;
  hint?: string;
}) {
  const router = useRouter();
  const [stage, setStage] = useState<"idle" | "running" | "done" | "error">("idle");
  const [resp, setResp] = useState<Resp | null>(null);

  // Auto-clear stale error/done UI after 8 seconds so the dashboard
  // doesn't show "stocks cannot be force-ticked" forever (Task #68).
  useEffect(() => {
    if (stage !== "error" && stage !== "done") return;
    const t = setTimeout(() => {
      setStage("idle");
      setResp(null);
    }, 8000);
    return () => clearTimeout(t);
  }, [stage]);

  async function send() {
    setStage("running");
    try {
      const r = await fetch(`/api/agents/run-now/${encodeURIComponent(name)}`, {
        method: "POST"
      });
      const j = (await r.json()) as Resp;
      setResp(j);
      setStage(j.ok ? "done" : "error");
      if (j.ok) router.refresh();
    } catch (e) {
      setResp({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  const text =
    stage === "running"
      ? "Ticking…"
      : stage === "done"
      ? `✓ ${resp?.summary ?? "done"}`
      : stage === "error"
      ? `✗ ${resp?.error ?? "failed"}`
      : label;

  return (
    <button
      type="button"
      onClick={send}
      disabled={stage === "running"}
      title={hint}
      className={cn(
        "rounded-md border px-3 py-1.5 text-xs font-medium transition disabled:opacity-60",
        stage === "done"
          ? "border-emerald-300 bg-emerald-50 text-emerald-800"
          : stage === "error"
          ? "border-red-300 bg-red-50 text-red-700"
          : "border-weave-200 bg-white text-weave-700 hover:bg-weave-50"
      )}
    >
      {text}
    </button>
  );
}
