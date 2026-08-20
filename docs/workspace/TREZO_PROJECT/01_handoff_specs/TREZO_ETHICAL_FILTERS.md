# TREZO — ETHICAL FILTERS SPEC

## Purpose
Trezo respects the founder's stated value: *"I do not have a specific sector in mind maybe those against humanity like racist or fascist companies."*

This document specifies how Trezo screens investments against ethical violations. The user has full control — defaults are conservative, all categories are toggleable.

---

## CORE PRINCIPLE

> **A treasure built on the backs of others isn't a treasure — it's a debt.**

Trezo's Woven Basket philosophy is about protection. We don't profit from companies that actively cause harm to humanity.

---

## DEFAULT EXCLUSIONS (Always On)

These are non-negotiable and built into the system. The bot will never recommend, scan, or execute trades on companies meeting these criteria:

### Tier 1: Human Rights Violations
- Companies on the **SAM.gov System for Award Management** exclusion list
- Companies named in active **OFAC sanctions**
- Companies with **adjudicated** (not alleged) human rights violations
- Companies operating in **state-sponsored forced labor** supply chains (per US Customs WRO list)

### Tier 2: Discrimination & Hate
- Companies with **active EEOC class-action settlements** related to race/religion/gender discrimination (within last 5 years)
- Companies named in **Southern Poverty Law Center hate group** financial connections
- Companies whose executives have made **on-record statements** advocating violence against protected classes

### Tier 3: Fraud & Predatory Conduct
- Companies under active **SEC fraud investigation** with substantial cause
- Companies on **FINRA permanent bar** lists
- Companies with **state attorney general** lawsuits for predatory consumer practices

---

## USER-TOGGLEABLE EXCLUSIONS

Beyond defaults, the user can opt to exclude additional categories:

```
TREZO ETHICAL FILTER SETTINGS
─────────────────────────────────────────────
☐ Tobacco companies (MO, PM, BTI, etc.)
☐ Weapons manufacturers (LMT, RTX, NOC, GD, etc.)
☐ Fossil fuel majors (XOM, CVX, BP, SHEL, etc.)
☐ Private prisons (GEO, CXW)
☐ Gambling companies (already kept ON for this user — CZR/MGM)
☐ Predatory lending (payday loan operators)
☐ Animal testing (cosmetics, beauty)
☐ Adult entertainment
☐ Cannabis (regulatory risk varies by state)
☐ Cryptocurrency mining (energy concerns)
─────────────────────────────────────────────
```

**Founder's current preferences (from conversation):**
- Defaults: ON
- Optional categories: All OFF (founder wants flexibility, especially gambling since CZR is a top winner)

---

## DATA SOURCES & VERIFICATION

Trezo cross-references these authoritative sources:

| Source | URL | Updated |
|---|---|---|
| SAM.gov Exclusions | sam.gov/exclusions | Daily |
| OFAC SDN List | treasury.gov/ofac | Daily |
| SEC EDGAR Enforcement | sec.gov/litigation | Daily |
| FINRA BrokerCheck | finra.org/brokercheck | Daily |
| US Customs WRO List | cbp.gov/trade/forced-labor | Weekly |
| EEOC Press Releases | eeoc.gov/newsroom | Weekly |
| State AG Consumer Actions | naag.org | Weekly |

**Trezo does NOT use:**
- Subjective ESG ratings (MSCI, Sustainalytics) — too easily gamed
- Political donation databases — beyond scope
- Activist campaign targeting — too partisan
- Boycott lists from advocacy groups — too partisan

We use **legal and regulatory records only.** This keeps the filter objective and defensible.

---

## TECHNICAL IMPLEMENTATION

### Database Schema
```sql
CREATE TABLE ethical_exclusions (
  id SERIAL PRIMARY KEY,
  ticker VARCHAR(10) NOT NULL,
  exclusion_category VARCHAR(50) NOT NULL,
  source VARCHAR(100) NOT NULL,
  source_url TEXT,
  source_date DATE NOT NULL,
  evidence TEXT,
  tier INTEGER NOT NULL,  -- 1, 2, or 3
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW(),
  reviewed_at TIMESTAMP
);

CREATE INDEX idx_ethical_ticker ON ethical_exclusions(ticker);
CREATE INDEX idx_ethical_active ON ethical_exclusions(active);
```

