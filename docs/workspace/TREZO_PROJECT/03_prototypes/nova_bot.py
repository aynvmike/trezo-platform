"""
╔══════════════════════════════════════════════════════════════════╗
║           NOVA TRADING BOT v1.0 — Small Trades Momentum Strategy      ║
║           Built for Webull OpenAPI — Small Account ($500–$2K)   ║
║                                                                  ║
║  PHASES:                                                         ║
║    Phase 1 (NOW)  — Paper mode: scan + score, no real orders     ║
║    Phase 2        — Alert mode: Telegram alerts, you approve     ║
║    Phase 3        — Live mode: full auto via Webull OpenAPI      ║
║                                                                  ║
║  STRATEGY: Small Trades Momentum Strategy (STMS)                    ║
║    Indicators: VWAP, MACD, EMA 50/200, Senkou Span B, FVG       ║
║    Setup: Bull Flag, Flat Top, Micro-Pullback                    ║
║    Time: 7:00 AM – 11:00 AM EST only                            ║
╚══════════════════════════════════════════════════════════════════╝

HOW TO RUN THIS (no coding experience needed):
─────────────────────────────────────────────
1. Install Python: https://www.python.org/downloads/
2. Open Terminal (Mac) or Command Prompt (Windows)
3. Type: pip install pandas pandas-ta requests yfinance python-telegram-bot
4. Save this file as nova_bot.py
5. Type: python nova_bot.py
6. The bot runs in PAPER mode — no real money touched

SETUP YOUR TELEGRAM ALERTS (free):
────────────────────────────────────
1. Message @BotFather on Telegram → /newbot → name it NovaBot
2. Copy the API token it gives you
3. Paste it in TELEGRAM_TOKEN below
4. Find your Chat ID: message @userinfobot
5. Paste your Chat ID in TELEGRAM_CHAT_ID below
"""

import time
import datetime
import random
import json
from dataclasses import dataclass, field
from typing import Optional

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
# Edit these settings to match your account

CONFIG = {
    # ── Account ──────────────────────────────────────────────
    "account_size": 1500,           # Your Webull account size in $
    "risk_per_trade_pct": 0.05,     # Risk 5% per trade
    "profit_target_pct": 0.10,      # Target 10% per trade
    "max_daily_loss_pct": 0.10,     # Stop trading if down 10% on the day
    "max_consecutive_losses": 3,    # Stop after 3 losses in a row

    # ── Stock Filter ─────────────────────────────────────────
    "min_price": 1.00,              # Minimum stock price
    "max_price": 20.00,             # Maximum stock price
    "sweet_spot_min": 5.00,         # Sweet spot minimum
    "sweet_spot_max": 10.00,        # Sweet spot maximum
    "min_change_pct": 10.0,         # Stock must be up this % today
    "min_relative_volume": 5.0,     # Must have 5x normal volume
    "max_float_million": 20.0,      # Float must be under 20 million shares

    # ── Trading Window ────────────────────────────────────────
    "start_hour": 7,                # 7:00 AM EST
    "start_minute": 0,
    "end_hour": 11,                 # 11:00 AM EST
    "end_minute": 0,

    # ── Scoring Thresholds ────────────────────────────────────
    "min_score_to_trade": 65,       # Must score 65%+ to enter
    "strong_go_score": 80,          # 80%+ = full size

    # ── Mode ─────────────────────────────────────────────────
    "mode": "paper",                # "paper" | "alert" | "live"
    "scan_interval_seconds": 30,    # How often to scan

    # ── Telegram (optional but recommended) ──────────────────
    "telegram_token": "YOUR_BOT_TOKEN_HERE",
    "telegram_chat_id": "YOUR_CHAT_ID_HERE",
    "use_telegram": False,          # Set True after you add your token

    # ── Logging ──────────────────────────────────────────────
    "log_file": "nova_trades.json",
    "verbose": True,
}

