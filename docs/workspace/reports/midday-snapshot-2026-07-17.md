# Trezo Midday Snapshot — Friday, July 17, 2026 (~12:10 PM ET)

**Verdict: HEALTHY AND ACTIVELY TRADING.** The bot exited five positions this morning, opened four new protected ones, closed out the F put for pennies, and the ETH trail stop fired overnight exactly as designed. Day so far: **+$15.00 (+0.31%)**.

## Market clock
Market is OPEN (regular session 9:30–4:00 ET). Closes in ~3h50m. No holidays or early closes in the next week; next open after today is Monday 7/20.

## Account health
Equity **$4,851.94** (vs $4,836.95 at yesterday's close). Cash $1,975.51. Buying power $15,956 (margin) / $3,396.84 for options. Options approval level 3. No trading, account, or transfer blocks. Account is ACTIVE and ready to trade — and clearly is trading.

## Today's orders (12 top-level, 19 fills)
- **Overnight:** ETH/USD sold 0.3993 @ $1,855.70 — the continuous profit trail (stop ratcheted to $1,856.36 yesterday) executed with ~$0.66 slippage. The locked-in gain banked as designed. Crypto book now flat.
- **At the bell (9:30):** F $12.50 put (7/31) bought back @ $0.09 — this is the harvest buy-back that expired unfilled Wednesday; the re-arm fix from yesterday's build worked on its first try. Options book now flat.
- **Morning exits:** SPDN 82 sh @ $8.75, RBLX 12 sh @ ~$52.27, XLE 12 sh @ ~$57.75–$58.01 (two lots), WMT 1 sh @ $118.06.
- **New entries (all bracketed):** ATAI 96 @ $7.13, F 48 @ $14.18, CSCO 6 @ $111.34, DRAM 8 @ $54.73 (noon).
- **Fast profit take:** half the F position (24 sh) sold @ $14.48 within 11 minutes = +$7.20 realized; remaining 24 sh rides with target $14.69 + held stop.
- Rejects: none. The 2 canceled orders were old protective legs correctly canceled before their positions were exited (RBLX stop, XLE stop/limit pair).

## Open positions (8, all stocks — no discrepancies)
CSCO 6 (+$5.46), F 24 (+$5.28), ATAI 96 (+$4.20), DRAM 8 (+$1.20), XLF 12 (−$2.40), AAL 2 (−$1.17), NU 1 (−$0.26), BITO 1 (−$0.03). Every position has a live profit-target sell order at the broker; stops ride as paired held legs (today's entries confirmed held at Alpaca). Nothing naked, nothing phantom.

## P&L
Day: **+$15.00 (+0.31%)** — roughly +$3 realized (F half-exit +$7.20 offset by small exit trims) plus ~$12 unrealized on the new book. Biggest movers: CSCO +$5.46, F +$5.28, ATAI +$4.20; drag XLF −$3.18. Goal ladder: partway to the $50 first rung with the afternoon left.

## Scan / gate detail (activity ledger — live, last write 12:11 ET)
3,270 ledger entries so far today: **9 approves, 2,874 vetoes**, 4 submitted, 5 modeled open fills, 2 option harvests, 2 exit liquidates, 221 wheel capacity checks. Approvals ARE turning into real broker fills — no gap there.
Top veto reasons: Open-signal cap reached at 10 (2,091 — 73% of all vetoes), neutral direction / no bias (372), anti-stacking skips on NU (160), GBPUSD (66), EURUSD (49), CSCO (46).
Same story as yesterday: the book is full at the cap, so almost everything new gets waved off. Not a fault — but if you want more concurrent positions, raise "Maximum open positions" in Bot Tuning.

## Bottom line
State (b): working and actively trading. High morning turnover (5 exits → 4 protected entries), both overnight protection systems (ETH trail, put harvest re-arm) verified live with real fills, ledger current, no rejects, no blocks. Nothing needs your attention.
