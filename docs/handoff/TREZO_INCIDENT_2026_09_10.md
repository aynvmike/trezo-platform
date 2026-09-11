# Trezo incident — 2026-09-10

## Verified causes and repairs

- **LULG260918P00004000, book 6ce61054**: the Wheel created its broker-backed row at 13:33 UTC September 8. Adoption created a second manager at 13:50 because it checked only paper_positions. The broker receipt confirms one short contract. Commit 681b08d makes adoption, QA orphan detection, and book health recognize the Wheel's ownership. An unreadable ownership query defers action.
- **Duplicate cleanup**: on September 10 at 19:14 UTC, tools/repair_lulg_duplicate_20260910.py retired paper row 072aeb66-ac96-4141-b668-c18b5b3deea3 as closed_adopted. Wheel row 5308eb58-887f-4dac-aaee-afc2ed70c303 remains open. Realized P/L stays NULL; no trade outcome or counter was written. Original rows and broker receipts are backed up in logs/LULG-before-repair-20260910T191406Z.json.
- **XOM, same book**: the prior short's take-profit filled September 3 at 19:57:19 UTC. A separate buy-stop was created 21 seconds later, remained working, then opened five long shares September 10 at 13:31. Protection now confirms a currently held short before cancellations, OCO submission, fallback, or target restoration. Missing, flat, long, malformed, and unavailable quantities refuse a protective buy. This narrows the stale-snapshot race; it is not an atomic broker reduce-only guarantee.
- **XOM current state**: the agents subsequently recorded the new long with its broker order ID. At the final broker check, the position endpoint returned 404 and the matching ledger row was closed_manual. No manual broker orders were placed during this investigation.
- **Server timeouts**: the initial localhost health check timed out and multiple agents had stalled. The server was running 5fd0c12; a previous deploy had stranded. The repaired engine booted on 681b08d, with 74 suites passing on the server.
- **Responsiveness evidence**: the diagnostic worker later read positions and open orders successfully on all three books (1.3–2.0 seconds each). At that moment the main thread was inside position_monitor -> ensure_stock_protection -> get_open_orders_for -> httpx.AsyncClient -> create_ssl_context -> ssl.create_default_context. The follow-up patch caches verified TLS trust configuration and builds it off the event loop. Request authentication stays per request/book; certificate and hostname verification remain enabled.
- Alert language now distinguishes missing ledger management from verified absence of broker protection.

## Validation and operations

The incident suite exercises the real adoption, QA, health, broker protection and diagnostic paths using offline boundaries. TLS tests require certificate loading off the event-loop thread, one cached context under concurrent reads, and failed setup to remain a failed read.

Use the existing relay report_status with {"diagnostics": true} to compare main-thread stack locations against isolated read-only broker calls. This reports no credentials, response bodies, or stack locals.

The TLS follow-up still requires a server boot and fresh operational verification before attributing timeout recovery to it. Do not treat a passing test suite or an old alert's silence as proof of recovery.
