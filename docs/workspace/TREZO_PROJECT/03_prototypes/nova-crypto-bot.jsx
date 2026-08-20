import { useState, useEffect, useRef } from "react";

// ── THEME ─────────────────────────────────────────────────────────────────────
const T = {
  bg:      "#04050d",
  surface: "#080b18",
  card:    "#0c1020",
  border:  "#141930",
  borderHi:"#1e2845",
  cyan:    "#00e5ff",
  cyanDim: "#00e5ff18",
  purple:  "#9d4edd",
  purDim:  "#9d4edd18",
  gold:    "#ffd60a",
  goldDim: "#ffd60a18",
  green:   "#06d6a0",
  red:     "#ef233c",
  text:    "#cdd6f4",
  muted:   "#45475a",
  mono:    "'Courier New', monospace",
};

// ── COIN CONFIG ───────────────────────────────────────────────────────────────
const COINS = {
  XRP:  { color: T.cyan,   symbol: "XRP",  base: 1.45,   vol: 0.04, capital: 2536.69, ready: true },
  ETH:  { color: T.purple, symbol: "ETH",  base: 2260.0, vol: 0.03, capital: 1267.00, ready: true },
  SOL:  { color: T.gold,   symbol: "SOL",  base: 93.81,  vol: 0.05, capital: 833.01,  ready: false },
};

// ── MODES ─────────────────────────────────────────────────────────────────────
const MODES = {
  SCALP: { label: "SCALP",  color: T.cyan,   target: 0.025, stop: 0.012, desc: "2–3% quick captures" },
  SWING: { label: "SWING",  color: T.purple, target: 0.12,  stop: 0.05,  desc: "10–15% trend rides" },
  DCA:   { label: "DCA",    color: T.gold,   target: 0.08,  stop: 0.04,  desc: "Buy dips, sell peaks" },
};

// ── MARKET CONDITIONS → MODE SELECTOR ────────────────────────────────────────
function selectMode(rsi, trend, volatility) {
  if (volatility > 0.035) return "SCALP";
  if (trend > 0.6 && rsi < 65) return "SWING";
  if (rsi < 35 || rsi > 72) return "DCA";
  return "SCALP";
}

// ── PRICE SIMULATOR ───────────────────────────────────────────────────────────
function nextPrice(current, vol) {
  const drift = (Math.random() - 0.495) * vol;
  return +(current * (1 + drift)).toFixed(current > 100 ? 2 : 4);
}

// ── INDICATOR SIMULATOR ───────────────────────────────────────────────────────
function calcIndicators(prices) {
  if (prices.length < 2) return { rsi: 50, macd: 0, bb_pos: 0.5, trend: 0.5, volatility: 0.02 };
  const gains = [], losses = [];
  for (let i = 1; i < prices.length; i++) {
    const d = prices[i] - prices[i - 1];
    if (d > 0) gains.push(d); else losses.push(Math.abs(d));
  }
  const avgGain = gains.length ? gains.reduce((a, b) => a + b, 0) / gains.length : 0.01;
  const avgLoss = losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : 0.01;
  const rs = avgGain / avgLoss;
  const rsi = 100 - (100 / (1 + rs));
  const last = prices[prices.length - 1];
  const first = prices[0];
  const trend = last > first ? Math.min(1, (last - first) / first / 0.05) : Math.max(0, 1 - (first - last) / first / 0.05);
  const mean = prices.reduce((a, b) => a + b, 0) / prices.length;
  const std = Math.sqrt(prices.map(p => (p - mean) ** 2).reduce((a, b) => a + b, 0) / prices.length);
  const bb_pos = std > 0 ? (last - (mean - 2 * std)) / (4 * std) : 0.5;
  const volatility = std / mean;
  const macd = prices.length > 5 ?
    (prices.slice(-3).reduce((a, b) => a + b) / 3) -
    (prices.slice(-6, -3).reduce((a, b) => a + b) / 3) : 0;
  return { rsi: +rsi.toFixed(1), macd: +macd.toFixed(4), bb_pos: +bb_pos.toFixed(2), trend: +trend.toFixed(2), volatility: +volatility.toFixed(4) };
}

