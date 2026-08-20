# TREZO — FOUNDER WATCHLIST

## Purpose
A pre-loaded, calibrated watchlist built from analysis of the founder's actual trading history (60+ positions across 2024-2025). The user can customize, add, or remove anything — this is the starting template, not a constraint.

---

## CORE WINNERS — Track Aggressively

These are tickers where the founder has demonstrated consistent profitability:

| Ticker | Company | Realized P&L | Why It's Here |
|---|---|---|---|
| CZR | Caesars Entertainment | +$551.05 | Best options performer. Patient scaling in/out on calls |
| WMT | Walmart | +$417.32 | Stable swing trades |
| INTC | Intel Corp | +$295.40 | ITM/near-money calls held through moves |
| AMD | Advanced Micro Devices | +$212.80 | Semiconductor conviction plays |
| AMSC | American Superconductor | +$169.92 | Momentum capture |
| STAFQ | Staffing 360 | +$147.65 | Small-cap winner |
| GM | General Motors | +$86.88 | Conservative wins |
| RBLX | Roblox Corp | +$72.42 | Gaming sector strength |
| CSCO | Cisco Systems | +$70.87 | Reliable mid-cap |
| MRK | Merck & Co | +$69.88 | Healthcare stability |
| PTON | Peloton (stock) | +$91.00 | Recovery play |
| ZOMDF | Zomedica Corp | +$65.98 | Penny stock win |
| PYPL | Paypal Holdings | +$43.74 | Fintech swing |

**Trezo Behavior:** Bot prioritizes pattern detection on these names. They go in the daily scan loop. When STMS signals fire on these symbols, position size can be 100% of normal allocation (other names require A-grade signal).

---

## DIVIDEND ENGINE — YieldMax Portfolio

The dividend layer. All current holdings are profitable:

| Ticker | Company | Realized P&L | Shares |
|---|---|---|---|
| AIYY | YieldMax AI Option Income | +$676.38 | 455 |
| AMZY | YieldMax AMZN Option Income | +$235.63 | 224 |
| TSLY | YieldMax TSLA Option Income | +$225.37 | 100 |
| GOOY | YieldMax GOOGL Option Income | +$212.95 | 200 |
| NVDY | YieldMax NVDA Option Income | +$212.69 | 200 |

**Watchlist additions for diversification:**
- AMDY (YieldMax AMD)
- ULTY (YieldMax Ultra Income)
- MSTY (YieldMax MSTR)
- CONY (YieldMax COIN)
- YMAX (YieldMax Universe ETF)

**Trezo Behavior:**
- NAV Health Monitor tracks each position for distribution erosion
- Auto-rebalance if any single YieldMax exceeds 40% of dividend layer
- Distribution income tracked and feeds the Daily Profit Lock vault
- Target weekly distribution income: $250

---

## PENNY STOCK STMS POOL — Small Trades Momentum Strategy

Founder has demonstrated success on penny stock momentum plays:

| Ticker | Company | Realized P&L |
|---|---|---|
| STAFQ | Staffing 360 | +$147.65 |
| NVIVQ | Invivo Therapeutics | +$51.90 |
| ZSANQ | Zosano Pharma | +$23.29 |
| XWEL | XWELL Inc | +$20.32 |
| ZNB | Zeta Network Group | +$18.67 |
| JAGX | Jaguar Health | +$18.22 |
| SDIG | Stronghold Digital | +$9.53 |
| GSAT | Globalstar | +$36.68 |
| ACHR | Archer Aviation | +$38.95 |

**Trezo Behavior:**
- STMS scanner runs 7:00 AM – 11:00 AM ET on these and similar small caps
- Maximum position size: 3% of stock account
- Hard stop at -8%
- Profit target tiers: 5%, 10%, 20% (scale out 1/3 at each)
- Time stop: close by 11:00 AM regardless of position

---

## SECTOR WATCH — Demonstrated Zones of Strength

Based on win/loss patterns, these are the sectors where the founder has an edge:

### Semiconductors (Strong Edge)
**Track:** AMD, INTC, NVDA, AMSC, SMCI, AVGO, TSM, MU, ON, MRVL, QCOM
**Note:** Founder's win rate in this sector is highest. Pattern Detection Agent should weight semiconductor signals higher.

### Gaming / Casino / Leisure (Mixed — Trade Carefully)
**Track:** CZR (winner), RBLX (winner), MGM (caution), DKNG (caution), PENN, LVS, WYNN
**Note:** CZR and RBLX have produced wins. MGM and DKNG have produced losses. Bot should be cautious on the latter pair — require stronger signals.

### Fintech (Mixed)
**Track:** SOFI (mixed), PYPL (winner), V, MA, JPM, BAC, SQ, AFRM, COF (caution)
**Note:** SOFI stock is profitable, SOFI options have been losses. Bot should favor wheel strategy (covered calls on stock) over directional options.

