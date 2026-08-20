import { useState, useEffect, useRef } from "react";

// ── THEME ─────────────────────────────────────────────────────────────────────
const T = {
  bg:       "#060810",
  surface:  "#0c0f1a",
  card:     "#101420",
  border:   "#1a1f35",
  borderHi: "#2a3060",
  green:    "#00ff88",
  greenDim: "#00ff8822",
  red:      "#ff3355",
  redDim:   "#ff335522",
  gold:     "#ffb800",
  goldDim:  "#ffb80022",
  blue:     "#4d9fff",
  blueDim:  "#4d9fff22",
  purple:   "#a855f7",
  text:     "#e2e8ff",
  muted:    "#4a5280",
  mono:     "'Courier New', monospace",
};

// ── UTILITIES ─────────────────────────────────────────────────────────────────
const fmt$ = (n, decimals = 2) =>
  (n >= 0 ? "+" : "") + n.toFixed(decimals);
const fmtPct = (n) => (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
const now = () => new Date().toLocaleTimeString("en-US", { hour12: false });

// ── FAKE MARKET DATA SIMULATION ───────────────────────────────────────────────
const TICKERS = ["TRAW","DRUG","MESO","MGRM","SHOT","CYTO","VERB","GHSI","AGRI","ILUS"];
const CATALYSTS = ["FDA Approval","Earnings Beat","Contract Win","Short Squeeze","Merger","Phase 3 Trial","Revenue Beat","Partnership","Uplisting","Reverse Split"];

function generateStock() {
  const ticker = TICKERS[Math.floor(Math.random() * TICKERS.length)];
  const price = +(1 + Math.random() * 18).toFixed(2);
  const changeP = +(10 + Math.random() * 120).toFixed(2);
  const relVol = +(5 + Math.random() * 45).toFixed(1);
  const floatM = +(1 + Math.random() * 18).toFixed(1);
  const catalyst = CATALYSTS[Math.floor(Math.random() * CATALYSTS.length)];
  const score = Math.round(
    (price <= 20 ? 10 : 0) +
    (changeP >= 10 ? 10 : 0) +
    (relVol >= 5 ? 15 : 0) +
    15 + // catalyst always present in sim
    (floatM < 20 ? 10 : 0) +
    (Math.random() > 0.4 ? 10 : 0) + // EMA200
    (Math.random() > 0.4 ? 10 : 0) + // Senkou
    (Math.random() > 0.3 ? 15 : 0) + // VWAP
    (Math.random() > 0.5 ? 10 : 0) + // MACD
    (Math.random() > 0.5 ? 10 : 0)   // Volume
  );
  return { ticker, price, changeP, relVol, floatM, catalyst, score, id: Date.now() + Math.random() };
}

function generateTrade(stock) {
  const entry = stock.price;
  const stop = +(entry * 0.95).toFixed(2);
  const target = +(entry * 1.10).toFixed(2);
  const shares = Math.floor(100 / entry);
  const risk = +((entry - stop) * shares).toFixed(2);
  return { ...stock, entry, stop, target, shares, risk, status: "OPEN", pnl: 0, time: now() };
}

// ── PULSE ANIMATION ───────────────────────────────────────────────────────────
const pulseKF = `
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
@keyframes scanline { 0%{transform:translateY(-100%)} 100%{transform:translateY(400%)} }
@keyframes blink { 0%,100%{opacity:1} 49%{opacity:1} 50%{opacity:0} 99%{opacity:0} }
@keyframes slideIn { from{transform:translateX(-20px);opacity:0} to{transform:translateX(0);opacity:1} }
@keyframes glow { 0%,100%{box-shadow:0 0 8px #00ff8844} 50%{box-shadow:0 0 24px #00ff8888} }
`;

// ── SUB COMPONENTS ────────────────────────────────────────────────────────────
const Dot = ({ color, pulse }) => (
  <span style={{
    width: 8, height: 8, borderRadius: "50%",
    background: color, display: "inline-block",
    animation: pulse ? "pulse 1.5s infinite" : "none",
    boxShadow: `0 0 6px ${color}`,
    flexShrink: 0,
  }} />
);

const Tag = ({ color, children }) => (
  <span style={{
    background: color + "22", color, border: `1px solid ${color}44`,
    borderRadius: 3, padding: "1px 7px", fontSize: 10,
    fontFamily: T.mono, fontWeight: 700, letterSpacing: "0.06em",
    textTransform: "uppercase", whiteSpace: "nowrap",
  }}>{children}</span>
);

const Bar = ({ value, max, color }) => (
  <div style={{ background: T.border, borderRadius: 2, height: 4, overflow: "hidden", flex: 1 }}>
    <div style={{
      height: "100%", borderRadius: 2,
      width: `${Math.min(100, (value / max) * 100)}%`,
      background: color, transition: "width 0.6s ease",
    }} />
  </div>
);

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function NovaBotCommandCenter() {
  const [botActive, setBotActive] = useState(false);
  const [scanResults, setScanResults] = useState([]);
  const [activeTrades, setActiveTrades] = useState([]);
  const [closedTrades, setClosedTrades] = useState([]);
  const [log, setLog] = useState([]);
  const [stats, setStats] = useState({ totalPnl: 0, wins: 0, losses: 0, trades: 0 });
  const [scanTick, setScanTick] = useState(0);
  const [phase, setPhase] = useState("IDLE"); // IDLE | SCANNING | SIGNAL | EXECUTING
  const [dailyLoss, setDailyLoss] = useState(0);
  const [accountSize] = useState(1500);
  const maxDailyLoss = accountSize * 0.10;
  const intervalRef = useRef(null);
  const logRef = useRef(null);

  const addLog = (msg, color = T.muted) => {
    setLog(prev => [{ msg, color, time: now(), id: Date.now() + Math.random() }, ...prev].slice(0, 80));
  };

  // ── BOT BRAIN LOOP ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!botActive) { setPhase("IDLE"); return; }
    intervalRef.current = setInterval(() => {
      setScanTick(t => t + 1);
      const hour = new Date().getHours();
      const inTradingWindow = hour >= 7 && hour < 11;

      if (!inTradingWindow) {
        setPhase("IDLE");
        addLog(`⏸  Outside trading window (7AM–11AM EST) — scanner paused`, T.muted);
        return;
      }

      if (dailyLoss >= maxDailyLoss) {
        setPhase("IDLE");
        addLog(`🛑  Daily max loss hit ($${maxDailyLoss.toFixed(0)}) — bot stopped for today`, T.red);
        setBotActive(false);
        return;
      }

      // SCAN phase
      setPhase("SCANNING");
      addLog(`🔍  Running gap scanner — filtering by price $1–$20, rel-vol ≥5x, float <20M...`, T.blue);

      setTimeout(() => {
        const found = Math.random() > 0.35;
        if (!found) { addLog(`   No A-grade setups found this scan cycle`, T.muted); setPhase("IDLE"); return; }

        const stock = generateStock();
        setScanResults(prev => [stock, ...prev].slice(0, 6));
        addLog(`📡  Candidate: $${stock.ticker} | +${stock.changeP}% | ${stock.relVol}x RVol | Float ${stock.floatM}M | ${stock.catalyst}`, T.gold);

        if (stock.score < 65) { addLog(`   Score ${stock.score}% — below 65% threshold, skipping`, T.muted); setPhase("IDLE"); return; }

        setPhase("SIGNAL");
        addLog(`✅  Score ${stock.score}% — A-Grade setup confirmed`, T.green);
        addLog(`📊  Checking VWAP position, MACD crossover, Senkou Span B filter...`, T.blue);

        setTimeout(() => {
          const trade = generateTrade(stock);
          setPhase("EXECUTING");
          addLog(`⚡  Executing LONG $${trade.ticker} @ $${trade.entry} | ${trade.shares} shares | Stop $${trade.stop} | Target $${trade.target}`, T.green);

          setActiveTrades(prev => [trade, ...prev].slice(0, 5));

          // Simulate trade outcome
          setTimeout(() => {
            const win = Math.random() > 0.35;
            const exitPrice = win
              ? +(trade.entry * (1.05 + Math.random() * 0.08)).toFixed(2)
              : +(trade.entry * (0.93 + Math.random() * 0.04)).toFixed(2);
            const pnl = +((exitPrice - trade.entry) * trade.shares).toFixed(2);

            setActiveTrades(prev => prev.filter(t => t.id !== trade.id));
            const closed = { ...trade, exitPrice, pnl, status: win ? "WIN" : "LOSS" };
            setClosedTrades(prev => [closed, ...prev].slice(0, 20));

            setStats(prev => ({
              totalPnl: +(prev.totalPnl + pnl).toFixed(2),
              wins: prev.wins + (win ? 1 : 0),
              losses: prev.losses + (win ? 0 : 1),
              trades: prev.trades + 1,
            }));

            if (!win) setDailyLoss(d => +(d + Math.abs(pnl)).toFixed(2));

            addLog(
              win
                ? `💰  $${trade.ticker} CLOSED WIN | Exit $${exitPrice} | PnL ${fmt$(pnl)}`
                : `❌  $${trade.ticker} STOPPED OUT | Exit $${exitPrice} | PnL ${fmt$(pnl)}`,
              win ? T.green : T.red
            );
            setPhase("IDLE");
          }, 4000 + Math.random() * 6000);

        }, 1500);
      }, 2000);

    }, 8000 + Math.random() * 4000);

    return () => clearInterval(intervalRef.current);
  }, [botActive, dailyLoss, maxDailyLoss]);

  const winRate = stats.trades > 0 ? ((stats.wins / stats.trades) * 100).toFixed(0) : 0;
  const phaseColor = phase === "SCANNING" ? T.blue : phase === "SIGNAL" ? T.gold : phase === "EXECUTING" ? T.green : T.muted;

  return (
    <>
      <style>{pulseKF}</style>
      <div style={{
        background: T.bg, minHeight: "100vh", color: T.text,
        fontFamily: T.mono, padding: "0 0 40px",
        backgroundImage: `radial-gradient(ellipse at 20% 10%, #0d1a3a 0%, transparent 60%),
                          radial-gradient(ellipse at 80% 80%, #0a1a0a 0%, transparent 60%)`,
      }}>

        {/* ── HEADER ── */}
        <div style={{
          background: T.surface, borderBottom: `1px solid ${T.border}`,
          padding: "14px 24px",
          display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 8,
              background: `linear-gradient(135deg, ${T.green}33, ${T.blue}33)`,
              border: `1px solid ${T.green}66`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 18,
            }}>⚡</div>
            <div>
              <div style={{ fontSize: 9, color: T.green, letterSpacing: "0.25em", marginBottom: 2 }}>NOVA TRADING SYSTEM</div>
              <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "0.05em", color: T.text }}>AUTOMATED BOT v1.0</div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {/* Phase indicator */}
            <div style={{
              background: phaseColor + "15",
              border: `1px solid ${phaseColor}44`,
              borderRadius: 6, padding: "6px 14px",
              display: "flex", alignItems: "center", gap: 8, fontSize: 11,
            }}>
              <Dot color={phaseColor} pulse={phase !== "IDLE"} />
              <span style={{ color: phaseColor, letterSpacing: "0.1em" }}>{phase}</span>
            </div>

            {/* Master switch */}
            <button onClick={() => {
              setBotActive(b => !b);
              if (!botActive) {
                setDailyLoss(0);
                setStats({ totalPnl: 0, wins: 0, losses: 0, trades: 0 });
                setScanResults([]);
                setClosedTrades([]);
                setLog([]);
                addLog("🚀  NOVA BOT ACTIVATED — Small Trades Momentum Strategy loaded", T.green);
                addLog("📋  Rules: Price $1–$20 | RVol ≥5x | Up ≥10% | Float <20M | Catalyst required", T.blue);
                addLog("⚠️   Risk: 5% per trade | 10% daily max loss | 2:1 R/R minimum", T.gold);
              } else {
                addLog("⏹  Bot deactivated by user", T.red);
              }
            }} style={{
              background: botActive ? T.redDim : T.greenDim,
              border: `1px solid ${botActive ? T.red : T.green}`,
              color: botActive ? T.red : T.green,
              borderRadius: 6, padding: "8px 20px", cursor: "pointer",
              fontSize: 12, fontFamily: T.mono, fontWeight: 700,
              letterSpacing: "0.08em", transition: "all 0.2s",
              animation: botActive ? "glow 2s infinite" : "none",
            }}>
              {botActive ? "■ STOP BOT" : "▶ START BOT"}
            </button>
          </div>
        </div>

        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "20px 20px", display: "grid", gap: 16 }}>

          {/* ── STATS ROW ── */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
            {[
              { label: "TODAY'S P&L", value: fmt$(stats.totalPnl), color: stats.totalPnl >= 0 ? T.green : T.red, sub: `${stats.trades} trades` },
              { label: "WIN RATE", value: `${winRate}%`, color: Number(winRate) >= 60 ? T.green : T.gold, sub: `${stats.wins}W / ${stats.losses}L` },
              { label: "DAILY RISK USED", value: `$${dailyLoss.toFixed(0)}`, color: dailyLoss > maxDailyLoss * 0.7 ? T.red : T.gold, sub: `Limit $${maxDailyLoss.toFixed(0)}` },
              { label: "ACCOUNT SIZE", value: `$${accountSize.toLocaleString()}`, color: T.blue, sub: "Webull margin" },
              { label: "ACTIVE TRADES", value: activeTrades.length, color: activeTrades.length > 0 ? T.green : T.muted, sub: activeTrades.length > 0 ? "In market" : "Flat" },
              { label: "BOT STATUS", value: botActive ? "LIVE" : "OFFLINE", color: botActive ? T.green : T.muted, sub: phase },
            ].map(s => (
              <div key={s.label} style={{
                background: T.card, border: `1px solid ${T.border}`,
                borderRadius: 8, padding: "14px 16px",
              }}>
                <div style={{ fontSize: 9, color: T.muted, letterSpacing: "0.15em", marginBottom: 6 }}>{s.label}</div>
                <div style={{ fontSize: 22, fontWeight: 900, color: s.color, lineHeight: 1 }}>{s.value}</div>
                <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>{s.sub}</div>
              </div>
            ))}
          </div>

          {/* ── RISK METER ── */}
          <div style={{
            background: T.card, border: `1px solid ${T.border}`,
            borderRadius: 8, padding: "12px 18px",
            display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap",
          }}>
            <span style={{ fontSize: 9, color: T.muted, letterSpacing: "0.15em", flexShrink: 0 }}>DAILY LOSS METER</span>
            <div style={{ flex: 1, minWidth: 200 }}>
              <Bar value={dailyLoss} max={maxDailyLoss}
                color={dailyLoss < maxDailyLoss * 0.5 ? T.green : dailyLoss < maxDailyLoss * 0.75 ? T.gold : T.red} />
            </div>
            <span style={{ fontSize: 10, color: T.muted, flexShrink: 0 }}>${dailyLoss.toFixed(0)} / ${maxDailyLoss.toFixed(0)}</span>
            {dailyLoss >= maxDailyLoss && <Tag color={T.red}>MAX LOSS HIT — TRADING HALTED</Tag>}
          </div>

          {/* ── TWO COLUMN MIDDLE ── */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>

            {/* SCANNER RESULTS */}
            <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, overflow: "hidden" }}>
              <div style={{
                background: T.surface, borderBottom: `1px solid ${T.border}`,
                padding: "10px 16px",
                display: "flex", justifyContent: "space-between", alignItems: "center",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Dot color={botActive ? T.blue : T.muted} pulse={botActive} />
                  <span style={{ fontSize: 10, color: T.blue, letterSpacing: "0.15em" }}>LIVE SCANNER</span>
                </div>
                <span style={{ fontSize: 9, color: T.muted }}>
                  {botActive ? `Cycle #${scanTick}` : "Offline"}
                </span>
              </div>
              {scanResults.length === 0 ? (
                <div style={{ padding: 24, textAlign: "center", color: T.muted, fontSize: 11 }}>
                  {botActive ? "Scanning for A-grade setups..." : "Start bot to begin scanning"}
                </div>
              ) : (
                scanResults.map((s, i) => (
                  <div key={s.id} style={{
                    padding: "10px 16px",
                    borderBottom: `1px solid ${T.border}`,
                    animation: i === 0 ? "slideIn 0.3s ease" : "none",
                    display: "flex", flexDirection: "column", gap: 6,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ color: T.gold, fontWeight: 700, fontSize: 14 }}>${s.ticker}</span>
                        <Tag color={s.score >= 80 ? T.green : s.score >= 65 ? T.gold : T.red}>
                          {s.score >= 80 ? "STRONG GO" : s.score >= 65 ? "GO" : "SKIP"}
                        </Tag>
                      </div>
                      <span style={{ color: T.green, fontSize: 12, fontWeight: 700 }}>+{s.changeP}%</span>
                    </div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 10, color: T.muted }}>${s.price}</span>
                      <span style={{ fontSize: 10, color: T.blue }}>{s.relVol}x RVol</span>
                      <span style={{ fontSize: 10, color: T.purple }}>{s.floatM}M float</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Bar value={s.score} max={100}
                        color={s.score >= 80 ? T.green : s.score >= 65 ? T.gold : T.red} />
                      <span style={{ fontSize: 10, color: T.muted, flexShrink: 0 }}>{s.score}%</span>
                    </div>
                    <div style={{ fontSize: 10, color: T.muted }}>📰 {s.catalyst}</div>
                  </div>
                ))
              )}
            </div>

            {/* ACTIVE TRADES */}
            <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, overflow: "hidden" }}>
              <div style={{
                background: T.surface, borderBottom: `1px solid ${T.border}`,
                padding: "10px 16px",
                display: "flex", justifyContent: "space-between", alignItems: "center",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Dot color={activeTrades.length > 0 ? T.green : T.muted} pulse={activeTrades.length > 0} />
                  <span style={{ fontSize: 10, color: T.green, letterSpacing: "0.15em" }}>ACTIVE TRADES</span>
                </div>
                <Tag color={activeTrades.length > 0 ? T.green : T.muted}>{activeTrades.length} OPEN</Tag>
              </div>
              {activeTrades.length === 0 ? (
                <div style={{ padding: 24, textAlign: "center", color: T.muted, fontSize: 11 }}>No open positions</div>
              ) : activeTrades.map(t => (
                <div key={t.id} style={{
                  padding: "12px 16px", borderBottom: `1px solid ${T.border}`,
                  animation: "slideIn 0.3s ease",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <span style={{ color: T.gold, fontWeight: 700, fontSize: 15 }}>${t.ticker}</span>
                    <Tag color={T.green}>LONG</Tag>
                  </div>
                  {[
                    ["Entry", `$${t.entry}`, T.blue],
                    ["Stop", `$${t.stop}`, T.red],
                    ["Target", `$${t.target}`, T.green],
                    ["Shares", t.shares, T.text],
                    ["Risk", `$${t.risk}`, T.gold],
                  ].map(([k, v, c]) => (
                    <div key={k} style={{
                      display: "flex", justifyContent: "space-between",
                      fontSize: 11, padding: "3px 0", borderBottom: `1px solid ${T.border}44`,
                    }}>
                      <span style={{ color: T.muted }}>{k}</span>
                      <span style={{ color: c }}>{v}</span>
                    </div>
                  ))}
                  <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
                    <Dot color={T.green} pulse />
                    <span style={{ fontSize: 10, color: T.green, animation: "blink 1s infinite" }}>
                      MANAGING POSITION...
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── TRADE LOG ── */}
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, overflow: "hidden" }}>
            <div style={{
              background: T.surface, borderBottom: `1px solid ${T.border}`,
              padding: "10px 16px",
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <span style={{ fontSize: 10, color: T.muted, letterSpacing: "0.15em" }}>BOT ACTIVITY LOG</span>
              <span style={{ fontSize: 9, color: T.muted }}>{log.length} entries</span>
            </div>
            <div ref={logRef} style={{
              maxHeight: 220, overflowY: "auto", padding: "4px 0",
              scrollbarWidth: "thin", scrollbarColor: `${T.border} transparent`,
            }}>
              {log.length === 0 ? (
                <div style={{ padding: 20, textAlign: "center", color: T.muted, fontSize: 11 }}>
                  Awaiting bot activation...
                </div>
              ) : log.map(l => (
                <div key={l.id} style={{
                  padding: "5px 16px", fontSize: 11,
                  borderBottom: `1px solid ${T.border}44`,
                  display: "flex", gap: 12, alignItems: "flex-start",
                }}>
                  <span style={{ color: T.muted, flexShrink: 0, fontSize: 10 }}>{l.time}</span>
                  <span style={{ color: l.color }}>{l.msg}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── CLOSED TRADES ── */}
          {closedTrades.length > 0 && (
            <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, overflow: "hidden" }}>
              <div style={{
                background: T.surface, borderBottom: `1px solid ${T.border}`,
                padding: "10px 16px",
              }}>
                <span style={{ fontSize: 10, color: T.muted, letterSpacing: "0.15em" }}>CLOSED TRADES — TODAY</span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                      {["TIME","TICKER","ENTRY","EXIT","SHARES","P&L","STATUS"].map(h => (
                        <th key={h} style={{
                          padding: "8px 14px", color: T.muted, textAlign: "left",
                          fontSize: 9, letterSpacing: "0.12em", fontWeight: 600,
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {closedTrades.map((t, i) => (
                      <tr key={i} style={{
                        borderBottom: `1px solid ${T.border}44`,
                        background: i % 2 === 0 ? T.surface + "44" : "transparent",
                      }}>
                        <td style={{ padding: "8px 14px", color: T.muted }}>{t.time}</td>
                        <td style={{ padding: "8px 14px", color: T.gold, fontWeight: 700 }}>${t.ticker}</td>
                        <td style={{ padding: "8px 14px", color: T.text }}>${t.entry}</td>
                        <td style={{ padding: "8px 14px", color: T.text }}>${t.exitPrice}</td>
                        <td style={{ padding: "8px 14px", color: T.muted }}>{t.shares}</td>
                        <td style={{ padding: "8px 14px", color: t.pnl >= 0 ? T.green : T.red, fontWeight: 700 }}>
                          {fmt$(t.pnl)}
                        </td>
                        <td style={{ padding: "8px 14px" }}>
                          <Tag color={t.status === "WIN" ? T.green : T.red}>{t.status}</Tag>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── BOT LOGIC BLUEPRINT ── */}
          <div style={{
            background: T.card, border: `1px solid ${T.borderHi}`,
            borderRadius: 8, padding: "18px 20px",
          }}>
            <div style={{ fontSize: 9, color: T.blue, letterSpacing: "0.2em", marginBottom: 14 }}>
              BOT LOGIC BLUEPRINT — WHAT THE BOT DOES EVERY CYCLE
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
              {[
                { step: "01", title: "SCAN", color: T.blue, desc: "Every 8–12s: filter all stocks for price $1–$20, up ≥10%, RVol ≥5x, float <20M, news catalyst" },
                { step: "02", title: "SCORE", color: T.gold, desc: "Run 14-point entry scorer. Must hit ≥65% to proceed. VWAP, MACD, Senkou Span B all checked automatically" },
                { step: "03", title: "SIZE", color: T.purple, desc: "Calculate shares: risk exactly 5% of account. Set stop loss at -5%, target at +10%. 2:1 R/R enforced" },
                { step: "04", title: "EXECUTE", color: T.green, desc: "Send market buy order via Webull OpenAPI. Immediately place stop-loss and target limit orders" },
                { step: "05", title: "MANAGE", color: T.green, desc: "Monitor: if MACD crosses bearish, exit. If jackknife rejection, exit. Trail stop if +5% ahead" },
                { step: "06", title: "PROTECT", color: T.red, desc: "3 consecutive losses → pause 30 min. Daily loss hits 10% → full stop. No exceptions, ever" },
              ].map(s => (
                <div key={s.step} style={{
                  background: T.surface, borderRadius: 6, padding: "12px 14px",
                  borderLeft: `3px solid ${s.color}`,
                }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                    <span style={{ color: s.color, fontSize: 9, letterSpacing: "0.1em" }}>STEP {s.step}</span>
                    <span style={{ color: s.color, fontWeight: 700, fontSize: 12 }}>{s.title}</span>
                  </div>
                  <div style={{ color: T.muted, fontSize: 11, lineHeight: 1.5 }}>{s.desc}</div>
                </div>
              ))}
            </div>
          </div>

          {/* ── BUILD PHASES ── */}
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: "18px 20px" }}>
            <div style={{ fontSize: 9, color: T.purple, letterSpacing: "0.2em", marginBottom: 14 }}>
              YOUR BOT BUILD JOURNEY — 4 PHASES TO FULL AUTOMATION
            </div>
            <div style={{ display: "grid", gap: 0 }}>
              {[
                { phase: "PHASE 1", title: "This Dashboard", status: "✅ DONE", color: T.green, desc: "Visual brain — you understand exactly what the bot will do. Rules loaded." },
                { phase: "PHASE 2", title: "Paper Bot", status: "NEXT →", color: T.gold, desc: "Python script runs the scanner and scorer using real market data. Simulates trades. You verify the logic works before any real money." },
                { phase: "PHASE 3", title: "Alert Bot", status: "MONTH 2", color: T.blue, desc: "Bot texts/Telegrams you: 'TRAW setup — 82% score. Enter $4.20?' You reply YES or NO. Bot executes on your approval." },
                { phase: "PHASE 4", title: "Full Auto", status: "MONTH 3–4", color: T.purple, desc: "Bot finds, enters, manages, exits, logs — zero human involvement. Daily P&L report sent to your phone every night." },
              ].map((p, i) => (
                <div key={i} style={{
                  display: "flex", gap: 14, padding: "12px 0",
                  borderBottom: i < 3 ? `1px solid ${T.border}` : "none",
                }}>
                  <div style={{
                    fontWeight: 900, fontSize: 9, color: p.color,
                    letterSpacing: "0.1em", minWidth: 60, flexShrink: 0, paddingTop: 2,
                  }}>{p.phase}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span style={{ color: p.color, fontWeight: 700, fontSize: 13 }}>{p.title}</span>
                      <Tag color={p.color}>{p.status}</Tag>
                    </div>
                    <div style={{ color: T.muted, fontSize: 11, lineHeight: 1.5 }}>{p.desc}</div>
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
