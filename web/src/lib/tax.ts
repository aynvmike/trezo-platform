/**
 * Trezo tax estimation engine.
 *
 * IMPORTANT: this produces *estimates* to help the user plan and to hand
 * to a CPA. It is NOT tax advice and not a substitute for a professional.
 *
 * ANNUAL REFRESH -------------------------------------------------------
 * The tables below are dated. Once a year, when the IRS publishes the new
 * inflation-adjusted figures, update all of these and bump TAX_YEAR:
 *   - ORDINARY_BRACKETS   federal ordinary-income brackets
 *   - STANDARD_DEDUCTION  standard deduction by filing status
 *   - LTCG_0_CEILING / LTCG_15_CEILING  long-term capital-gains breakpoints
 * Source: the IRS annual inflation-adjustment release (search
 * "IRS <year> tax brackets"). Note: tax-strategy.ts separately carries
 * dated contribution limits (IRA / HSA / 529) to refresh in the same pass.
 * ---------------------------------------------------------------------
 *
 * Everything is computed from closed `paper_positions`.
 */

export type FilingStatus =
  | "single"
  | "married_joint"
  | "married_separate"
  | "head_of_household";

/** The tax year the tables in this file reflect. Bump on the annual
 * refresh (see the ANNUAL REFRESH note above). */
export const TAX_YEAR = 2025;

export type ClosedPosition = {
  id: string;
  ticker: string;
  side: string;
  quantity: number;
  entry_price: number;
  entry_at: string;
  exit_price: number | null;
  exit_at: string | null;
  realized_pnl_usd: number | null;
  status: string;
};

// --- 2025 federal ordinary-income brackets (approximate) -------------------

type Bracket = { upTo: number; rate: number };

const ORDINARY_BRACKETS: Record<FilingStatus, Bracket[]> = {
  single: [
    { upTo: 11_925, rate: 0.10 },
    { upTo: 48_475, rate: 0.12 },
    { upTo: 103_350, rate: 0.22 },
    { upTo: 197_300, rate: 0.24 },
    { upTo: 250_525, rate: 0.32 },
    { upTo: 626_350, rate: 0.35 },
    { upTo: Infinity, rate: 0.37 }
  ],
  married_joint: [
    { upTo: 23_850, rate: 0.10 },
    { upTo: 96_950, rate: 0.12 },
    { upTo: 206_700, rate: 0.22 },
    { upTo: 394_600, rate: 0.24 },
    { upTo: 501_050, rate: 0.32 },
    { upTo: 751_600, rate: 0.35 },
    { upTo: Infinity, rate: 0.37 }
  ],
  married_separate: [
    { upTo: 11_925, rate: 0.10 },
    { upTo: 48_475, rate: 0.12 },
    { upTo: 103_350, rate: 0.22 },
    { upTo: 197_300, rate: 0.24 },
    { upTo: 250_525, rate: 0.32 },
    { upTo: 375_800, rate: 0.35 },
    { upTo: Infinity, rate: 0.37 }
  ],
  head_of_household: [
    { upTo: 17_000, rate: 0.10 },
    { upTo: 64_850, rate: 0.12 },
    { upTo: 103_350, rate: 0.22 },
    { upTo: 197_300, rate: 0.24 },
    { upTo: 250_500, rate: 0.32 },
    { upTo: 626_350, rate: 0.35 },
    { upTo: Infinity, rate: 0.37 }
  ]
};

const STANDARD_DEDUCTION: Record<FilingStatus, number> = {
  single: 15_000,
  married_joint: 30_000,
  married_separate: 15_000,
  head_of_household: 22_500
};

// Long-term capital gains brackets (single-ish approximation; widened for joint)
const LTCG_0_CEILING: Record<FilingStatus, number> = {
  single: 48_350,
  married_joint: 96_700,
  married_separate: 48_350,
  head_of_household: 64_750
};
const LTCG_15_CEILING: Record<FilingStatus, number> = {
  single: 533_400,
  married_joint: 600_050,
  married_separate: 300_000,
  head_of_household: 566_700
};

// --- Holding period --------------------------------------------------------

export function holdingTerm(entryAt: string, exitAt: string | null): "short" | "long" {
  if (!exitAt) return "short";
  const ms = new Date(exitAt).getTime() - new Date(entryAt).getTime();
  const days = ms / 86_400_000;
  return days >= 365 ? "long" : "short";
}

// --- Gain aggregation ------------------------------------------------------

export type GainSummary = {
  shortTermGain: number;
  longTermGain: number;
  totalRealized: number;
  winners: number;
  losers: number;
  tradeCount: number;
};

export function summarizeGains(positions: ClosedPosition[]): GainSummary {
  let st = 0;
  let lt = 0;
  let winners = 0;
  let losers = 0;
  for (const p of positions) {
    const pnl = Number(p.realized_pnl_usd ?? 0);
    if (holdingTerm(p.entry_at, p.exit_at) === "long") lt += pnl;
    else st += pnl;
    if (pnl >= 0) winners++;
    else losers++;
  }
  return {
    shortTermGain: st,
    longTermGain: lt,
    totalRealized: st + lt,
    winners,
    losers,
    tradeCount: positions.length
  };
}

// --- Wash-sale detection ---------------------------------------------------

export type WashSaleFlag = {
  ticker: string;
  lossPositionId: string;
  lossAmount: number;
  repurchasePositionId: string;
  daysApart: number;
};

/**
 * Simplified wash-sale scan: a loss is flagged if the SAME ticker was
 * (re)bought within 30 days before or after the losing sale. The real IRS
 * rule has more nuance (replacement shares, options, IRAs) — this is a
 * planning aid, not a determination.
 */
