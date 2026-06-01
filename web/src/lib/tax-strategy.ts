// Tax Strategy — tax-advantaged account knowledge + the math.
//
// Phase 9.5. Educational by design: it explains each account and strategy
// in plain language and shows the numbers, but makes no personalized
// "you should" recommendations. Trezo frames tax content as information,
// not advice.

export type AccountAudience = "family" | "individual" | "both";

export type AccountInfo = {
  id: string;
  name: string;
  audience: AccountAudience; // family = good for a child / individual / both
  what: string; // plain "what it is"
  why: string; // plain "why it helps"
  facts: string[];
  example: string; // a plain-language worked example — illustrative, not advice
};

export const TAX_ADVANTAGED_ACCOUNTS: AccountInfo[] = [
  {
    id: "employer_retirement",
    name: "Employer-matched retirement (401(k) / Roth 401(k))",
    audience: "individual",
    what: "A retirement account offered through your job. Many employers match part of what you put in.",
    why: "The match is free money — an immediate return on every dollar you contribute, before the market does anything at all.",
    facts: [
      "A common match is 50% of what you contribute, up to 6% of your salary.",
      "Contributing at least up to the match cap captures the whole match.",
      "A Roth 401(k) is taxed now and grows tax-free; a traditional 401(k) lowers your taxable income today."
    ],
    example: "Example: on a $60,000 salary with a 50%-up-to-6% match, contributing 6% ($3,600) earns an extra $1,800 a year from your employer — free, before any market move."
  },
  {
    id: "roth_ira",
    name: "Roth IRA",
    audience: "individual",
    what: "A personal retirement account you open yourself — no employer involved.",
    why: "You contribute money you have already paid tax on, and it grows completely tax-free. Qualified withdrawals in retirement are tax-free.",
    facts: [
      "The 2025 contribution limit is about $7,000 ($8,000 if you are 50 or older).",
      "There are income limits on who can contribute directly.",
      "No employer match — but decades of tax-free growth is the advantage."
    ],
    example: "Example: $500 a month from age 30 to 65, at a ~7% return, could grow past $850,000 — and every dollar of it comes out tax-free."
  },
  {
    id: "hsa",
    name: "Health Savings Account (HSA)",
    audience: "individual",
    what: "A savings account paired with a high-deductible health plan — money goes in, grows invested, and comes out for medical costs.",
    why: "It is the only account taxed in none of the three ways: contributions, growth, and qualified medical withdrawals are all tax-free.",
    facts: [
      "The 2025 limit is about $4,300 for an individual and $8,550 for a family.",
      "Unused money rolls over every year — it is not use-it-or-lose-it.",
      "After age 65 it works like a retirement account for any spending, taxed only as ordinary income."
    ],
    example: "Example: $300 a month invested in an HSA from age 35 and left untouched, at ~7%, could exceed $250,000 by age 65 — usable tax-free for medical costs."
  },
  {
    id: "i_bonds",
    name: "Series I savings bonds (I-bonds)",
    audience: "both",
    what: "US government savings bonds whose interest rate tracks inflation — a low-risk way to hold cash savings without losing ground to rising prices.",
    why: "The interest is exempt from state tax, and federal tax can be deferred until you cash out — or skipped entirely if the money is used for qualified education.",
    facts: [
      "Bought directly from the US Treasury at treasurydirect.gov; up to $10,000 per person per year.",
      "Must be held at least 1 year; cashing out before 5 years forfeits the last 3 months of interest.",
      "A steady, principal-safe place for an emergency fund or a child's near-term savings."
    ],
    example: "Example: $5,000 in I-bonds tracks inflation — if inflation runs about 3% that year, the bond grows roughly 3%, with the interest tax-deferred until you cash it in."
  },
  {
    id: "future_index",
    name: "Future Index Account (KINDRIP)",
    audience: "family",
    what: "The federal child account created under the One Big Beautiful Bill — Trezo's KINDRIP layer routes contributions into it.",
    why: "A one-time $1,000 federal seed plus tax-advantaged growth, started while a child is young enough for decades of compounding.",
    facts: [
      "One-time $1,000 federal contribution per eligible child.",
      "Up to $5,000 a year can be contributed.",
      "Invested in US stock-index funds; stays invested until the child turns 18."
    ],
    example: "Example: the $1,000 federal seed plus $150 a month, at a ~7% return, could be worth around $63,000 by the time the child turns 18."
  },
  {
    id: "education_529",
    name: "529 college-savings plan",
    audience: "family",
    what: "A state-sponsored investment account built for education — tuition, room and board, books, and some K-12 and apprenticeship costs.",
    why: "The money grows tax-free, and anything spent on qualified education is never taxed. Many states also give a tax deduction or credit on what you contribute.",
    facts: [
      "No federal contribution limit, though gifts above the annual exclusion (about $19,000 in 2025) need reporting.",
      "Most 529 plans offer an age-based option that shifts from stocks to bonds automatically as college nears.",
      "Unused funds can move to another family member, or up to $35,000 (lifetime) into the child's Roth IRA.",
      "It complements KINDRIP: the Future Index Account builds general wealth, a 529 earmarks money for school."
    ],
    example: "Example: $200 a month from a child's birth, at a ~7% return, could reach roughly $86,000 by age 18 — and none of that growth is taxed if it is spent on school."
  },
  {
    id: "coverdell_esa",
    name: "Coverdell Education Savings Account (ESA)",
    audience: "family",
    what: "A small education-savings account — like a 529, but it also covers a wider range of K-12 costs and lets you pick your own investments.",
    why: "Growth and qualified-education withdrawals are tax-free, and the money can be spent on school costs from kindergarten through college.",
    facts: [
      "Capped at $2,000 per child per year, and the contributor must be under an income limit.",
      "Must generally be used by the time the child turns 30, or rolled to another family member.",
      "Often used alongside a 529 — the ESA for flexibility, the 529 for higher contribution room."
    ],
    example: "Example: the $2,000 yearly maximum invested from a child's birth, at ~7%, reaches roughly $72,000 by age 18 — tax-free for tuition, books, even K-12 costs."
  },
  {
    id: "custodial_roth",
    name: "Custodial Roth IRA (for a child)",
    audience: "family",
    what: "A Roth IRA an adult opens and manages for a child who has earned income — money from a real job, like a summer or part-time job.",
    why: "Starting a Roth this early gives the money the longest possible runway — decades of completely tax-free compounding.",
    facts: [
      "The child can contribute up to what they earned that year, capped at the annual IRA limit (~$7,000 in 2025).",
      "Control passes to the child at the age of majority.",
      "Contributions (not earnings) can be withdrawn anytime, which keeps it flexible."
    ],
    example: "Example: a teen earning $3,000 from a summer job puts it in a custodial Roth; left alone at ~7% for 50 years, that single $3,000 year could grow past $90,000 — tax-free."
  },
  {
    id: "custodial_brokerage",
    name: "Custodial brokerage account (UTMA / UGMA)",
    audience: "family",
    what: "A regular investment account an adult opens and manages for a minor. The money legally belongs to the child and becomes theirs at the age of majority.",
    why: "It has no contribution limit and no spending restrictions — the most flexible way to build a child a pot of money for anything, not just school.",
    facts: [
      "No contribution cap and no withdrawal rules, but the money cannot be taken back once it is in.",
      "A child's investment income above a small threshold is taxed under the 'kiddie tax' rules.",
      "It counts as the child's own asset, which can affect college financial aid."
    ],
    example: "Example: $100 a month into a custodial account from a child's birth, at a ~7% return, is about $43,000 by age 18 — fully the child's, usable for anything."
  }
];

