# TREZO — TAX STRATEGIES SPEC

## Purpose
A profitable trader can pay vastly different amounts of tax depending on their tax structure. This document specifies the advanced tax strategies the Tax Optimizer Agent will help users navigate, based on US tax code provisions for active traders.

**Disclaimer:** Trezo provides educational information about tax strategies. Users must consult a qualified CPA before making any tax election. This is not tax advice.

---

## THE FOUR TAX STRATEGY LEVELS

### Level 1: Default Investor Status (Worst for Active Traders)

This is what every trader starts as without taking action.

**Characteristics:**
- Trades classified as capital gains/losses
- Short-term gains taxed as ordinary income
- Long-term gains taxed at favorable LTCG rates (0%, 15%, 20%)
- Losses limited to **$3,000/year** against ordinary income
- Excess losses carry forward at $3,000/year
- **Wash sale rules apply** (disallowed losses on repurchases within 30 days)
- No deduction for trading-related expenses

**Problem for active traders:**
If you have a $50,000 trading loss in a year, you can only deduct $3,000 against your income. The remaining $47,000 carries forward at $3,000/year — taking nearly 16 years to fully deduct.

---

### Level 2: Trader Tax Status (TTS)

A designation under Section 162 of the IRS code that recognizes trading as a business activity.

**Qualification Requirements:**
- Trade frequently (typically 4+ days per week, hundreds of trades/year)
- Trade with the intention of profiting from short-term price movements
- Spend significant time analyzing markets (typically 4+ hours/day)
- Trading must be substantial and continuous

**Benefits:**
- Trading-related expenses become deductible
  - Education courses
  - Trading platform fees
  - Data subscriptions
  - Home office (% allocation)
  - Equipment (computer, monitors)
  - Internet and phone (% allocation)
- Schedule C treatment for expenses

**Limitations:**
- Still subject to wash sale rules
- Still limited to $3,000 capital loss deduction
- Self-employment tax may apply

**When to elect:**
- After confirming you meet criteria with CPA
- Filed with annual tax return
- Can be claimed retroactively for current year

---

### Level 3: Mark-to-Market Accounting (Section 475(f))

The single most powerful tax election for active traders. Treats unrealized gains/losses as if positions were sold on December 31.

**Election Requirements:**
- Must qualify for Trader Tax Status first
- File **Form 3115** (Application for Change in Accounting Method)
- Election deadline: **April 15 of the year you want it active**
- Cannot be applied retroactively
- Notify your broker after filing

**Benefits:**
- **Unlimited loss deduction** against ordinary income
  - Lost $200,000 trading? Deduct the full $200,000 (not just $3,000)
- **No wash sale rules** for traders under 475(f)
- Cleaner tax reporting
- Carry-forward losses can offset future ordinary income

**Trade-offs:**
- Year-end positions are "marked" to market prices
- Phantom income possible (unrealized gains taxed)
- Phantom losses possible (offset by phantom gains)
- Permanent change (difficult to revoke)

**The math example from the source:**
```
Scenario: Made $50K from W-2, lost $15K trading
                            
Without 475(f):
  Taxable income: $50K - $3K = $47K
  Carry forward: $12K (4 years at $3K/year)

With 475(f):
  Taxable income: $50K - $15K = $35K
  Immediate full deduction
  Tax savings: $12K x marginal rate
  At 22% bracket: $2,640 saved this year alone
```

---

### Level 4: LLC / S-Corp Trading Business

The ultimate tax structure for traders earning significant profit. Combines TTS + 475(f) + business entity benefits.

**Structure:**
- Form an LLC or S-Corp (single-member or multi-member)
- Open business bank account
- Open business brokerage account
- Open business credit card
- Segregate all trading expenses to business

**Benefits Beyond Level 3:**

**1. Solo 401(k) Contributions**
- Up to $69,000/year (2024) in tax-deferred retirement savings
- Combined employer/employee contributions
- Roth option available for tax-free growth
- Loans available against balance

**2. Health Insurance Premium Deduction**
- 100% of health insurance premiums deductible
- Including dental and vision
- Including dependents

**3. Home Office Deduction**
- Dedicated office space deductible
- Includes utilities, internet, % of rent/mortgage interest

**4. Business Travel and Meals**
- Trading conferences (50% meals, 100% travel)
- Meeting with mentors/advisors
- Educational events

**5. Equipment and Software**
- Full deduction for computers, monitors, software
- Section 179 immediate expensing available

**Considerations:**
- Setup costs ($500-$2,000)
- Annual filing requirements
- Separate tax return required (1120-S for S-Corp)
- CPA fees increase ($1,500-$5,000/year)
- Only worthwhile above certain profit threshold

**When to elect:**
- Annual trading profit > $75,000
- Want retirement savings beyond IRA limits
- Have health insurance costs to deduct
- Plan to continue trading long-term

---

## TREZO TAX OPTIMIZER AGENT — IMPLEMENTATION

The Tax Optimizer Agent helps users navigate these strategies:

### Phase 1 Capabilities (Observe Only)
- Track all trades with tax classification
- Calculate realized gains/losses YTD
- Project tax liability based on current status
- Flag wash sales (for users without 475(f))

### Phase 2 Capabilities (Suggest)
- Recommend tax-loss harvesting opportunities
- Suggest 475(f) election if user qualifies
- Calculate potential savings of each election
- Generate questions for CPA conversation