export function detectWashSales(positions: ClosedPosition[]): WashSaleFlag[] {
  const flags: WashSaleFlag[] = [];
  const losses = positions.filter(
    (p) => Number(p.realized_pnl_usd ?? 0) < 0 && p.exit_at
  );
  for (const loss of losses) {
    const lossDate = new Date(loss.exit_at as string).getTime();
    for (const other of positions) {
      if (other.id === loss.id) continue;
      if (other.ticker.toUpperCase() !== loss.ticker.toUpperCase()) continue;
      const buyDate = new Date(other.entry_at).getTime();
      const days = Math.abs(buyDate - lossDate) / 86_400_000;
      if (days <= 30) {
        flags.push({
          ticker: loss.ticker.toUpperCase(),
          lossPositionId: loss.id,
          lossAmount: Number(loss.realized_pnl_usd ?? 0),
          repurchasePositionId: other.id,
          daysApart: Math.round(days)
        });
        break; // one flag per loss is enough for a planning view
      }
    }
  }
  return flags;
}

// --- Tax estimate ----------------------------------------------------------

function ordinaryTaxOn(amount: number, status: FilingStatus): number {
  if (amount <= 0) return 0;
  let tax = 0;
  let prev = 0;
  for (const b of ORDINARY_BRACKETS[status]) {
    const slice = Math.min(amount, b.upTo) - prev;
    if (slice > 0) tax += slice * b.rate;
    prev = b.upTo;
    if (amount <= b.upTo) break;
  }
  return tax;
}

export type TaxEstimate = {
  taxableOrdinaryIncome: number;
  shortTermGain: number;
  longTermGain: number;
  // Short-term gains stack on ordinary income — this is the marginal cost
  // of the gains, i.e. tax(income+stGain) - tax(income).
  federalOnShortTerm: number;
  federalOnLongTerm: number;
  federalTotal: number;
  stateTotal: number;
  combinedTotal: number;
  effectiveRatePct: number;
};

export function estimateTax(
  gains: GainSummary,
  opts: {
    annualIncome: number;
    filingStatus: FilingStatus;
    stateTaxRatePct: number;
  }
): TaxEstimate {
  const { annualIncome, filingStatus, stateTaxRatePct } = opts;
  const deduction = STANDARD_DEDUCTION[filingStatus];
  const taxableOrdinary = Math.max(0, annualIncome - deduction);

  const st = Math.max(0, gains.shortTermGain); // losses don't create tax
  const lt = Math.max(0, gains.longTermGain);

  // Short-term: marginal cost of stacking ST gains on top of ordinary income
  const fedOnShort =
    ordinaryTaxOn(taxableOrdinary + st, filingStatus) -
    ordinaryTaxOn(taxableOrdinary, filingStatus);

  // Long-term: 0 / 15 / 20% depending on where income+lt lands
  let fedOnLong = 0;
  const zeroCeil = LTCG_0_CEILING[filingStatus];
  const fifteenCeil = LTCG_15_CEILING[filingStatus];
  const base = taxableOrdinary;
  let remaining = lt;
  // 0% portion
  const zeroRoom = Math.max(0, zeroCeil - base);
  const atZero = Math.min(remaining, zeroRoom);
  remaining -= atZero;
  // 15% portion
  const fifteenRoom = Math.max(0, fifteenCeil - Math.max(base, zeroCeil));
  const atFifteen = Math.min(remaining, fifteenRoom);
  fedOnLong += atFifteen * 0.15;
  remaining -= atFifteen;
  // 20% portion
  fedOnLong += remaining * 0.20;

  const federalTotal = fedOnShort + fedOnLong;
  const stateTotal = (st + lt) * (stateTaxRatePct / 100);
  const combinedTotal = federalTotal + stateTotal;
  const totalGain = st + lt;
  const effectiveRatePct = totalGain > 0 ? (combinedTotal / totalGain) * 100 : 0;

  return {
    taxableOrdinaryIncome: taxableOrdinary,
    shortTermGain: gains.shortTermGain,
    longTermGain: gains.longTermGain,
    federalOnShortTerm: fedOnShort,
    federalOnLongTerm: fedOnLong,
    federalTotal,
    stateTotal,
    combinedTotal,
    effectiveRatePct
  };
}

// --- Quarterly estimates ---------------------------------------------------

export type QuarterEstimate = {
  quarter: string;     // 'Q1'..'Q4'
  dueDate: string;     // IRS due date label
  realizedGain: number;
  estimatedTax: number;
};

const QUARTER_DUE = ["Apr 15", "Jun 15", "Sep 15", "Jan 15 (next yr)"];

/**
 * Split closed positions into IRS quarters by exit date and estimate the
 * tax attributable to each. Uses the combined effective rate from the
 * full-year estimate so each quarter is proportional.
 */
export function quarterlyEstimates(
  positions: ClosedPosition[],
  effectiveRatePct: number
): QuarterEstimate[] {
  const buckets = [0, 0, 0, 0];
  for (const p of positions) {
    if (!p.exit_at) continue;
    const m = new Date(p.exit_at).getMonth(); // 0-11
    // IRS quarters: Q1 Jan-Mar, Q2 Apr-May, Q3 Jun-Aug, Q4 Sep-Dec
    let q = 0;
    if (m <= 2) q = 0;
    else if (m <= 4) q = 1;
    else if (m <= 7) q = 2;
    else q = 3;
    buckets[q] += Number(p.realized_pnl_usd ?? 0);
  }
  return buckets.map((gain, i) => ({
    quarter: `Q${i + 1}`,
    dueDate: QUARTER_DUE[i],
    realizedGain: gain,
    estimatedTax: Math.max(0, gain) * (effectiveRatePct / 100)
  }));
}