/** The accounts that can hold a child's / family's wealth — shown on KINDRIP. */
export function familyAccounts(): AccountInfo[] {
  return TAX_ADVANTAGED_ACCOUNTS.filter(
    (a) => a.audience === "family" || a.audience === "both"
  );
}

export type TaxStrategy = {
  id: string;
  name: string;
  what: string;
  why: string;
  appliesTo: string; // who this is most useful for
};

// A working set of tax-saving moves, in plain language. Educational — each
// describes how the move works, never a personalized "you should do this".
export const TAX_STRATEGIES: TaxStrategy[] = [
  {
    id: "capture_match",
    name: "Capture the full employer match",
    what: "Contribute to your workplace retirement plan at least up to the percentage your employer matches.",
    why: "The match is an instant, guaranteed return — often 25-100% — that no trade can reliably beat. Stopping short of the cap leaves money on the table.",
    appliesTo: "Anyone with a 401(k) or 403(b) that offers a match."
  },
  {
    id: "long_term_holding",
    name: "Hold winners past one year",
    what: "When a position is in profit, holding it longer than 12 months changes how the gain is taxed.",
    why: "A gain on something held over a year is taxed at the long-term rate (0%, 15%, or 20%) — usually well below the short-term rate, which matches your ordinary income.",
    appliesTo: "Anyone with profitable positions and no urgent reason to sell."
  },
  {
    id: "loss_harvesting",
    name: "Tax-loss harvesting",
    what: "Realize a loss on a position that is down, to offset gains taken elsewhere in the same year.",
    why: "Losses cancel gains dollar-for-dollar, and up to $3,000 of leftover loss can offset ordinary income — with the rest carried into future years.",
    appliesTo: "Anyone holding both winning and losing positions in a taxable account."
  },
  {
    id: "wash_sale",
    name: "Mind the wash-sale rule",
    what: "If you sell at a loss and rebuy the same security within 30 days, the IRS disallows that loss for now.",
    why: "Knowing the rule keeps a harvested loss from being quietly cancelled. Trezo's Tax Optimizer already scans your trades for it.",
    appliesTo: "Anyone harvesting losses or trading the same ticker repeatedly."
  },
  {
    id: "qualified_dividends",
    name: "Favor qualified dividends",
    what: "Dividends from US stocks and many funds held long enough are 'qualified' and taxed at the lower long-term rate.",
    why: "The same dividend dollar is taxed less when it qualifies — meeting the holding-period rule is what makes the difference.",
    appliesTo: "Dividend and Wheel strategy users, and KINDRIP's SCHD sleeve."
  },
  {
    id: "asset_location",
    name: "Asset location",
    what: "Keep tax-heavy holdings (bonds, high-turnover strategies) inside tax-advantaged accounts, and tax-efficient ones in taxable accounts.",
    why: "The same portfolio keeps more after tax when each holding sits in the account type that taxes it the least.",
    appliesTo: "Anyone using more than one account type."
  },
  {
    id: "education_529",
    name: "529 for a child's education",
    what: "Save for school in a 529 plan instead of a regular taxable account.",
    why: "Growth and qualified-education withdrawals are tax-free, and many states add a deduction or credit on contributions.",
    appliesTo: "Parents or relatives saving for a child's education — alongside KINDRIP."
  },
  {
    id: "withholding",
    name: "Set aside tax on trading gains",
    what: "A paycheck has tax withheld automatically; trading profits do not. Set money aside, or make quarterly estimated payments.",
    why: "It avoids a surprise bill — and a possible underpayment penalty — at tax time. Trezo's Tax Optimizer estimates the quarterly amounts for you.",
    appliesTo: "Anyone with meaningful gains outside a tax-advantaged account."
  },
  {
    id: "roth_diversification",
    name: "Build some Roth (tax-free) money",
    what: "Direct part of your saving into Roth accounts, which are funded with money you have already paid tax on.",
    why: "Having both pre-tax and Roth balances lets you choose in retirement which to draw from, smoothing your tax bill across years.",
    appliesTo: "Anyone saving for retirement, especially earlier in their career."
  },
  {
    id: "gifting_shares",
    name: "Give appreciated shares, not cash",
    what: "When donating, transferring an appreciated stock can beat selling it first and donating the cash.",
    why: "Donating shares to charity can skip the capital-gains tax entirely while still counting the full value — more reaches the cause, less goes to tax.",
    appliesTo: "Anyone who donates to charity and holds appreciated positions."
  }
];