### Phase 3 Capabilities (Active Optimization)
- Time trades for tax efficiency
- Manage wash sales proactively (when applicable)
- Generate quarterly estimated tax calculations
- Prepare year-end tax documents
- Suggest entity structuring when appropriate

---

## QUARTERLY ESTIMATED TAX

Active traders generally must pay quarterly estimated taxes to avoid underpayment penalties.

**Due Dates:**
- Q1: April 15
- Q2: June 15
- Q3: September 15
- Q4: January 15 (following year)

**Safe Harbor Rules:**
To avoid underpayment penalty, pay the smaller of:
1. 90% of current year's tax liability, OR
2. 100% of last year's tax liability (110% if AGI > $150K)

**Trezo Calculation:**
Tax Optimizer Agent maintains a running tax ledger and recommends quarterly payment amounts before each due date.

---

## STATE TAX CONSIDERATIONS

Federal tax is only half the story. State tax treatment varies dramatically.

**Best States for Active Traders (no state income tax):**
- Florida, Texas, Tennessee, Nevada, Wyoming, Washington, South Dakota, Alaska, New Hampshire

**Mid-tier:**
- Most states (4-7% on trading gains)

**Worst States for Active Traders:**
- California (up to 13.3%)
- New York (up to 10.9%)
- New Jersey (up to 10.75%)
- Hawaii (up to 11%)

Founder is in **New Jersey** — state tax planning is meaningful here. The Tax Optimizer Agent will factor NJ tax (10.75% top rate) into all projections.

---

## SPECIFIC SCENARIOS FOR FOUNDER

Based on founder's profile (single filer, ~$30K income, NJ resident):

### Current Year (2025-2026):
- **Income bracket:** 12% federal, ~5.5% NJ
- **LTCG rate:** 0% federal (under $44K), 5.5% NJ
- **Recommendation:** Hold profitable positions > 1 year when possible — 0% federal LTCG

### If Trading Increases (2026-2027):
- Watch for TTS qualification thresholds
- Consider 475(f) election by April 15
- Track all trading-related expenses

### If Income Grows to $75K+ (2027-2028):
- Evaluate LLC formation
- Solo 401(k) becomes powerful
- Health insurance deduction increases value

### If Trading Income > $100K (Future):
- Full S-Corp structure recommended
- CPA partnership essential
- Quarterly tax planning meetings

---

## KEY FORMS & FILINGS

| Form | Purpose | When |
|---|---|---|
| Schedule D | Capital gains/losses | Annual |
| Form 8949 | Detail of trades | Annual |
| Schedule C | Business income/expenses (TTS) | Annual |
| Form 3115 | 475(f) election | Before April 15 |
| Form 1040-ES | Quarterly estimates | 4x/year |
| Form 4868 | Extension request | April 15 |
| Form 1120-S | S-Corp return | March 15 |
| Form 4562 | Depreciation (equipment) | Annual |

---

## BEGINNER MISTAKES TO AVOID

From the day trading guide, the tax-related mistakes:

1. **Not tracking expenses** — Lost deductions = paid more tax
2. **Missing wash sales** — Disallowed losses surprise at tax time
3. **Late 475(f) election** — Must file by April 15
4. **No quarterly payments** — Penalty + interest accrues
5. **Mixing personal and business** — IRS audit risk
6. **DIY tax filing** — Active trader returns are complex

---

## TREZO'S DEFAULT ASSUMPTIONS

For the founder's account at start:

```
TAX_SETTINGS_FOUNDER = {
    'filing_status': 'single',
    'state': 'NJ',
    'estimated_annual_income': 30000,
    'trader_tax_status': False,  # Will qualify with bot activity
    'mark_to_market': False,     # User decision Phase 3
    'business_entity': None,      # Future consideration
    'estimated_quarterly_payment': 'calculated_dynamically',
    'wash_sale_tracking': True,
    'cost_basis_method': 'FIFO',  # Default; can change to specific lot
}
```

---

## EDUCATIONAL CONTENT FOR USER

The User Support Agent provides on-demand education about:
- "What is wash sale and how does it affect me?"
- "Should I make the mark-to-market election?"
- "When does TTS qualification kick in?"
- "How do I calculate my quarterly estimate?"
- "Is forming an LLC worth it for my situation?"

All explanations include calculator examples using the user's actual numbers.

---

## INTEGRATION WITH OTHER TREZO COMPONENTS

| Component | Tax Integration |
|---|---|
| Trade Execution Agent | Tags every trade with cost basis lot |
| Pattern Detection | Considers tax holding period for swing trades |
| Daily Profit Lock | Vault tracks taxable vs tax-free distributions |
| Credit Spreads | Generates short-term gains (separate tracking) |
| Dividend Wheel | Qualified vs non-qualified dividend tracking |
| YieldMax | Distribution income tracking (often ROC) |
| KINDRIP | UTMA/UGMA tax implications for child accounts |

---

## CPA INTEGRATION (FUTURE)

In a later phase, Trezo will offer:
- Direct export to CPA-friendly formats
- Schedule K-1 generation for partnerships
- 1099-B reconciliation tools
- CPA collaboration portal
- Recommended CPA network (vetted for trader expertise)

---

## END OF TAX STRATEGIES SPEC