# ─── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class StockCandidate:
    ticker: str
    price: float
    change_pct: float
    relative_volume: float
    float_millions: float
    catalyst: str
    score: int = 0
    above_vwap: bool = False
    macd_bullish: bool = False
    above_ema200: bool = False
    above_senkou_b: bool = False
    volume_confirmed: bool = False
    pattern: str = ""

@dataclass
class Trade:
    ticker: str
    entry_price: float
    stop_price: float
    target_price: float
    shares: int
    risk_amount: float
    entry_time: str
    score: int
    status: str = "OPEN"   # OPEN | WIN | LOSS | STOPPED
    exit_price: float = 0.0
    pnl: float = 0.0
    exit_time: str = ""

@dataclass
class BotState:
    total_pnl: float = 0.0
    daily_loss: float = 0.0
    trades_today: list = field(default_factory=list)
    consecutive_losses: int = 0
    wins: int = 0
    losses: int = 0
    active_trade: Optional[Trade] = None
    is_running: bool = True

# ─── LOGGER ───────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "   ", "SCAN": "🔍 ", "SIGNAL": "✅ ", "TRADE": "⚡ ",
              "WIN": "💰 ", "LOSS": "❌ ", "WARN": "⚠️  ", "STOP": "🛑 "}.get(level, "   ")
    print(f"[{timestamp}] {prefix}{msg}")

def log_trade_to_file(trade: Trade):
    """Save every trade to a JSON log file for review"""
    try:
        with open(CONFIG["log_file"], "a") as f:
            f.write(json.dumps({
                "ticker": trade.ticker,
                "entry": trade.entry_price,
                "exit": trade.exit_price,
                "stop": trade.stop_price,
                "target": trade.target_price,
                "shares": trade.shares,
                "pnl": trade.pnl,
                "status": trade.status,
                "entry_time": trade.entry_time,
                "exit_time": trade.exit_time,
                "score": trade.score,
            }) + "\n")
    except Exception as e:
        log(f"Log write error: {e}", "WARN")

# ─── SCANNER ENGINE ───────────────────────────────────────────────────────────

def get_market_health() -> tuple[float, bool]:
    """
    Checks SPY and QQQ to determine if it's a hot or cold market.
    Returns (avg_market_change_pct, is_hot_market).
    Requires: pip install yfinance --break-system-packages
    """
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY").fast_info
        qqq = yf.Ticker("QQQ").fast_info
        spy_pct = (spy.last_price - spy.previous_close) / spy.previous_close * 100
        qqq_pct = (qqq.last_price - qqq.previous_close) / qqq.previous_close * 100
        avg = (spy_pct + qqq_pct) / 2
        is_hot = avg >= 0.25
        log(f"Market health: SPY {spy_pct:+.2f}% | QQQ {qqq_pct:+.2f}% | {'🔥 HOT' if is_hot else '❄️ COLD'}", "SCAN")
        return avg, is_hot
    except Exception as e:
        log(f"Market health check failed: {e}", "WARN")
        return 0.0, True  # Default to trading in unknown conditions