export type GlideStage = {
  label: string;
  ageRange: string;
  stocksPct: number;
  bondsPct: number;
  note: string;
};

// A plain illustration of how an age-based glide path — the model 529 plans
// and KINDRIP's Auto mode both use — shifts a child's money over time.
export const GLIDE_PATH_STAGES: GlideStage[] = [
  {
    label: "Early years",
    ageRange: "Age 0-5",
    stocksPct: 90,
    bondsPct: 10,
    note: "Decades until the money is needed — almost all in stocks, where time smooths out the bumps."
  },
  {
    label: "Grade school",
    ageRange: "Age 6-11",
    stocksPct: 70,
    bondsPct: 30,
    note: "Still growth-focused, but starting to add bonds as ballast."
  },
  {
    label: "Middle / high school",
    ageRange: "Age 12-16",
    stocksPct: 45,
    bondsPct: 55,
    note: "College is close — the mix tilts toward bonds to protect what has been built."
  },
  {
    label: "College doorstep",
    ageRange: "Age 17-18",
    stocksPct: 25,
    bondsPct: 75,
    note: "Mostly bonds and cash, so a bad market year right before tuition cannot undo years of saving."
  }
];

export type MatchResult = {
  salary: number;
  contributionPct: number;
  employeeContribution: number;
  employerMatch: number;
  fullPotentialMatch: number;
  leftOnTable: number;
  capturingFullMatch: boolean;
};

