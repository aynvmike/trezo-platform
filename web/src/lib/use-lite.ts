"use client";

import { useEffect, useState } from "react";

/**
 * Lite Mode — a performance switch.
 *
 * When ON, the dashboard drops its heavy 3D / parallax visuals and slows
 * its live data polling, so the browser and the shared agents backend
 * (port 8001) aren't doing extra work that competes with the trading
 * agents. Data still flows — just less often. Agent automation is never
 * touched by this.
 *
 * State of record is the `data-lite="on" | "off"` attribute on <html>; an
 * inline script in the root layout applies the saved choice before paint.
 * The LiteToggle flips the attribute, writes `trezo_lite` to localStorage,
 * and dispatches a `trezo-lite` event so live components re-rate without a
 * reload. Mirrors the experience-toggle pattern.
 */

/** Floor (seconds) that polling is clamped to when Lite is ON (Mike: 30-60s). */
export const LITE_MIN_REFRESH_SEC = 45;

function readLite(): boolean {
  if (typeof document === "undefined") return false;
  return document.documentElement.getAttribute("data-lite") === "on";
}

/** Reactive boolean: is Lite Mode currently on? Updates live on toggle. */
export function useLite(): boolean {
  const [lite, setLite] = useState(false);

  useEffect(() => {
    setLite(readLite());

    function onLite(e: Event) {
      setLite((e as CustomEvent<string>).detail === "on");
    }
    function onStorage(e: StorageEvent) {
      if (e.key === "trezo_lite") setLite(e.newValue === "on");
    }

    window.addEventListener("trezo-lite", onLite as EventListener);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("trezo-lite", onLite as EventListener);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return lite;
}

/**
 * Effective refresh interval in seconds for a poller. Pass the normal
 * (Rich-mode) base; when Lite is ON the result is clamped to at least
 * LITE_MIN_REFRESH_SEC. Use the returned value in setInterval and include
 * it in the effect deps so the timer re-subscribes when Lite flips.
 */
export function useLiteRefresh(baseSec: number): number {
  const lite = useLite();
  return lite ? Math.max(baseSec, LITE_MIN_REFRESH_SEC) : baseSec;
}