### Filter Check Function (Pseudocode)
```python
def passes_ethical_filter(ticker: str, user_settings: dict) -> tuple[bool, str]:
    """
    Returns: (passes, reason_if_excluded)
    """
    # Always check defaults
    default_exclusions = db.query("""
        SELECT exclusion_category, evidence 
        FROM ethical_exclusions 
        WHERE ticker = %s AND active = true AND tier IN (1, 2, 3)
    """, ticker)
    
    if default_exclusions:
        return False, f"Default exclusion: {default_exclusions[0].evidence}"
    
    # Check user opt-in categories
    if user_settings.get('exclude_tobacco') and ticker in TOBACCO_TICKERS:
        return False, "User excluded: tobacco category"
    
    if user_settings.get('exclude_weapons') and ticker in WEAPONS_TICKERS:
        return False, "User excluded: weapons category"
    
    # ... etc for each user category
    
    return True, ""
```

### Integration Points

**1. Watchlist Screening**
Before any ticker enters the user's watchlist, it passes through `passes_ethical_filter()`. Failed tickers are blocked with a clear message:

```
⚠️ Ticker XYZ cannot be added to watchlist.
Reason: Company on active SAM.gov exclusion list
since 2023-08-15 for human trafficking violations.

[ View Source ] [ Override (not recommended) ]
```

**2. Pre-Trade Check**
Every trade goes through the filter immediately before execution:

```python
def execute_trade(ticker, side, qty, price):
    passes, reason = passes_ethical_filter(ticker, user_settings)
    if not passes:
        log_blocked_trade(ticker, reason)
        notify_user(f"Trade blocked: {reason}")
        return TradeResult(success=False, blocked=True, reason=reason)
    
    # Continue with normal execution
    return broker.submit_order(...)
```

**3. Strategy Discovery Agent**
When the Strategy Discovery Agent suggests new tickers to add, ethical filter runs first. Excluded tickers never appear as suggestions.

---

## USER OVERRIDE MECHANISM

The user can manually override the filter for any ticker (except Tier 1 violations, which are hard-blocked).

```
OVERRIDE FLOW:
─────────────────────────────────────────────
1. User attempts to add excluded ticker
2. System displays exclusion reason + evidence
3. User clicks "Override (not recommended)"
4. System asks: "Why are you overriding?"
   [ Free text field ]
5. Override logged with timestamp and reason
6. Ticker added to watchlist with permanent ⚠️ flag
7. All trades on this ticker carry a footer note
─────────────────────────────────────────────
```

**Tier 1 exclusions cannot be overridden.** This is a hard line.

---

## TRANSPARENCY

Every excluded ticker comes with:
- The specific category triggered
- The source (SAM.gov, SEC, etc.)
- The date the exclusion was recorded
- A direct link to the source document
- The evidence summary

Users are never told "blocked" without a reason. Trust is built on transparency.

---

## REVIEW & UPDATES

- Exclusion database refreshes daily from authoritative sources
- Tickers can be **removed from exclusion** if a company resolves the issue
- Annual review by the Trezo team of category definitions
- User feedback channel to report missing exclusions or false positives

---

## CONNECTING BACK TO THE WOVEN BASKET

The philosophy says: *"the love tries to keep whatever it is protecting safe, layer after layer."*

The Ethical Filter is one of those layers. It protects:
- The user's conscience
- The user's children (KINDRIP inheritance)
- The communities affected by the companies we choose not to fund
- The integrity of the wealth being built

A treasure built ethically is a treasure that can be passed down without shame.

---

## FOR CLAUDE CODE — BUILD NOTES

When implementing this:

1. **Build the exclusion database first** — seed with current SAM.gov data
2. **Build daily sync job** — pulls updates from official sources
3. **Add filter check to all trade entry points** — watchlist add, scanner, execution
4. **Build user settings UI** — toggleable categories
5. **Build override flow** — with logging
6. **Build transparency UI** — exclusion reason display
7. **Add unit tests** — for each filter category

---

## END OF ETHICAL FILTERS SPEC
