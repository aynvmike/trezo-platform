/**
 * Writing-rules enforcer for the terse signal format.
 *
 * Codifies the Mike spec:
 *  - No em dashes (use periods instead).
 *  - No semicolons.
 *  - No hedging words: maybe / could / probably / possibly.
 *  - No weasel words: can / may / just / very / really / probably /
 *    basically / maybe / literally / revolutionary / pivotal /
 *    however / remarkable / interesting.
 *  - No markdown, hashtags, asterisks.
 *  - No generic phrases: in conclusion / overall / as mentioned earlier.
 *
 * Deterministic, no LLM. Strips banned words, normalises punctuation,
 * truncates trailing filler. Used by the terse renderer to clean
 * payload-derived reasoning strings before display.
 */

const BANNED_WORDS = [
  // hedging
  "maybe", "could", "probably", "possibly",
  // weasel
  "can", "may", "just", "very", "really", "basically",
  "literally", "revolutionary", "pivotal", "however",
  "remarkable", "interesting",
];

const BANNED_PHRASES = [
  /\bin conclusion[,.]?\s*/gi,
  /\boverall[,.]?\s*/gi,
  /\bas mentioned earlier[,.]?\s*/gi,
  /\bit (is|was) important to note[,.]?\s*/gi,
];

export function applyTerseRules(input: string): string {
  if (!input) return "";
  let s = input;

  // 1. Em dashes -> periods. en-dash and figure-dash too.
  s = s.replace(/[—–]/g, ".");

  // 2. Semicolons -> periods.
  s = s.replace(/;/g, ".");

  // 3. Strip banned phrases first (longer matches before single words).
  for (const re of BANNED_PHRASES) {
    s = s.replace(re, "");
  }

  // 4. Strip banned single words (case-insensitive, word-boundary).
  for (const w of BANNED_WORDS) {
    const re = new RegExp(`\\b${w}\\b`, "gi");
    s = s.replace(re, "");
  }

  // 5. Markdown / asterisks / hashtags.
  s = s.replace(/[*#`_~]/g, "");

  // 6. Collapse double spaces and orphan punctuation.
  s = s.replace(/\s{2,}/g, " ");
  s = s.replace(/\s+([.,!?])/g, "$1");
  s = s.replace(/\.{2,}/g, ".");
  s = s.replace(/^[\s.,]+/, "").trim();

  // 7. Ensure terminal period if any text remains.
  if (s && !/[.!?]$/.test(s)) s += ".";

  return s;
}

/**
 * Build a 2-3 sentence reasoning string from structured payload bits.
 * Deterministic: only uses fields actually present on the payload.
 * Designed so a signal with sparse data still produces something
 * useful rather than a broken render.
 */
export function buildTerseReasoning(payload: {
  strategy?: string;
  dominant_pattern?: string;
  detected_patterns?: string[];
  breakdown?: Record<string, number> | null;
  cycle?: { iv_environment?: string; next_earnings_days?: number };
  stms_filters?: {
    relative_volume?: number;
    daily_move_pct?: number;
  };
  scope?: { regime?: string };
}): string {
  const parts: string[] = [];

  if (payload.dominant_pattern) {
    parts.push(
      `Dominant pattern ${payload.dominant_pattern.replace(/_/g, " ")}.`
    );
  } else if (payload.strategy) {
    parts.push(`Strategy ${payload.strategy}.`);
  }

  // Top 2 breakdown factors with their score
  if (payload.breakdown) {
    const ranked = Object.entries(payload.breakdown)
      .filter(([, v]) => Number.isFinite(v) && v > 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, 2);
    if (ranked.length > 0) {
      const labels = ranked.map(([k]) => k.replace(/_/g, " ")).join(", ");
      parts.push(`Top factors ${labels}.`);
    }
  }

  if (payload.stms_filters?.relative_volume) {
    parts.push(
      `Volume ${payload.stms_filters.relative_volume.toFixed(1)}x average.`
    );
  }

  if (payload.cycle?.iv_environment && payload.cycle.iv_environment !== "normal") {
    parts.push(`IV environment ${payload.cycle.iv_environment.replace(/_/g, " ")}.`);
  }

  if (payload.scope?.regime && payload.scope.regime !== "normal") {
    parts.push(`Regime ${payload.scope.regime}.`);
  }

  // Cap at 3 sentences
  const trimmed = parts.slice(0, 3).join(" ");
  return applyTerseRules(trimmed);
}

export function tcsToConfidence(tcs: number | null | undefined): number | null {
  if (tcs === null || tcs === undefined || !Number.isFinite(tcs)) return null;
  const c = Math.round(Number(tcs) / 100);
  return Math.max(1, Math.min(10, c));
}