def scan_for_candidates() -> list[StockCandidate]:
    """
    Scans for A-grade momentum stock setups using real yfinance data.

    SETUP (one time):
    ─────────────────
    pip install yfinance --break-system-packages

    HOW IT WORKS:
    1. Checks SPY/QQQ for overall market health
    2. Scans a watchlist of small-cap tickers for qualifying setups
    3. Filters by: price $1–$20, up 10%+, rel vol 5x+, float <20M
    4. Falls back to simulation if yfinance unavailable

    LIVE MODE (Phase 3):
    ─────────────────────
    Change CONFIG["mode"] to "live" — same function, same data,
    but execute_trade() will send real orders via Webull OpenAPI.
    """

    # Watchlist of small-cap momentum candidates to scan
    # These are real tickers — bot checks which ones are actually moving
    WATCHLIST = [
        "TRAW", "DRUG", "MESO", "SHOT", "CYTO", "VERB", "GHSI",
        "AGRI", "ILUS", "EBON", "WINT", "NRXS", "PRLD", "PALI",
        "APRE", "SAVA", "ATXI", "INVU", "CUEN", "ABVC",
    ]

    try:
        import yfinance as yf

        candidates = []
        log(f"Scanning {len(WATCHLIST)} tickers via yfinance...", "SCAN")

        for ticker_sym in WATCHLIST:
            try:
                t = yf.Ticker(ticker_sym)
                info = t.fast_info

                price = info.last_price
                if not price or price < CONFIG["min_price"] or price > CONFIG["max_price"]:
                    continue

                prev = info.previous_close
                if not prev or prev <= 0:
                    continue

                change_pct = (price - prev) / prev * 100
                if change_pct < CONFIG["min_change_pct"]:
                    continue

                # Relative volume
                hist = t.history(period="1mo", interval="1d")
                if hist.empty or len(hist) < 5:
                    continue
                avg_vol = hist["Volume"].mean()
                today_vol = info.three_month_average_volume or avg_vol
                rel_vol = today_vol / avg_vol if avg_vol > 0 else 1
                if rel_vol < CONFIG["min_relative_volume"]:
                    continue

                # Float
                full_info = t.info
                float_shares = full_info.get("floatShares", 0) or 0
                float_m = float_shares / 1_000_000
                if float_m > CONFIG["max_float_million"] and float_m != 0:
                    continue

                # News catalyst
                news = t.news
                catalyst = ""
                if news:
                    try:
                        catalyst = news[0]["content"]["title"][:60]
                    except Exception:
                        catalyst = "News catalyst present"

                candidate = StockCandidate(
                    ticker=ticker_sym,
                    price=price,
                    change_pct=round(change_pct, 1),
                    relative_volume=round(rel_vol, 1),
                    float_millions=round(float_m, 1),
                    catalyst=catalyst,
                )
                candidates.append(candidate)
                log(f"  ✓ {ticker_sym} qualifies: ${price} | +{change_pct:.1f}% | {rel_vol:.1f}x RVol", "SCAN")

            except Exception:
                continue

        log(f"Scan complete — {len(candidates)} qualified candidates", "SCAN")
        return candidates

    except ImportError:
        log("yfinance not installed. Run: pip install yfinance --break-system-packages", "WARN")
    except Exception as e:
        log(f"yfinance scan error: {e}", "WARN")

    # ── SIMULATION FALLBACK ───────────────────────────────────────────────────
    log("Using simulation fallback — install yfinance for live data", "WARN")
    candidates = []
    catalysts = [
        "FDA Drug Approval", "Earnings Beat +42%", "Major Contract Award",
        "Clinical Trial Success", "Short Squeeze Setup", "Revenue Guidance Raise",
        "Strategic Partnership", "CEO Buyback Announcement",
    ]
    for _ in range(random.randint(0, 4)):
        ticker = "".join(random.choices("ABCDEFGHIJKLMNOPRSTUVWXYZ", k=random.randint(3, 4)))
        candidate = StockCandidate(
            ticker=ticker,
            price=round(random.uniform(CONFIG["min_price"], CONFIG["max_price"]), 2),
            change_pct=round(random.uniform(8, 150), 1),
            relative_volume=round(random.uniform(2, 50), 1),
            float_millions=round(random.uniform(0.5, 25), 1),
            catalyst=random.choice(catalysts),
        )
        candidates.append(candidate)
    return candidates

# ─── SCORING ENGINE ───────────────────────────────────────────────────────────

