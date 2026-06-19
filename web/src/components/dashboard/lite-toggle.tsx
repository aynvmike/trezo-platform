"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

type Mode = "off" | "on";

/**
 * Site-wide Rich / Lite switch. Lite (off by default) drops the heavy 3D
 * visuals and slows live data polling so the browser and the shared agents
 * backend aren't overloaded — protecting the trading agents' resources.
 * Data still flows, just less often; agent automation is untouched.
 *
 * The choice is the `data-lite` attribute on <html> — an inline script in
 * the root layout applies the saved value before paint (no flash). This
 * control flips it, persists `trezo_lite`, and fires a `trezo-lite` event
 * so pollers re-rate without a reload. Mirrors the experience toggle.
 */
export function LiteToggle() {
  const [mode, setMode] = useState<Mode>("off");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const attr = document.documentElement.getAttribute("data-lite");
    setMode(attr === "on" ? "on" : "off");
    setReady(true);
  }, []);

  function pick(next: Mode) {
    setMode(next);
    document.documentElement.setAttribute("data-lite", next);
    try {
      localStorage.setItem("trezo_lite", next);
    } catch {
      /* localStorage unavailable — the attribute still flips this session */
    }
    window.dispatchEvent(new CustomEvent("trezo-lite", { detail: next }));
  }

  return (
    <div
      role="group"
      aria-label="Performance mode"
      title="Lite drops heavy visuals and slows live updates so the trading agents aren't competing with the dashboard for resources"
      className="hidden sm:flex items-center rounded-md border border-weave-200 p-0.5"
    >
      {(
        [
          ["off", "Rich"],
          ["on", "Lite"]
        ] as [Mode, string][]
      ).map(([m, label]) => (
        <button
          key={m}
          type="button"
          onClick={() => pick(m)}
          aria-pressed={ready && mode === m}
          title={
            m === "off"
              ? "Rich — full visuals and fast live updates"
              : "Lite — flat visuals, updates slow to ~45s, agents get priority"
          }
          className={cn(
            "rounded px-2 py-1 text-xs transition",
            ready && mode === m
              ? "bg-weave-100 text-weave-800"
              : "text-weave-500 hover:text-weave-700"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
