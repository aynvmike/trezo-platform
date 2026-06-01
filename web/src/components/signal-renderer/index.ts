/**
 * Public surface of the signal-renderer module. Modular by design -
 * future builds that need to render signals (Wheel page, Options
 * Engine cards, future mobile-first dashboards) import from here
 * and get the same 4-layer safety for free.
 */
export { SignalCard } from "./signal-card";
export { TerseSignal } from "./terse-signal";
export { toTerseFields } from "./to-terse-fields";
export type { TerseFields } from "./to-terse-fields";
export { applyTerseRules, buildTerseReasoning, tcsToConfidence }
  from "./format-rules";

/**
 * Read the platform kill switch. Server-side only (process.env).
 * When this returns true, SignalCard hides its toggle and forces
 * verbose for every user on every page.
 */
export function isTerseFormatKilled(): boolean {
  return process.env.TREZO_TERSE_MODE_DISABLED === "true";
}
