/**
 * Payload-to-TerseFields converter.
 *
 * Takes an arbitrary agent_messages payload and extracts the 8-line
 * trader schema. Designed to be forgiving: any field that can't be
 * resolved becomes a dash. The caller's try-catch never has to fire
 * on a missing-field issue alone - we degrade gracefully.
 */

import { buildTerseReasoning, tcsToConfidence } from "./format-rules";

export type TerseFields = {
  ticker: string;
  bias: "Bullish" | "Bearish" | "Neutral";
  trade_type: string;
  strike_expiration: string;
  entry_range: string;
  exit_target_stop: string;
  confidence: number | null;
  reasoning: string;
};

type AnyPayload = Record<string, unknown>;

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function biasFromDirection(direction: unknown): TerseFields["bias"] {
  const d = String(direction ?? "").toLowerCase();
  if (d === "bullish" || d === "long") return "Bullish";
  if (d === "bearish" || d === "short") return "Bearish";
  return "Neutral";
}

function tradeTypeFor(payload: AnyPayload): string {
  const strat = String(payload.strategy ?? "").toLowerCase();
  if (strat.startsWith("wheel_csp")) return "Put";
  if (strat.startsWith("wheel_cc")) return "Call";
  if (strat.includes("long_call") || strat === "iv_crush_short") return "Call";
  if (strat.includes("put")) return "Put";
  if (strat.includes("spread")) return "Spread";
  if (strat.includes("condor")) return "Spread";
  if (payload.legs && Array.isArray(payload.legs) && payload.legs.length > 1) {
    return "Spread";
  }
  // default: equity
  return "Common Share";
}

function strikeExpiration(payload: AnyPayload): string {
  const strike = num(payload.strike);
  const exp = payload.expiration;
  if (strike === null && !exp) return "—";
  const type = String(payload.option_type ?? "").toUpperCase();
  const parts: string[] = [];
  if (strike !== null) parts.push(strike.toFixed(2));
  if (type === "PUT" || type === "CALL") parts.push(type);
  if (exp) parts.push(String(exp));
  return parts.join(" ");
}

function entryRange(payload: AnyPayload): string {
  // Equity: derive from current price ± a small buffer (the bot fires
  // near spot). Options: use the modeled premium / strike when present.
  const entry = num(payload.entry_price ?? payload.spot ?? payload.price);
  if (entry === null) return "—";
  const buf = entry * 0.003;
  return `${(entry - buf).toFixed(2)} to ${(entry + buf).toFixed(2)}`;
}

function exitTargetStop(payload: AnyPayload): string {
  // Prefer absolute prices when the bot computed them; fall back to
  // percentage geometry from the signal payload.
  const target = num(payload.target_price);
  const stop = num(payload.stop_price);
  if (target !== null && stop !== null) {
    return `${target.toFixed(2)} / ${stop.toFixed(2)}`;
  }
  const targetPct = num(payload.target_pct);
  const stopPct = num(payload.stop_pct);
  const entry = num(payload.entry_price ?? payload.spot ?? payload.price);
  if (entry !== null && targetPct !== null && stopPct !== null) {
    const bias = biasFromDirection(payload.direction);
    const sign = bias === "Bearish" ? -1 : 1;
    const t = entry * (1 + sign * targetPct);
    const s = entry * (1 - sign * stopPct);
    return `${t.toFixed(2)} / ${s.toFixed(2)}`;
  }
  return "—";
}

export function toTerseFields(payload: AnyPayload): TerseFields {
  const ticker = String(
    payload.ticker ?? payload.underlying ?? ""
  ).toUpperCase() || "—";

  return {
    ticker,
    bias: biasFromDirection(payload.direction),
    trade_type: tradeTypeFor(payload),
    strike_expiration: strikeExpiration(payload),
    entry_range: entryRange(payload),
    exit_target_stop: exitTargetStop(payload),
    confidence: tcsToConfidence(num(payload.tcs)),
    reasoning: buildTerseReasoning(payload as Parameters<typeof buildTerseReasoning>[0]),
  };
}
