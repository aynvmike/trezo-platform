# Trezo Midday Snapshot — Monday, July 13, 2026 (~12:10 PM ET)

## Market clock
🟢 Open. Today's session 9:30 AM – 4:00 PM ET; no holidays or early closes this week.

## Account health (Alpaca paper — PA3PR4F6ZFWZ)
- Equity **$4,734.81** (up $17.78 from Friday's close) · Cash $1,526.93
- Buying power $4,165.82 margin / **$657 non-marginable** (this is what crypto can spend — see the flag below)
- Options approval level 3 · No account, trading, or transfer blocks · Day-trade count not reported by the paper API
- Account is fine — the small non-marginable cash number matters because crypto buys can only use that slice.

## Today's orders (6 at the broker)
- **Filled (4):** three ETH buys ~9:24–9:29 AM (total ~1.20 ETH ≈ $2,121 @ ~$1,768.6) + PYPL profit-ladder sell of 7 shares @ $47.43 (~+$9.6 realized)
- **Working (2):** PYPL bracket on the remaining 8 shares — a stop (held) and a take-profit limit (open). Normal.
- **Rejected at the broker (3, ~12:04 PM):** ETH, DOGE, LINK adds — "insufficient balance: requested ~$725, available ~$657." Real rejects: the engine sized ~$725 against $657 of crypto-spendable cash.

## Open positions (5 — books match broker)
| Position | Qty | Entry → Now | P&L |
|---|---|---|---|
| ETHUSD | 1.199 | $1,768.59 → $1,774.25 | +$6.79 (+0.3%) |
| PYPL | 8 sh | $46.05 → $47.01 | +$7.68 (+2.1%) |
| SPDN (hedge) | 82 sh | $8.63 → $8.63 | +$0.12 |
| BITO | 1 sh | $8.64 → $8.48 | −$0.17 |
| F 7/31 $12.50 put (CSP) | −1 | $0.27 → $0.12 | +$15.00 (+56%) |

HPQ 20.5P and F 13P are gone — the queued buy-backs from 7/8 executed, freeing collateral. Only the F 12.5P remains, and it's most of the way to max profit.

## Today's P&L
Realized ~+$9.6 (PYPL ladder). Unrealized today: ETH +$6.79, PYPL +$5.52, SPDN +$3.40, BITO −$0.20. Net day so far ≈ **+$18**.

## Scan / gate detail (activity ledger — 434 entries, live as of 12:09 PM)
- **8 approvals** (all crypto: ETH ×4, ALGO, HBAR, DOGE, LINK; TCS 45–49 under coverage-mode floor 40) · **193 vetoes** · 124 wheel-limit gates · 26 wheel-collateral-cap gates
- Top veto reasons: neutral direction / no bias (62), already-holding stacking guards on EURUSD/BITO/PYPL (70 combined), **session kill-switch (15)**, thin liquidity (2)
- Cross-check: approvals did convert to fills this morning (3 ETH), the 12:04 batch hit the balance rejects above.

## ⚠️ Two things worth knowing (report only — no changes made)
1. **False-reject kill-switch.** The three ETH orders that FILLED at 9:24–9:29 were also logged as broker rejects ("unexpected_response" with a full order payload) — the engine mis-read successful crypto order responses. Three phantom rejects tripped the session kill-switch at 9:30, which then vetoed new entries ~9:30 AM–12:05 PM (15 vetoes). Exits and ladders kept working (PYPL sell at 9:35 went through — kill-switch only blocks entries, by design).
2. **Crypto sizing ignores non-marginable buying power.** The 12:04 adds asked ~$725 with only $657 crypto-spendable. The notional cap appears to size against equity/margin BP, not the non-marginable slice.

Both are after-hours fix candidates for Nova — no code or config changes during market hours.

## Verdict
The bot is **healthy and actively trading**: scanners running, crypto lane filling, profit ladder banked PYPL gains, exits and brackets working, books match the broker 5-for-5, and the day is green (~+$18). The one blemish: a response-parsing bug made winning ETH fills look like rejects and froze *new* entries for ~2.5 hours mid-morning; crypto adds are also sizing slightly past their spendable cash. If the halt is still on this afternoon, you can clear it safely with:
[PowerShell] `Invoke-RestMethod -Method Post http://localhost:8001/admin/clear-session-halt`
Then ask Nova after 4 PM ET to fix the crypto order-response parsing and the crypto sizing cap.