// ── ANIMATIONS ────────────────────────────────────────────────────────────────
const CSS = `
@keyframes pulse { 0%,100%{opacity:1}50%{opacity:.3} }
@keyframes fadeUp { from{transform:translateY(8px);opacity:0}to{transform:translateY(0);opacity:1} }
@keyframes glow { 0%,100%{box-shadow:0 0 10px #00e5ff33}50%{box-shadow:0 0 30px #00e5ff77} }
@keyframes ticker { 0%{transform:translateX(100%)}100%{transform:translateX(-100%)} }
@keyframes scanLine { 0%{top:0}100%{top:100%} }
`;

const Pip = ({ color, pulse }) => (
  <span style={{
    width: 7, height: 7, borderRadius: "50%", display: "inline-block",
    background: color, boxShadow: `0 0 6px ${color}`,
    animation: pulse ? "pulse 1.2s infinite" : "none", flexShrink: 0,
  }} />
);

const Tag = ({ color, children, sm }) => (
  <span style={{
    background: color + "20", color, border: `1px solid ${color}44`,
    borderRadius: 3, padding: sm ? "1px 5px" : "2px 8px",
    fontSize: sm ? 9 : 10, fontFamily: T.mono,
    fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase",
    whiteSpace: "nowrap",
  }}>{children}</span>
);

const MiniBar = ({ value, max, color }) => (
  <div style={{ background: T.border, borderRadius: 2, height: 3, flex: 1, overflow: "hidden" }}>
    <div style={{
      height: "100%", borderRadius: 2, transition: "width .5s ease",
      width: `${Math.min(100, Math.max(0, (value / max) * 100))}%`,
      background: color,
    }} />
  </div>
);

