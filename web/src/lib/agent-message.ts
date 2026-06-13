/**
 * Shared formatting for agent messages — turns a raw message into plain,
 * readable words for the Activity feed and the ticker. One place so the
 * two never drift apart. Phase 12 follow-up.
 */

export type FeedMessage = {
  id: string;
  agent_name: string;
  kind: string;
  confidence?: number | null;
  payload: Record<string, unknown>;
  created_at: string;
};

const AGENT_NAMES: Record<string, string> = {
  pattern_detection: "Pattern Detection",
  stms_scanner: "Stock Bot",
  orb_scanner: "ORB Scanner",
  extended_scanner: "Extended Strategy",
  crypto_scanner: "Crypto Bot",
  options_scanner: "Options Scanner",
  risk_manager: "Risk Manager",
  trade_execution: "Trade Execution",
  position_monitor: "Position Monitor",
  tax_optimizer: "Tax Optimizer",
  kindrip: "KINDRIP",
  market_sentiment: "Market Sentiment",
  user_support: "User Support",
  research: "Research",
  adaptive_scope: "Adaptive Scope",
  strategy_discovery: "Strategy Discovery",
  dividend_manager: "Dividend Manager",
  market_horizon: "Market Horizon"
};

export function agentLabel(a: string): string {
  return AGENT_NAMES[a] ?? a.replace(/_/g, " ");
}

// Plain-language names for the trading strategies.
const STRATEGY_LABEL: Record<string, string> = {
  default: "Core scoring",
  pattern: "Pattern Engine",
  stms: "Stock Bot",
  orb: "ORB breakout",
  crypto: "Crypto momentum",
  extended: "Extended swing",
  crypto_hodl: "Crypto HODL (hold)",
  crypto_swing: "Crypto swing",
  crypto_dca: "Crypto DCA",
  crypto_scalp: "Crypto scalp"
};

export function strategyLabel(s: string): string {
  return STRATEGY_LABEL[s] ?? s.replace(/_/g, " ");
}

export const KIND_LABEL: Record<string, string> = {
  signal: "Signal",
  approve: "Approved",
  veto: "Held back",
  execute: "Trade",
  close: "Closed",
  alert: "Alert",
  error: "Error",
  metrics: "Metrics",
  info: "Update"
};

export const KIND_COLOR: Record<string, string> = {
  signal: "bg-weave-100 text-weave-800",
  approve: "bg-emerald-100 text-emerald-800",
  veto: "bg-amber-100 text-amber-800",
  execute: "bg-treasure-200 text-treasure-800",
  close: "bg-weave-100 text-weave-700",
  alert: "bg-red-100 text-red-800",
  error: "bg-red-100 text-red-800",
  metrics: "bg-weave-50 text-weave-600",
  info: "bg-weave-50 text-weave-600"
};

export function kindLabel(k: string): string {
  return KIND_LABEL[k] ?? k;
}

/** One plain-language sentence for an agent message. */
export function describeAgentMessage(m: FeedMessage): string {
  const p = m.payload ?? {};
  const str = (k: string) => (p[k] == null ? "" : String(p[k]));
  const numv = (k: string) => Number((p[k] as number) ?? 0);
  const ticker = str("ticker") || str("underlying") || str("symbol");

  // Most info / scan messages carry a plain 'note'.
  const note = typeof p.note === "string" ? p.note.trim() : "";
  if (note) {
    const bits: string[] = [];
    if ("coins_scanned" in p) bits.push(`${numv("coins_scanned")} coins`);
    if ("tickers_scanned" in p) bits.push(`${numv("tickers_scanned")} tickers`);
    if ("scanned" in p) bits.push(`${numv("scanned")} scanned`);
    if ("candidates_found" in p) bits.push(`${numv("candidates_found")} candidate(s)`);
    if ("signals" in p) bits.push(`${numv("signals")} signal(s)`);
    if ("breakouts" in p) bits.push(`${numv("breakouts")} breakout(s)`);
    if ("contributions_made" in p) bits.push(`${numv("contributions_made")} contribution(s)`);
    return bits.length ? `${note} — ${bits.join(", ")}.` : note;
  }

  // Event-tagged messages.
  const event = typeof p.event === "string" ? p.event : "";
  if (event) {
    switch (event) {
      case "options_idea":
        return `Options idea — ${str("strategy").replace(/_/g, " ")} on ${ticker}.`;
      case "kindrip_contribution":
        return `KINDRIP added a contribution to ${str("child_name") || "a child account"}.`;
      case "daily_profit_lock":
        return "Daily profit lock — the day's gains are secured.";
      case "performance_review_due":
        return "A 25-trade performance review is due.";
      case "employer_match_gap":
        return "Heads up — employer-match money may be left on the table.";
      default:
        return `${event.replace(/_/g, " ")}${ticker ? ` · ${ticker}` : ""}.`;
    }
  }

  // Trade-lifecycle messages keyed on a ticker.
  if (ticker) {
    const dir = str("direction") || str("side");
    const tcs = "tcs" in p ? ` (confidence ${numv("tcs")})` : "";
    switch (m.kind) {
      case "signal": {
        // Pattern Detection now picks the best strategy per stock — when
        // it does, the signal carries that choice, so name it.
        const strat = str("strategy");
        const fit =
          p.strategy_selection && strat
            ? ` · best fit: ${strategyLabel(strat)}`
            : "";
        return `Signal on ${ticker}${dir ? ` — looks ${dir}` : ""}${tcs}${fit}.`;
      }
      case "approve":
        return `Risk Manager approved a ${dir || "trade"} on ${ticker}.`;
      case "veto":
        return `Risk Manager held back ${ticker}${p.reason ? ` — ${str("reason")}` : ""}.`;
      case "execute":
        return `Placed a ${dir || ""} trade on ${ticker} (${
          str("venue") || str("broker") || "paper"
        }).`.replace(" ()", "").replace("  ", " ");
      case "close":
        return `Closed ${ticker}${p.reason ? ` — ${str("reason")}` : ""}.`;
      default:
        return `${kindLabel(m.kind)} — ${ticker}.`;
    }
  }

  // Position-check heartbeat (no note, just counts).
  if ("open_positions" in p) {
    return `Position check — watching ${numv("open_positions")} open position(s).`;
  }
  if (m.kind === "error") {
    return `Something went wrong: ${str("error") || "see the agent logs"}.`;
  }
  if (m.kind === "metrics") {
    return "Performance metrics updated.";
  }
  return `${kindLabel(m.kind)} from ${agentLabel(m.agent_name)}.`;
}