// The "free money" math on an employer-matched retirement account.
export function employerMatchValue(
  salary: number,
  contributionPct: number,
  matchRatePct: number,
  matchCapPct: number
): MatchResult {
  const s = Math.max(0, salary || 0);
  const contrib = Math.max(0, Math.min(contributionPct || 0, 100));
  const rate = Math.max(0, matchRatePct || 0) / 100;
  const cap = Math.max(0, Math.min(matchCapPct || 0, 100));

  const employeeContribution = s * (contrib / 100);
  const matchedPct = Math.min(contrib, cap);
  const employerMatch = s * (matchedPct / 100) * rate;
  const fullPotentialMatch = s * (cap / 100) * rate;
  const leftOnTable = Math.max(0, fullPotentialMatch - employerMatch);

  return {
    salary: s,
    contributionPct: contrib,
    employeeContribution: Math.round(employeeContribution),
    employerMatch: Math.round(employerMatch),
    fullPotentialMatch: Math.round(fullPotentialMatch),
    leftOnTable: Math.round(leftOnTable),
    capturingFullMatch: cap === 0 || contrib >= cap
  };
}

// A plain-language read of a MatchResult.
export function matchSummary(r: MatchResult): string {
  if (r.fullPotentialMatch <= 0) {
    return "No employer match is set up. If your job offers one, it is free money worth capturing.";
  }
  if (r.capturingFullMatch) {
    return `You are capturing the full employer match — about $${r.employerMatch.toLocaleString()} a year of free money, on top of what you put in yourself.`;
  }
  return `You are getting about $${r.employerMatch.toLocaleString()} a year in employer match, but leaving about $${r.leftOnTable.toLocaleString()} on the table. Contributing up to your match cap would capture the full $${r.fullPotentialMatch.toLocaleString()}.`;
}

// Withholding: a paycheck has tax withheld automatically; trading gains do not.
export function withholdingNote(
  estimatedAnnualGains: number,
  setAsidePct: number
): string {
  const gains = Math.max(0, estimatedAnnualGains || 0);
  const pct = Math.max(0, setAsidePct || 0);
  const setAside = Math.round(gains * (pct / 100));
  return (
    `Your paycheck has taxes withheld automatically, but trading gains do not. ` +
    `On about $${Math.round(gains).toLocaleString()} of expected gains, setting aside ` +
    `roughly $${setAside.toLocaleString()} (about ${pct}%) keeps you clear of a ` +
    `surprise bill at tax time. Trezo's Tax Optimizer already tracks this for you.`
  );
}

// KINDRIP child-account contributions — the plain-language tax angle.
export function childAccountTaxNote(
  contributedYtd: number,
  totalContributed: number,
  childCount: number
): string {
  if (childCount <= 0) {
    return (
      "No KINDRIP child accounts yet. Money set aside in a child's Future " +
      "Index Account grows tax-advantaged — its gains are not taxed year to " +
      "year the way trading gains are. The KINDRIP page is where you start one."
    );
  }
  const ytd = Math.max(0, contributedYtd);
  const total = Math.max(0, totalContributed);
  if (ytd <= 0) {
    return (
      `You have ${childCount} child account${childCount === 1 ? "" : "s"} set up` +
      (total > 0
        ? `, with $${Math.round(total).toLocaleString()} contributed so far`
        : "") +
      ". No new money has moved across yet this year. When it does, it leaves " +
      "your taxable trading balance and grows tax-advantaged inside the account."
    );
  }
  return (
    `So far this year, $${Math.round(ytd).toLocaleString()} has moved into your ` +
    `child account${childCount === 1 ? "" : "s"}. That money leaves your taxable ` +
    "trading balance and grows tax-advantaged inside the Future Index Account — " +
    "its gains are not taxed year to year the way trading gains are. " +
    "Contributions are made with after-tax dollars (there is no federal " +
    "deduction), but many states give a tax deduction or credit on 529 " +
    "contributions, so it is worth checking your state's rules."
  );
}