// ── MAIN ─────────────────────────────────────────────────────────────────────
export default function NovaCryptoBot() {
  const [active, setActive] = useState(false);
  const [prices, setPrices] = useState({ XRP: COINS.XRP.base, ETH: COINS.ETH.base, SOL: COINS.SOL.base });
  const [priceHistory, setPriceHistory] = useState({ XRP: [COINS.XRP.base], ETH: [COINS.ETH.base], SOL: [COINS.SOL.base] });
  const [indicators, setIndicators] = useState({ XRP: {rsi:50,macd:0,trend:.5,volatility:.02}, ETH: {rsi:50,macd:0,trend:.5,volatility:.02}, SOL: {rsi:50,macd:0,trend:.5,volatility:.02} });
  const [modes, setModes] = useState({ XRP: "SCALP", ETH: "SCALP", SOL: "SCALP" });
  const [activeTrades, setActiveTrades] = useState({});
  const [closedTrades, setClosedTrades] = useState([]);
  const [pnl, setPnl] = useState({ XRP: 0, ETH: 0, SOL: 0, total: 0 });
  const [dailyLoss, setDailyLoss] = useState(0);
  const [log, setLog] = useState([]);
  const [tick, setTick] = useState(0);
  const [solReady, setSolReady] = useState(false);
  const [stats, setStats] = useState({ wins: 0, losses: 0, trades: 0 });
  const intervalRef = useRef(null);
  const totalCapital = Object.values(COINS).reduce((s, c) => s + c.capital, 0);
  const maxDailyLoss = totalCapital * 0.10;

  const addLog = (msg, color = T.muted) =>
    setLog(prev => [{ msg, color, id: Date.now() + Math.random(), time: new Date().toLocaleTimeString("en", { hour12: false }) }, ...prev].slice(0, 60));

  // ── BOT CORE LOOP ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!active) return;
    intervalRef.current = setInterval(() => {
      setTick(t => t + 1);

      // Update prices
      setPrices(prev => {
        const next = {};
        Object.keys(COINS).forEach(sym => {
          if (sym === "SOL" && !solReady) { next[sym] = prev[sym]; return; }
          next[sym] = nextPrice(prev[sym], COINS[sym].vol);
        });
        return next;
      });

      setPriceHistory(prev => {
        const next = {};
        Object.keys(COINS).forEach(sym => {
          const hist = [...(prev[sym] || []), prices[sym]].slice(-20);
          next[sym] = hist;
        });
        return next;
      });

      // Recalc indicators + mode
      const newInds = {}, newModes = {};
      Object.keys(COINS).forEach(sym => {
        const ind = calcIndicators(priceHistory[sym] || [prices[sym]]);
        newInds[sym] = ind;
        newModes[sym] = selectMode(ind.rsi, ind.trend, ind.volatility);
      });
      setIndicators(newInds);
      setModes(newModes);

      // Try to enter trades
      Object.keys(COINS).forEach(sym => {
        if (sym === "SOL" && !solReady) return;
        if (activeTrades[sym]) return;
        if (dailyLoss >= maxDailyLoss) return;

        const ind = newInds[sym];
        const mode = newModes[sym];
        const price = prices[sym];
        const coin = COINS[sym];

        // Entry conditions
        const shouldEnter = (
          (mode === "SCALP" && ind.macd > 0 && ind.rsi > 45 && ind.rsi < 68) ||
          (mode === "SWING" && ind.trend > 0.55 && ind.rsi < 62 && ind.macd > 0) ||
          (mode === "DCA"   && (ind.rsi < 38 || ind.rsi > 70))
        ) && Math.random() > 0.6;

        if (!shouldEnter) return;

        const modeConf = MODES[mode];
        const riskAmt = coin.capital * 0.05;
        const stopDist = price * modeConf.stop;
        const qty = +(riskAmt / stopDist).toFixed(4);
        const stopPrice = +(price * (1 - modeConf.stop)).toFixed(4);
        const targetPrice = +(price * (1 + modeConf.target)).toFixed(4);

        const trade = { sym, entry: price, stop: stopPrice, target: targetPrice, qty, mode, risk: +riskAmt.toFixed(2), time: new Date().toLocaleTimeString("en", { hour12: false }) };
        setActiveTrades(prev => ({ ...prev, [sym]: trade }));
        addLog(`⚡ ${mode} LONG ${sym} @ $${price} | Qty ${qty} | Stop $${stopPrice} | Target $${targetPrice}`, coin.color);
      });

      // Monitor active trades
      setActiveTrades(prev => {
        const next = { ...prev };
        Object.keys(next).forEach(sym => {
          const trade = next[sym];
          const price = prices[sym];
          if (!trade) return;

          const win = price >= trade.target;
          const loss = price <= trade.stop;

          if (win || loss) {
            const tradePnl = +((price - trade.entry) * trade.qty).toFixed(2);
            const closed = { ...trade, exit: price, pnl: tradePnl, status: win ? "WIN" : "LOSS" };

            setClosedTrades(cp => [closed, ...cp].slice(0, 30));
            setPnl(pp => {
              const next = { ...pp, [sym]: +(pp[sym] + tradePnl).toFixed(2), total: +(pp.total + tradePnl).toFixed(2) };
              return next;
            });
            setStats(ss => ({ wins: ss.wins + (win ? 1 : 0), losses: ss.losses + (win ? 0 : 1), trades: ss.trades + 1 }));
            if (!win) setDailyLoss(d => +(d + Math.abs(tradePnl)).toFixed(2));

            addLog(
              win ? `💰 WIN ${sym} | Exit $${price} | PnL +$${tradePnl}` : `❌ STOP ${sym} | Exit $${price} | PnL -$${Math.abs(tradePnl)}`,
              win ? T.green : T.red
            );
            delete next[sym];
          }
        });
        return next;
      });

    }, 3000);
    return () => clearInterval(intervalRef.current);
  }, [active, prices, priceHistory, activeTrades, dailyLoss, solReady, maxDailyLoss]);

  const winRate = stats.trades > 0 ? ((stats.wins / stats.trades) * 100).toFixed(0) : "—";

  return (
    <>
      <style>{CSS}</style>
      <div style={{
        minHeight: "100vh", background: T.bg, color: T.text,
        fontFamily: T.mono, paddingBottom: 48,
        backgroundImage: `radial-gradient(ellipse 60% 40% at 10% 0%, #0a1a3a 0%, transparent 70%),
                          radial-gradient(ellipse 50% 30% at 90% 100%, #1a0a3a 0%, transparent 70%)`,
      }}>

        {/* ── HEADER ── */}
        <div style={{
          background: T.surface, borderBottom: `1px solid ${T.border}`,
          padding: "13px 22px",
          display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              fontSize: 22, width: 38, height: 38, borderRadius: 10,
              background: `linear-gradient(135deg, ${T.cyan}33, ${T.purple}33)`,
              border: `1px solid ${T.cyan}55`,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>🪙</div>
            <div>
              <div style={{ fontSize: 9, color: T.cyan, letterSpacing: ".22em", marginBottom: 1 }}>NOVA BOT FAMILY</div>
              <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: ".04em" }}>CRYPTO BOT v1.0</div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <Tag color={T.cyan}>Coinbase</Tag>
            <Tag color={T.green}>24/7 LIVE</Tag>
            {!solReady && (
              <button onClick={() => { setSolReady(true); addLog("🔓 SOL delegation unlocked — SOL trading activated!", T.gold); }}
                style={{
                  background: T.goldDim, border: `1px solid ${T.gold}66`,
                  color: T.gold, borderRadius: 6, padding: "6px 12px",
                  cursor: "pointer", fontSize: 10, fontFamily: T.mono, fontWeight: 700,
                }}>UNLOCK SOL ⏳</button>
            )}
            <button onClick={() => {
              setActive(b => !b);
              if (!active) {
                setPnl({ XRP: 0, ETH: 0, SOL: 0, total: 0 });
                setDailyLoss(0);
                setStats({ wins: 0, losses: 0, trades: 0 });
                setActiveTrades({});
                setClosedTrades([]);
                setLog([]);
                addLog("🚀 NOVA CRYPTO BOT ACTIVATED — XRP + ETH trading live", T.cyan);
                addLog("📋 Strategy: RSI + MACD + Bollinger Bands | 3 adaptive modes", T.purple);
                addLog("⚠️  Risk: 5% per trade | 10% daily max | 2:1 R/R min", T.gold);
                if (!solReady) addLog("⏳ SOL locked — delegations unlock in ~4 days. Click UNLOCK SOL when ready.", T.gold);
              } else {
                addLog("⏹  Bot paused by user", T.red);
              }
            }} style={{
              background: active ? `${T.red}22` : `${T.cyan}22`,
              border: `1px solid ${active ? T.red : T.cyan}`,
              color: active ? T.red : T.cyan,
              borderRadius: 6, padding: "8px 18px", cursor: "pointer",
              fontSize: 11, fontFamily: T.mono, fontWeight: 800,
              letterSpacing: ".07em", animation: active ? "glow 2s infinite" : "none",
            }}>{active ? "■ PAUSE" : "▶ START"}</button>
          </div>
        </div>

        <div style={{ maxWidth: 1060, margin: "0 auto", padding: "18px 18px", display: "grid", gap: 14 }}>

          {/* ── GLOBAL STATS ── */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
            {[
              { label: "TOTAL P&L", value: `${pnl.total >= 0 ? "+" : ""}$${pnl.total.toFixed(2)}`, color: pnl.total >= 0 ? T.green : T.red },
              { label: "WIN RATE", value: `${winRate}%`, color: Number(winRate) >= 60 ? T.green : T.gold },
              { label: "TRADES", value: `${stats.wins}W / ${stats.losses}L`, color: T.text },
              { label: "DAILY LOSS", value: `$${dailyLoss.toFixed(2)}`, color: dailyLoss > maxDailyLoss * 0.7 ? T.red : T.gold },
              { label: "PORTFOLIO", value: `$${(totalCapital + pnl.total).toFixed(2)}`, color: T.cyan },
              { label: "BOT MODE", value: active ? "RUNNING" : "OFFLINE", color: active ? T.green : T.muted },
            ].map(s => (
              <div key={s.label} style={{
                background: T.card, border: `1px solid ${T.border}`,
                borderRadius: 8, padding: "12px 14px",
              }}>
                <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".15em", marginBottom: 5 }}>{s.label}</div>
                <div style={{ fontSize: 18, fontWeight: 900, color: s.color }}>{s.value}</div>
              </div>
            ))}
          </div>

          {/* ── DAILY LOSS METER ── */}
          <div style={{
            background: T.card, border: `1px solid ${T.border}`, borderRadius: 8,
            padding: "10px 16px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
          }}>
            <span style={{ fontSize: 8, color: T.muted, letterSpacing: ".15em" }}>DAILY LOSS METER</span>
            <div style={{ flex: 1, minWidth: 160 }}>
              <MiniBar value={dailyLoss} max={maxDailyLoss}
                color={dailyLoss < maxDailyLoss * 0.5 ? T.green : dailyLoss < maxDailyLoss * 0.8 ? T.gold : T.red} />
            </div>
            <span style={{ fontSize: 10, color: T.muted }}>${dailyLoss.toFixed(0)} / ${maxDailyLoss.toFixed(0)}</span>
            {dailyLoss >= maxDailyLoss && <Tag color={T.red}>MAX LOSS — HALTED</Tag>}
          </div>

          {/* ── COIN PANELS ── */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
            {Object.entries(COINS).map(([sym, coin]) => {
              const price = prices[sym];
              const ind = indicators[sym];
              const mode = modes[sym];
              const modeConf = MODES[mode];
              const trade = activeTrades[sym];
              const coinPnl = pnl[sym];
              const locked = sym === "SOL" && !solReady;

              return (
                <div key={sym} style={{
                  background: T.card,
                  border: `1px solid ${locked ? T.border : coin.color + "44"}`,
                  borderRadius: 10, overflow: "hidden",
                  opacity: locked ? 0.5 : 1,
                }}>
                  {/* Coin Header */}
                  <div style={{
                    background: coin.color + "12",
                    borderBottom: `1px solid ${coin.color}33`,
                    padding: "10px 14px",
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Pip color={locked ? T.muted : coin.color} pulse={active && !locked} />
                      <span style={{ color: coin.color, fontWeight: 800, fontSize: 16 }}>{sym}</span>
                      {locked && <Tag color={T.gold} sm>LOCKED 4D</Tag>}
                      {!locked && trade && <Tag color={T.green} sm>IN TRADE</Tag>}
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: 16, fontWeight: 800, color: T.text }}>${price?.toFixed(sym === "ETH" ? 2 : 4)}</div>
                      <div style={{ fontSize: 9, color: coinPnl >= 0 ? T.green : T.red }}>
                        Session: {coinPnl >= 0 ? "+" : ""}${coinPnl?.toFixed(2)}
                      </div>
                    </div>
                  </div>

                  {/* Indicators */}
                  <div style={{ padding: "10px 14px", display: "grid", gap: 8 }}>
                    {[
                      { label: "RSI", value: ind?.rsi, max: 100, color: ind?.rsi > 70 ? T.red : ind?.rsi < 30 ? T.green : T.cyan, fmt: v => v?.toFixed(1) },
                      { label: "TREND", value: (ind?.trend || 0) * 100, max: 100, color: T.purple, fmt: v => `${v?.toFixed(0)}%` },
                      { label: "VOLATILITY", value: (ind?.volatility || 0) * 1000, max: 100, color: T.gold, fmt: v => `${(v / 10)?.toFixed(2)}%` },
                    ].map(row => (
                      <div key={row.label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 9, color: T.muted, minWidth: 65, letterSpacing: ".08em" }}>{row.label}</span>
                        <MiniBar value={row.value || 0} max={row.max} color={row.color} />
                        <span style={{ fontSize: 10, color: row.color, minWidth: 36, textAlign: "right" }}>{row.fmt(row.value)}</span>
                      </div>
                    ))}

                    {/* Mode */}
                    <div style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      marginTop: 4, paddingTop: 8, borderTop: `1px solid ${T.border}`,
                    }}>
                      <div>
                        <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".12em", marginBottom: 3 }}>ACTIVE MODE</div>
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          <Tag color={modeConf.color}>{mode}</Tag>
                          <span style={{ fontSize: 9, color: T.muted }}>{modeConf.desc}</span>
                        </div>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <div style={{ fontSize: 8, color: T.muted, marginBottom: 2 }}>MACD</div>
                        <div style={{ fontSize: 11, color: (ind?.macd || 0) >= 0 ? T.green : T.red, fontWeight: 700 }}>
                          {(ind?.macd || 0) >= 0 ? "▲" : "▼"} {Math.abs(ind?.macd || 0).toFixed(4)}
                        </div>
                      </div>
                    </div>

                    {/* Active trade details */}
                    {trade && (
                      <div style={{
                        background: T.green + "10", border: `1px solid ${T.green}33`,
                        borderRadius: 6, padding: "8px 10px", marginTop: 4,
                      }}>
                        <div style={{ fontSize: 8, color: T.green, letterSpacing: ".12em", marginBottom: 6 }}>OPEN POSITION</div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 10px" }}>
                          {[["Entry", `$${trade.entry}`], ["Stop", `$${trade.stop}`], ["Target", `$${trade.target}`], ["Qty", trade.qty]].map(([k, v]) => (
                            <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
                              <span style={{ color: T.muted }}>{k}</span>
                              <span style={{ color: T.text }}>{v}</span>
                            </div>
                          ))}
                        </div>
                        <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "center" }}>
                          <Pip color={T.green} pulse />
                          <span style={{ fontSize: 9, color: T.green }}>MANAGING...</span>
                          <Tag color={modeConf.color} sm>{trade.mode}</Tag>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* ── CLOSED TRADES TABLE ── */}
          {closedTrades.length > 0 && (
            <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden" }}>
              <div style={{
                background: T.surface, borderBottom: `1px solid ${T.border}`,
                padding: "9px 16px", display: "flex", justifyContent: "space-between",
              }}>
                <span style={{ fontSize: 9, color: T.muted, letterSpacing: ".15em" }}>CLOSED TRADES — SESSION</span>
                <span style={{ fontSize: 9, color: T.muted }}>{closedTrades.length} trades</span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                      {["TIME", "COIN", "MODE", "ENTRY", "EXIT", "QTY", "P&L", "RESULT"].map(h => (
                        <th key={h} style={{ padding: "7px 12px", color: T.muted, textAlign: "left", fontSize: 8, letterSpacing: ".12em" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {closedTrades.slice(0, 15).map((t, i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${T.border}44`, animation: i === 0 ? "fadeUp .3s ease" : "none" }}>
                        <td style={{ padding: "7px 12px", color: T.muted }}>{t.time}</td>
                        <td style={{ padding: "7px 12px", color: COINS[t.sym]?.color, fontWeight: 700 }}>{t.sym}</td>
                        <td style={{ padding: "7px 12px" }}><Tag color={MODES[t.mode]?.color} sm>{t.mode}</Tag></td>
                        <td style={{ padding: "7px 12px", color: T.text }}>${t.entry}</td>
                        <td style={{ padding: "7px 12px", color: T.text }}>${t.exit}</td>
                        <td style={{ padding: "7px 12px", color: T.muted }}>{t.qty}</td>
                        <td style={{ padding: "7px 12px", color: t.pnl >= 0 ? T.green : T.red, fontWeight: 700 }}>
                          {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
                        </td>
                        <td style={{ padding: "7px 12px" }}><Tag color={t.status === "WIN" ? T.green : T.red} sm>{t.status}</Tag></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── ACTIVITY LOG ── */}
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden" }}>
            <div style={{ background: T.surface, borderBottom: `1px solid ${T.border}`, padding: "9px 16px" }}>
              <span style={{ fontSize: 9, color: T.muted, letterSpacing: ".15em" }}>BOT ACTIVITY LOG — LIVE</span>
            </div>
            <div style={{ maxHeight: 200, overflowY: "auto", padding: "4px 0" }}>
              {log.length === 0
                ? <div style={{ padding: 20, textAlign: "center", color: T.muted, fontSize: 10 }}>Awaiting activation...</div>
                : log.map(l => (
                  <div key={l.id} style={{
                    padding: "5px 16px", fontSize: 10,
                    borderBottom: `1px solid ${T.border}33`,
                    display: "flex", gap: 12,
                  }}>
                    <span style={{ color: T.muted, flexShrink: 0, fontSize: 9 }}>{l.time}</span>
                    <span style={{ color: l.color }}>{l.msg}</span>
                  </div>
                ))}
            </div>
          </div>

          {/* ── MODE GUIDE ── */}
          <div style={{
            background: T.card, border: `1px solid ${T.borderHi}`,
            borderRadius: 10, padding: "16px 18px",
          }}>
            <div style={{ fontSize: 9, color: T.cyan, letterSpacing: ".2em", marginBottom: 12 }}>
              HOW THE 3 MODES WORK — BOT SWITCHES AUTOMATICALLY
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
              {Object.entries(MODES).map(([key, m]) => (
                <div key={key} style={{
                  background: T.surface, borderRadius: 7, padding: "12px 14px",
                  borderLeft: `3px solid ${m.color}`,
                }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                    <Tag color={m.color}>{key}</Tag>
                    <span style={{ fontSize: 9, color: T.muted }}>{m.desc}</span>
                  </div>
                  <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.6 }}>
                    Target: <span style={{ color: T.green }}>+{(m.target * 100).toFixed(0)}%</span>
                    {" · "}Stop: <span style={{ color: T.red }}>-{(m.stop * 100).toFixed(0)}%</span>
                  </div>
                  <div style={{ fontSize: 9, color: T.muted, marginTop: 4 }}>
                    {key === "SCALP" && "Triggers: High volatility detected"}
                    {key === "SWING" && "Triggers: Strong trend + RSI < 62"}
                    {key === "DCA"   && "Triggers: RSI oversold <38 or overbought >70"}
                  </div>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>
    </>
  );
}
