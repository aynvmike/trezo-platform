/**
 * KINDRIP projection — models a child's Future Index Account forward to
 * age 18: a compound-growth model on the current balance plus ongoing
 * monthly contributions. Phase 14.
 *
 * The numbers are illustrative estimates, not a promise — markets vary.
 */

export type ProjPoint = {
  year: number;
  age: number;
  contributed: number; // cumulative contributions added since today
  value: number; // projected account value
};

export const RETURN_SCENARIOS = {
  conservative: 0.05,
  expected: 0.07,
  strong: 0.09
} as const;
export type Scenario = keyof typeof RETURN_SCENARIOS;

// A rough yearly tax drag a regular taxable brokerage account would face
// (dividend tax + turnover). A tax-advantaged account avoids it. Modest
// on purpose — this is an estimate, not a guarantee.
export const TAXABLE_DRAG = 0.008;

export const AGE_OF_MAJORITY = 18;

/** Year-by-year projection from the child's current age to 18. */
export function project(
  currentValue: number,
  currentAge: number,
  monthlyContribution: number,
  annualReturn: number
): ProjPoint[] {
  const startYear = new Date().getFullYear();
  const yearsLeft = Math.max(0, AGE_OF_MAJORITY - currentAge);
  const monthlyRate = annualReturn / 12;
  const monthly = Math.max(0, monthlyContribution);

  let value = Math.max(0, currentValue);
  let contributed = 0;
  const points: ProjPoint[] = [
    { year: startYear, age: currentAge, contributed: 0, value }
  ];

  for (let y = 1; y <= yearsLeft; y++) {
    for (let m = 0; m < 12; m++) {
      value = value * (1 + monthlyRate) + monthly;
      contributed += monthly;
    }
    points.push({ year: startYear + y, age: currentAge + y, contributed, value });
  }
  return points;
}

export type ProjectionSummary = {
  points: ProjPoint[];
  finalValue: number;
  totalContributed: number;
  growth: number;
  yearsLeft: number;
  taxAdvantage: number; // est. $ the tax-advantaged account beats a taxable one by, at 18
};

export function summarize(
  currentValue: number,
  currentAge: number,
  monthlyContribution: number,
  annualReturn: number
): ProjectionSummary {
  const points = project(currentValue, currentAge, monthlyContribution, annualReturn);
  const final = points[points.length - 1];

  // Same contributions, but a taxable account compounds at a slightly
  // lower rate because of the yearly tax drag. The gap at 18 is the
  // estimated tax benefit of the Future Index Account.
  const taxablePoints = project(
    currentValue,
    currentAge,
    monthlyContribution,
    Math.max(0, annualReturn - TAXABLE_DRAG)
  );
  const taxableFinal = taxablePoints[taxablePoints.length - 1];

  return {
    points,
    finalValue: final.value,
    totalContributed: final.contributed,
    growth: final.value - final.contributed,
    yearsLeft: Math.max(0, AGE_OF_MAJORITY - currentAge),
    taxAdvantage: Math.max(0, final.value - taxableFinal.value)
  };
}