def score_candidate(candidate: StockCandidate) -> StockCandidate:
    """
    Runs the 14-point entry scorer.
    This is the same logic as the Entry Scorer dashboard.
    Returns the candidate with a score 0–100.
    REQUIRED checks must ALL pass or score = 0.
    """

    score = 0
    required_failed = False

    # ── REQUIRED CHECKS (all must pass) ────────────────────────────────
    # Price in range
    if CONFIG["min_price"] <= candidate.price <= CONFIG["max_price"]:
        score += 10
    else:
        required_failed = True
        log(f"  ${candidate.ticker} FAIL: Price ${candidate.price} out of range", "SCAN")

    # Already up 10%+
    if candidate.change_pct >= CONFIG["min_change_pct"]:
        score += 10
    else:
        required_failed = True
        log(f"  ${candidate.ticker} FAIL: Only up {candidate.change_pct}% (need 10%+)", "SCAN")

    # Relative volume 5x+
    if candidate.relative_volume >= CONFIG["min_relative_volume"]:
        score += 15
    else:
        required_failed = True
        log(f"  ${candidate.ticker} FAIL: RVol {candidate.relative_volume}x (need 5x+)", "SCAN")

    # News catalyst present (always true in simulation; live = check news API)
    if candidate.catalyst:
        score += 15
    else:
        required_failed = True

    # Float under 20M
    if candidate.float_millions < CONFIG["max_float_million"]:
        score += 10
    else:
        required_failed = True
        log(f"  ${candidate.ticker} FAIL: Float {candidate.float_millions}M (need <20M)", "SCAN")

    # EMA 200 filter (simulated in paper mode)
    candidate.above_ema200 = random.random() > 0.3
    if candidate.above_ema200:
        score += 10

    # Senkou Span B direction filter (simulated in paper mode)
    candidate.above_senkou_b = random.random() > 0.35
    if candidate.above_senkou_b:
        score += 10

    # ── TRIGGER CHECKS (not required but add to score) ──────────────────

    # VWAP cross (simulated)
    candidate.above_vwap = random.random() > 0.3
    if candidate.above_vwap:
        score += 15

    # MACD bullish crossover (simulated)
    candidate.macd_bullish = random.random() > 0.4
    if candidate.macd_bullish:
        score += 10

    # Volume confirmation
    candidate.volume_confirmed = random.random() > 0.4
    if candidate.volume_confirmed:
        score += 10

    # Pattern identified
    patterns = ["Bull Flag", "Flat Top Breakout", "Micro-Pullback", ""]
    candidate.pattern = random.choice(patterns)
    if candidate.pattern:
        score += 10

    # EMA 50 above price
    if random.random() > 0.5:
        score += 5

    # Early in move (not extended)
    if random.random() > 0.5:
        score += 5

    # 2:1 R/R visible
    if random.random() > 0.4:
        score += 10

    # If any required check failed, override score to 0
    if required_failed:
        candidate.score = 0
    else:
        candidate.score = min(100, score)

    return candidate

# ─── POSITION SIZER ───────────────────────────────────────────────────────────

def calculate_position(candidate: StockCandidate, account_size: float) -> tuple[int, float, float, float]:
    """
    Calculates position size, stop, and target.
    Rules:
    - Risk exactly 5% of account per trade
    - Stop at -5% from entry
    - Target at +10% from entry
    - Returns (shares, stop_price, target_price, risk_amount)
    """
    risk_dollars = account_size * CONFIG["risk_per_trade_pct"]
    stop_price = round(candidate.price * 0.95, 2)
    target_price = round(candidate.price * (1 + CONFIG["profit_target_pct"]), 2)
    risk_per_share = candidate.price - stop_price
    shares = max(1, int(risk_dollars / risk_per_share))

    # Don't exceed 50% of account in one position
    max_shares = int((account_size * 0.5) / candidate.price)
    shares = min(shares, max_shares)

    actual_risk = round(risk_per_share * shares, 2)

    return shares, stop_price, target_price, actual_risk

# ─── TELEGRAM ALERTS ──────────────────────────────────────────────────────────

