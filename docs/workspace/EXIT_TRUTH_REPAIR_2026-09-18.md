# Exit truth — evidence and repair plan for the 2026-09-18 modeled closes

Source of truth: Alpaca paper `GET /v2/account/activities/FILL` per book, read with each
book's own credentials on 2026-09-18 ~16:00Z. Ledger rows: `paper_positions` closed
12:30–14:00Z for SOL and LINK. Fee model: 26 bps per side (Alpaca posts fee activities later).

| book | tk | qty | entry | booked exit | booked P/L | venue exit | true P/L | delta | order |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 75k TR2H | SOL | 28.184129 | 106.230 | 96.821565 | −272.26 | 105.4226 | −30.48 | +241.78 | e41003ba |
| 25k H703 | SOL | 7.044620 | 106.230 | 96.821565 | −68.05 | 105.5100 | −7.00 | +61.05 | 3f8e5b95 |
| primary | SOL | 1.568441 | 106.150 | 96.821565 | −15.03 | 105.5000 | −1.45 | +13.58 | 75d13131 |
| primary | LINK | 58.987605 | 11.877 | 10.874560 | −60.81 | 11.9073 | −0.05 | +60.76 | e0cb9457 |
| primary | SOL | 6.507045 | 105.540 | 108.360000 | +18.35 | 107.9000 | +13.53 | −4.82 | b7a1321c |

Total ledger correction: **+372.35 USD**. Booked −416.15 on the four disputed rows; real ≈ −39.

What happened: the monitor priced SOL off a days-old fallback candle (96.87), judged the stop hit
on all three books while the venue quoted 105.40/105.50, liquidated at the venue (fills
105.40–105.51), and booked every row at 96.87 × (1 − 5 bps) with modeled fees. The stop never
triggered on a real price; the coins were sold for no reason and the primary re-bought 36 s later.

Fix (this commit): fresh venue price or no judgment; liquidations booked from the venue's fill by
order id or parked as exit_pending; broker closes priced from receipts and labelled; both close paths
move the account counters through one function.

Repair: applied only on Mike's approval; each repaired row keeps `source_payload.repair` with the
old exit/P&L so it is reversible; account today/week/ytd/cash move by each row's delta.