### EV / Auto (Cautious Edge)
**Track:** F (winner), GM (winner), RIVN (slight loss), TSLA, NIO (avoid)
**Note:** Domestic auto OK. Avoid Chinese EV plays.

### Health / Biotech (Selective Wins)
**Track:** PFE (winner), MRK (winner), JAGX (winner), NVIVQ (winner), MRNA, ABBV
**Note:** Founder wins on established pharma and select biotech penny stocks.

### Retail (Stable Wins)
**Track:** WMT (best performer), COST, TGT, AMZN, HD, LOW
**Note:** Brick-and-mortar large caps are reliable for this founder.

---

## ⚠️ CAUTION LIST — Reduce Position Size or Require A+ Signal

Tickers where the founder has lost money. Bot can still trade these but with extra caution:

| Ticker | Loss | Caution Note |
|---|---|---|
| SOUN | -$1,079.92 | **AVOID OPTIONS.** AI hype name. Highest loss in account. |
| AAPL | -$377.63 | Mega-cap reversal trap. Stock holds OK, options dangerous. |
| BABA | -$360.53 | Chinese ADR — avoid in general per founder pattern |
| MGM | -$258.44 | Casino sector — winner CZR available instead |
| SOFI Options | -$238.94 | Wheel strategy preferred over directional |
| NAK | -$196.42 | Mining junior — speculative penny |
| COF | -$150.51 | Banking — large cap competitors preferred |
| NOK Options | -$136.10 | Stock OK, options drain — wheel strategy only |
| DKNG | -$92.12 | Sports betting — CZR preferred for gaming exposure |

**Trezo Behavior:**
- These appear in scans with a yellow warning flag
- Position size automatically reduced by 50%
- Require A+ pattern confidence score (8.5+ out of 10) to enter
- Mandatory time stop applied

---

## 🚫 SOFT AVOID LIST — Default Off (User Can Re-enable)

Based on demonstrated weakness patterns:

| Category | Examples | Reason |
|---|---|---|
| Chinese ADRs | BABA, NIO, JD, BIDU, PDD | Regulatory + delisting risk + founder's loss pattern |
| AI Hype Names | SOUN, BBAI, PATH (pre-pump) | Volatility traps that have hurt founder |
| SPAC Reversions | (varies) | Generally avoid post-merger SPACs |
| OTC/Pink Sheet | (varies) | Liquidity risk |

**These are default OFF in scanning. User can manually add any of these to active watchlist anytime.**

---

## USER CUSTOMIZATION

The watchlist UI allows:

1. **Add ticker** — Type any symbol, Trezo verifies it's tradeable
2. **Remove ticker** — Click X to drop from watchlist
3. **Create custom list** — User-named groups (e.g., "My Earnings Plays", "Q4 Watchlist")
4. **Import from CSV** — Bulk add from spreadsheet
5. **Import from broker** — Sync with Webull watchlist via API
6. **Star favorites** — Pin most-watched to top of scanner
7. **Set per-ticker rules** — Custom position sizing for specific names
8. **Notes field** — User can add context to any ticker

---

## STRATEGY DISCOVERY AGENT — Watchlist Suggestions

In Phase 3, the Strategy Discovery Agent will analyze the user's actual win/loss patterns and suggest additions:

```
EXAMPLE SUGGESTIONS:
─────────────────────────────────────────────
"You've won on 4 of 5 semiconductor swing trades.
Consider adding: MU, ON, MRVL — similar setups."

"Your wins cluster on stocks priced $20-$60.
Consider adding: PLAY, BBWI, CNC — similar profile."

"You've avoided energy entirely.
Sector is showing your favored patterns.
Suggest watching: XOM, CVX, DVN for paper trades."
─────────────────────────────────────────────
```

User accepts/rejects each suggestion. Bot learns from rejections.

---

## INTEGRATION WITH OTHER AGENTS

| Agent | How It Uses Watchlist |
|---|---|
| Pattern Detection | Scans watchlist tickers every 60s during market hours |
| Risk Manager | Applies caution flags from this document |
| Trade Execution | Only executes on watchlist tickers (unless user manually overrides) |
| Market Sentiment | Pulls news + social sentiment for watchlist names first |
| Strategy Discovery | Suggests new tickers based on win patterns |
| Tax Optimizer | Tracks cost basis per ticker for tax-loss harvesting |

---

## DATA SOURCES FOR WATCHLIST INFO

- **Real-time quotes:** Finnhub API
- **Fundamentals:** Finnhub company profile endpoint
- **News:** Finnhub news + RSS aggregation
- **Options chain:** Finnhub options endpoint
- **ESG screening:** SAM.gov + SEC enforcement records (cross-referenced)
- **Earnings dates:** Finnhub earnings calendar

---

## END OF FOUNDER WATCHLIST SPEC