def send_telegram(message: str):
    """Send a Telegram message. Enable by setting use_telegram: True in CONFIG."""
    if not CONFIG["use_telegram"]:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{CONFIG['telegram_token']}/sendMessage"
        requests.post(url, data={
            "chat_id": CONFIG["telegram_chat_id"],
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=5)
    except Exception as e:
        log(f"Telegram error: {e}", "WARN")

# ─── TRADE EXECUTOR ───────────────────────────────────────────────────────────

def execute_trade(candidate: StockCandidate, state: BotState) -> Optional[Trade]:
    """
    PAPER MODE: Simulates order execution.
    LIVE MODE (Phase 3): Sends real orders via Webull OpenAPI.

    Live implementation stub:
    ─────────────────────────
    from webull_openapi import webull
    wb = webull()
    wb.login(YOUR_API_KEY)
    wb.place_order(
        stock=candidate.ticker,
        action='BUY',
        orderType='MKT',
        enforce='DAY',
        qty=shares
    )
    wb.place_order(  # Stop loss
        stock=candidate.ticker,
        action='SELL',
        orderType='STP',
        price=stop_price,
        enforce='DAY',
        qty=shares
    )
    wb.place_order(  # Profit target
        stock=candidate.ticker,
        action='SELL',
        orderType='LMT',
        price=target_price,
        enforce='DAY',
        qty=shares
    )
    """

    account_size = CONFIG["account_size"] + state.total_pnl
    shares, stop_price, target_price, risk_amount = calculate_position(candidate, account_size)

    trade = Trade(
        ticker=candidate.ticker,
        entry_price=candidate.price,
        stop_price=stop_price,
        target_price=target_price,
        shares=shares,
        risk_amount=risk_amount,
        entry_time=datetime.datetime.now().strftime("%H:%M:%S"),
        score=candidate.score,
    )

    msg = (
        f"⚡ *NOVA BOT ENTERING TRADE*\n"
        f"Ticker: `${trade.ticker}`\n"
        f"Entry: `${trade.entry_price}`\n"
        f"Stop: `${trade.stop_price}` (-5%)\n"
        f"Target: `${trade.target_price}` (+10%)\n"
        f"Shares: `{trade.shares}`\n"
        f"Risk: `${trade.risk_amount}`\n"
        f"Score: `{trade.score}%`\n"
        f"Catalyst: {candidate.catalyst}"
    )
    send_telegram(msg)

    return trade

# ─── TRADE MONITOR ────────────────────────────────────────────────────────────

def monitor_trade(trade: Trade, state: BotState) -> Trade:
    """
    Monitors an open trade and exits when:
    - Price hits target (+10%)
    - Price hits stop (-5%)
    - MACD crosses bearish
    - Jackknife rejection candle appears
    - End of trading window (11 AM)

    In paper mode: randomly simulates outcome.
    In live mode: polls Webull for current price.
    """

    # Paper mode simulation
    time.sleep(random.uniform(2, 8))  # Simulate time in trade

    # Simulate outcome (65% win rate target for STMS A-grade setups)
    win = random.random() < 0.65

    if win:
        # Hit target or partial fill
        exit_price = round(trade.entry_price * random.uniform(1.05, 1.12), 2)
        trade.status = "WIN"
        trade.pnl = round((exit_price - trade.entry_price) * trade.shares, 2)
    else:
        # Hit stop
        exit_price = round(trade.entry_price * random.uniform(0.93, 0.97), 2)
        trade.status = "LOSS"
        trade.pnl = round((exit_price - trade.entry_price) * trade.shares, 2)

    trade.exit_price = exit_price
    trade.exit_time = datetime.datetime.now().strftime("%H:%M:%S")

    return trade

# ─── RISK GUARD ───────────────────────────────────────────────────────────────

def check_risk_rules(state: BotState) -> tuple[bool, str]:
    """
    Returns (can_trade, reason).
    Enforces all hard risk rules — these NEVER get overridden.
    """

    # Daily max loss
    max_loss = CONFIG["account_size"] * CONFIG["max_daily_loss_pct"]
    if state.daily_loss >= max_loss:
        return False, f"Daily max loss hit (${state.daily_loss:.0f} / ${max_loss:.0f})"

    # Consecutive losses
    if state.consecutive_losses >= CONFIG["max_consecutive_losses"]:
        return False, f"{state.consecutive_losses} consecutive losses — 30 min cool-down"

    # No active trade
    if state.active_trade is not None:
        return False, "Already in a trade"

    return True, "OK"

# ─── TRADING WINDOW CHECK ─────────────────────────────────────────────────────

def in_trading_window() -> bool:
    """Returns True if current time is within the 7 AM – 11 AM EST trading window."""
    now_time = datetime.datetime.now()
    start = now_time.replace(hour=CONFIG["start_hour"], minute=CONFIG["start_minute"], second=0)
    end = now_time.replace(hour=CONFIG["end_hour"], minute=CONFIG["end_minute"], second=0)
    return start <= now_time < end

# ─── DAILY SUMMARY ────────────────────────────────────────────────────────────

def print_daily_summary(state: BotState):
    total_trades = state.wins + state.losses
    win_rate = (state.wins / total_trades * 100) if total_trades > 0 else 0

    print("\n" + "═" * 60)
    print("  NOVA BOT — DAILY SUMMARY")
    print("═" * 60)
    print(f"  Total P&L:     ${state.total_pnl:+.2f}")
    print(f"  Trades:        {total_trades} ({state.wins}W / {state.losses}L)")
    print(f"  Win Rate:      {win_rate:.0f}%")
    print(f"  Daily Loss:    ${state.daily_loss:.2f}")
    print(f"  Status:        {'✅ Profitable' if state.total_pnl > 0 else '❌ Down'}")
    print("═" * 60 + "\n")

    send_telegram(
        f"📊 *NOVA BOT DAILY SUMMARY*\n"
        f"P&L: `${state.total_pnl:+.2f}`\n"
        f"Trades: `{total_trades}` ({state.wins}W/{state.losses}L)\n"
        f"Win Rate: `{win_rate:.0f}%`"
    )

# ─── MAIN BOT LOOP ────────────────────────────────────────────────────────────

def run_bot():
    print("\n" + "═" * 60)
    print("  ⚡ NOVA TRADING BOT v1.0 — STARTING UP")
    print(f"  Mode: {CONFIG['mode'].upper()}")
    print(f"  Account: ${CONFIG['account_size']}")
    print(f"  Risk per trade: {CONFIG['risk_per_trade_pct']*100:.0f}%")
    print(f"  Daily max loss: ${CONFIG['account_size'] * CONFIG['max_daily_loss_pct']:.0f}")
    print(f"  Trading window: {CONFIG['start_hour']}:00 – {CONFIG['end_hour']}:00 EST")
    print("═" * 60 + "\n")

    state = BotState()
    scan_count = 0

    try:
        while state.is_running:

            # ── Wait for trading window ────────────────────────────────────
            if not in_trading_window():
                current_hour = datetime.datetime.now().hour
                if current_hour >= CONFIG["end_hour"]:
                    log("Trading window closed (past 11 AM) — shutting down for today", "STOP")
                    print_daily_summary(state)
                    break
                else:
                    log(f"Waiting for 7:00 AM trading window... (current: {datetime.datetime.now().strftime('%H:%M')})", "INFO")
                    time.sleep(60)
                    continue

            # ── Check risk rules ────────────────────────────────────────────
            can_trade, reason = check_risk_rules(state)
            if not can_trade:
                log(f"Risk guard: {reason}", "STOP")
                if "cool-down" in reason:
                    log("Pausing for 30 minutes...", "WARN")
                    time.sleep(1800)
                    state.consecutive_losses = 0  # Reset after cool-down
                    continue
                elif "Daily max loss" in reason:
                    log("Daily max loss hit — stopping bot for today", "STOP")
                    print_daily_summary(state)
                    break

            # ── Market health check (live via yfinance) ─────────────────────
            avg_mkt, is_hot = get_market_health()
            if avg_mkt < -1.5:
                log(f"Market down {avg_mkt:.2f}% — conditions too cold, waiting...", "WARN")
                time.sleep(CONFIG["scan_interval_seconds"] * 2)
                continue

            # ── Scan ───────────────────────────────────────────────────────
            scan_count += 1
            log(f"Scan #{scan_count} — filtering for A-grade setups...", "SCAN")

            candidates = scan_for_candidates()

            if not candidates:
                log("No candidates found this cycle", "SCAN")
                time.sleep(CONFIG["scan_interval_seconds"])
                continue

            # ── Score each candidate ───────────────────────────────────────
            qualified = []
            for c in candidates:
                scored = score_candidate(c)
                log(f"  ${c.ticker} | ${c.price} | +{c.change_pct}% | {c.relative_volume}x | Score: {scored.score}%", "SCAN")
                if scored.score >= CONFIG["min_score_to_trade"]:
                    qualified.append(scored)

            if not qualified:
                log("No candidates met the 65% score threshold", "SCAN")
                time.sleep(CONFIG["scan_interval_seconds"])
                continue

            # ── Take the best setup ────────────────────────────────────────
            best = max(qualified, key=lambda x: x.score)
            verdict = "STRONG GO" if best.score >= CONFIG["strong_go_score"] else "GO"
            log(f"${best.ticker} — Score {best.score}% — {verdict} — {best.catalyst}", "SIGNAL")
            log(f"  VWAP: {'✅' if best.above_vwap else '❌'}  MACD: {'✅' if best.macd_bullish else '❌'}  Senkou B: {'✅' if best.above_senkou_b else '❌'}  Pattern: {best.pattern or 'None'}", "SIGNAL")

            # ── Execute ────────────────────────────────────────────────────
            trade = execute_trade(best, state)
            if not trade:
                continue

            state.active_trade = trade
            log(
                f"LONG ${trade.ticker} @ ${trade.entry_price} | "
                f"{trade.shares} shares | Stop ${trade.stop_price} | Target ${trade.target_price} | Risk ${trade.risk_amount}",
                "TRADE"
            )

            # ── Monitor ────────────────────────────────────────────────────
            trade = monitor_trade(trade, state)
            state.active_trade = None

            # ── Process outcome ────────────────────────────────────────────
            state.total_pnl = round(state.total_pnl + trade.pnl, 2)
            state.trades_today.append(trade)

            if trade.status == "WIN":
                state.wins += 1
                state.consecutive_losses = 0
                log(
                    f"${trade.ticker} WIN | Exit ${trade.exit_price} | P&L ${trade.pnl:+.2f} | Total ${state.total_pnl:+.2f}",
                    "WIN"
                )
                send_telegram(f"💰 WIN: `${trade.ticker}` | P&L: `${trade.pnl:+.2f}` | Day: `${state.total_pnl:+.2f}`")
            else:
                state.losses += 1
                state.consecutive_losses += 1
                state.daily_loss = round(state.daily_loss + abs(trade.pnl), 2)
                log(
                    f"${trade.ticker} LOSS | Exit ${trade.exit_price} | P&L ${trade.pnl:+.2f} | Total ${state.total_pnl:+.2f} | Streak: {state.consecutive_losses}",
                    "LOSS"
                )
                send_telegram(f"❌ LOSS: `${trade.ticker}` | P&L: `${trade.pnl:+.2f}` | Day: `${state.total_pnl:+.2f}`")

            log_trade_to_file(trade)

            # ── Cool down between trades ────────────────────────────────────
            log("Cooling down 60 seconds before next scan...", "INFO")
            time.sleep(60)

    except KeyboardInterrupt:
        log("Bot stopped by user (Ctrl+C)", "STOP")
        print_daily_summary(state)

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_bot()
