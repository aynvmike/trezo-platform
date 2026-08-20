import { useState, useEffect } from "react";

// ─── CHECKS CONFIG ────────────────────────────────────────────────────────────
// Each check has: id, label, detail, weight (points), category, required (must-have)
const CHECKS = [
  // STOCK QUALITY — must all pass
  { id: "price",    category: "Stock Quality", required: true,  weight: 10, label: "Price is $1–$20",            detail: "Sweet spot $5–$10 for small account" },
  { id: "up10",     category: "Stock Quality", required: true,  weight: 10, label: "Stock already up ≥ 10%",     detail: "Must show existing strength" },
  { id: "relvol",   category: "Stock Quality", required: true,  weight: 15, label: "Relative Volume ≥ 5x",       detail: "High participation = predictable moves" },
  { id: "catalyst", category: "Stock Quality", required: true,  weight: 15, label: "News catalyst present",      detail: "Earnings, FDA, PR, partnership" },
  { id: "float",    category: "Stock Quality", required: true,  weight: 10, label: "Float < 20M shares",         detail: "Low supply = explosive moves" },
  // TREND — direction filters
  { id: "ema200",   category: "Trend Filter",  required: true,  weight: 10, label: "Price above EMA 200",        detail: "Macro bull bias confirmed" },
  { id: "senkou",   category: "Trend Filter",  required: true,  weight: 10, label: "Price above Senkou Span B",  detail: "Long trades only above this line" },
  // ENTRY TRIGGERS — timing
  { id: "vwap",     category: "Entry Trigger", required: true,  weight: 15, label: "Price crossed above VWAP",   detail: "Core entry signal — aggressive or conservative" },
  { id: "macd",     category: "Entry Trigger", required: false, weight: 10, label: "MACD bullish crossover",     detail: "MACD line above signal line = momentum confirmed" },
  { id: "volume2",  category: "Entry Trigger", required: false, weight: 10, label: "Volume ≥ 50% of 20-bar avg", detail: "Confirms real participation at entry" },
  // PATTERN — setup type
  { id: "pattern",  category: "Pattern",       required: false, weight: 10, label: "Bull flag or flat top seen", detail: "Clearest high-probability entry patterns" },
  { id: "ema50",    category: "Pattern",       required: false, weight: 5,  label: "Price above EMA 50",         detail: "Intermediate trend support" },
  // RISK
  { id: "pdh",      category: "Risk / Levels", required: false, weight: 5,  label: "Entry near FVG or PDL zone", detail: "Fair Value Gap or Prior Day Low = low-risk entry zone" },
  { id: "rr",       category: "Risk / Levels", required: false, weight: 10, label: "2:1 R/R visible on chart",   detail: "Stop loss defined, target is 2x the risk" },
];

const CATEGORIES = ["Stock Quality", "Trend Filter", "Entry Trigger", "Pattern", "Risk / Levels"];

const CAT_COLORS = {
  "Stock Quality": "#00d4aa",
  "Trend Filter":  "#58a6ff",
  "Entry Trigger": "#f0a500",
  "Pattern":       "#c792ea",
  "Risk / Levels": "#ff7b72",
};

const MAX_SCORE = CHECKS.reduce((s, c) => s + c.weight, 0);
const REQUIRED_IDS = CHECKS.filter(c => c.required).map(c => c.id);

function getVerdict(score, pct, missingRequired) {
  if (missingRequired.length > 0) return { label: "NO TRADE", color: "#ff4d4f", bg: "#ff4d4f18", emoji: "🚫", msg: `Missing required: ${missingRequired.slice(0,2).join(", ")}` };
  if (pct >= 80) return { label: "STRONG GO", color: "#00d4aa", bg: "#00d4aa18", emoji: "🚀", msg: "All systems aligned. Execute with confidence." };
  if (pct >= 65) return { label: "GO",        color: "#7ee787", bg: "#7ee78718", emoji: "✅", msg: "Good setup. Size down slightly, manage risk." };
  if (pct >= 50) return { label: "WAIT",      color: "#f0a500", bg: "#f0a50018", emoji: "⏳", msg: "Setup forming. Wait for more confirmation." };
  return            { label: "NO TRADE",    color: "#ff4d4f", bg: "#ff4d4f18", emoji: "🚫", msg: "Too many signals missing. Skip this trade." };
}

// ─── ANIMATED RING ────────────────────────────────────────────────────────────
function ScoreRing({ pct, color }) {
  const r = 54, cx = 64, cy = 64;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;
  return (
    <svg width={128} height={128} style={{ display: "block" }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#21262d" strokeWidth={10} />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={10}
        strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: "stroke-dasharray 0.5s ease, stroke 0.3s ease" }}
      />
      <text x={cx} y={cy - 8} textAnchor="middle" fill={color}
        style={{ fontSize: 22, fontWeight: 900, fontFamily: "monospace" }}>{pct}%</text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill="#7d8590"
        style={{ fontSize: 10, fontFamily: "monospace" }}>SCORE</text>
    </svg>
  );
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────
export default function TradeEntryScorer() {
  const [checked, setChecked] = useState({});
  const [ticker, setTicker] = useState("");
  const [tradeType, setTradeType] = useState("LONG");
  const [logs, setLogs] = useState([]);
  const [flash, setFlash] = useState(false);

  const toggle = (id) => setChecked(prev => ({ ...prev, [id]: !prev[id] }));
  const reset = () => { setChecked({}); setTicker(""); };

  const score = CHECKS.reduce((s, c) => s + (checked[c.id] ? c.weight : 0), 0);
  const pct = Math.round((score / MAX_SCORE) * 100);
  const missingRequired = REQUIRED_IDS.filter(id => !checked[id]);
  const verdict = getVerdict(score, pct, missingRequired);

  // Flash on verdict change
  useEffect(() => {
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 400);
    return () => clearTimeout(t);
  }, [verdict.label]);

  const logTrade = () => {
    if (!ticker) return;
    const entry = {
      time: new Date().toLocaleTimeString(),
      ticker: ticker.toUpperCase(),
      type: tradeType,
      score: pct,
      verdict: verdict.label,
      checks: Object.keys(checked).filter(k => checked[k]).length,
    };
    setLogs(prev => [entry, ...prev].slice(0, 10));
    reset();
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0a0c0f",
      color: "#e6edf3",
      fontFamily: "'Segoe UI', 'Helvetica Neue', sans-serif",
      padding: "0 0 60px 0",
    }}>

      {/* ── HEADER ── */}
      <div style={{
        background: "#111418",
        borderBottom: "1px solid #21262d",
        padding: "14px 20px",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10,
      }}>
        <div>
          <div style={{ fontFamily: "monospace", fontSize: 9, color: "#00d4aa", letterSpacing: "0.2em", marginBottom: 2 }}>NOVA TRADING SYSTEM</div>
          <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "-0.02em" }}>Trade Entry Scorer</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            value={ticker}
            onChange={e => setTicker(e.target.value.toUpperCase())}
            placeholder="TICKER"
            maxLength={6}
            style={{
              background: "#161b22", border: "1px solid #21262d", borderRadius: 6,
              color: "#e6edf3", padding: "7px 12px", fontSize: 14, fontFamily: "monospace",
              width: 90, fontWeight: 700, letterSpacing: "0.05em",
              outline: "none",
            }}
          />
          {["LONG","SHORT"].map(t => (
            <button key={t} onClick={() => setTradeType(t)} style={{
              background: tradeType === t ? (t === "LONG" ? "#00d4aa22" : "#ff4d4f22") : "transparent",
              border: `1px solid ${tradeType === t ? (t === "LONG" ? "#00d4aa" : "#ff4d4f") : "#21262d"}`,
              color: tradeType === t ? (t === "LONG" ? "#00d4aa" : "#ff4d4f") : "#7d8590",
              borderRadius: 6, padding: "7px 14px", cursor: "pointer", fontSize: 12, fontWeight: 700,
            }}>{t}</button>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 860, margin: "0 auto", padding: "20px 16px", display: "grid", gap: 16 }}>

        {/* ── VERDICT BANNER ── */}
        <div style={{
          background: verdict.bg,
          border: `1px solid ${verdict.color}44`,
          borderRadius: 10,
          padding: "16px 20px",
          display: "flex",
          alignItems: "center",
          gap: 20,
          flexWrap: "wrap",
          transition: "all 0.3s ease",
          boxShadow: flash ? `0 0 20px ${verdict.color}44` : "none",
        }}>
          <ScoreRing pct={pct} color={verdict.color} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 28, fontWeight: 900, color: verdict.color, letterSpacing: "-0.02em", lineHeight: 1 }}>
              {verdict.emoji} {verdict.label}
            </div>
            <div style={{ color: "#7d8590", fontSize: 13, marginTop: 6 }}>{verdict.msg}</div>
            {ticker && (
              <div style={{ marginTop: 8, fontFamily: "monospace", fontSize: 13, color: "#e6edf3" }}>
                <span style={{ color: tradeType === "LONG" ? "#00d4aa" : "#ff4d4f" }}>{tradeType}</span>
                {" "}<strong>{ticker}</strong>
                {" · "}{Object.values(checked).filter(Boolean).length} of {CHECKS.length} checks passed
              </div>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <button onClick={logTrade} disabled={!ticker} style={{
              background: verdict.color, color: "#000", border: "none",
              borderRadius: 6, padding: "10px 20px", cursor: ticker ? "pointer" : "not-allowed",
              fontWeight: 800, fontSize: 13, opacity: ticker ? 1 : 0.4,
            }}>LOG TRADE</button>
            <button onClick={reset} style={{
              background: "transparent", color: "#7d8590", border: "1px solid #21262d",
              borderRadius: 6, padding: "8px 20px", cursor: "pointer", fontSize: 12,
            }}>RESET</button>
          </div>
        </div>

        {/* ── CHECKLIST BY CATEGORY ── */}
        {CATEGORIES.map(cat => {
          const catChecks = CHECKS.filter(c => c.category === cat);
          const catColor = CAT_COLORS[cat];
          const passed = catChecks.filter(c => checked[c.id]).length;
          return (
            <div key={cat} style={{
              background: "#111418",
              border: "1px solid #21262d",
              borderRadius: 10,
              overflow: "hidden",
            }}>
              {/* Category Header */}
              <div style={{
                background: catColor + "14",
                borderBottom: "1px solid #21262d",
                padding: "10px 16px",
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 3, height: 14, background: catColor, borderRadius: 2 }} />
                  <span style={{ fontFamily: "monospace", fontSize: 11, fontWeight: 700, color: catColor, letterSpacing: "0.1em" }}>
                    {cat.toUpperCase()}
                  </span>
                </div>
                <span style={{ fontFamily: "monospace", fontSize: 11, color: "#7d8590" }}>
                  {passed}/{catChecks.length}
                </span>
              </div>

              {/* Checks */}
              {catChecks.map((c, i) => {
                const isChecked = !!checked[c.id];
                return (
                  <div
                    key={c.id}
                    onClick={() => toggle(c.id)}
                    style={{
                      display: "flex", alignItems: "flex-start", gap: 14,
                      padding: "12px 16px",
                      borderBottom: i < catChecks.length - 1 ? "1px solid #21262d" : "none",
                      cursor: "pointer",
                      background: isChecked ? catColor + "0a" : "transparent",
                      transition: "background 0.15s",
                    }}
                  >
                    {/* Checkbox */}
                    <div style={{
                      width: 20, height: 20, borderRadius: 5, flexShrink: 0, marginTop: 1,
                      background: isChecked ? catColor : "transparent",
                      border: `2px solid ${isChecked ? catColor : "#30363d"}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      transition: "all 0.15s",
                    }}>
                      {isChecked && <span style={{ color: "#000", fontSize: 12, fontWeight: 900 }}>✓</span>}
                    </div>

                    {/* Label */}
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span style={{
                          fontSize: 14, fontWeight: 600,
                          color: isChecked ? catColor : "#e6edf3",
                          transition: "color 0.15s",
                        }}>{c.label}</span>
                        {c.required && (
                          <span style={{
                            background: "#ff7b7222", color: "#ff7b72",
                            border: "1px solid #ff7b7244",
                            borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
                            fontFamily: "monospace", letterSpacing: "0.05em",
                          }}>REQUIRED</span>
                        )}
                      </div>
                      <div style={{ fontSize: 12, color: "#7d8590", marginTop: 2 }}>{c.detail}</div>
                    </div>

                    {/* Points */}
                    <div style={{
                      fontFamily: "monospace", fontSize: 12, fontWeight: 700, flexShrink: 0,
                      color: isChecked ? catColor : "#30363d",
                    }}>+{c.weight}pt</div>
                  </div>
                );
              })}
            </div>
          );
        })}

        {/* ── SCORE BREAKDOWN ── */}
        <div style={{
          background: "#111418", border: "1px solid #21262d",
          borderRadius: 10, padding: "16px",
        }}>
          <div style={{
            fontFamily: "monospace", fontSize: 10, color: "#7d8590",
            letterSpacing: "0.15em", marginBottom: 12,
          }}>SCORE BREAKDOWN BY CATEGORY</div>
          {CATEGORIES.map(cat => {
            const catChecks = CHECKS.filter(c => c.category === cat);
            const earned = catChecks.reduce((s, c) => s + (checked[c.id] ? c.weight : 0), 0);
            const max = catChecks.reduce((s, c) => s + c.weight, 0);
            const catPct = Math.round((earned / max) * 100);
            const color = CAT_COLORS[cat];
            return (
              <div key={cat} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 12 }}>
                  <span style={{ color: "#7d8590", fontFamily: "monospace" }}>{cat}</span>
                  <span style={{ color, fontFamily: "monospace", fontWeight: 700 }}>{earned}/{max}pt</span>
                </div>
                <div style={{ height: 6, background: "#21262d", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{
                    height: "100%", background: color, borderRadius: 3,
                    width: `${catPct}%`, transition: "width 0.4s ease",
                  }} />
                </div>
              </div>
            );
          })}
        </div>

        {/* ── TRADE LOG ── */}
        {logs.length > 0 && (
          <div style={{
            background: "#111418", border: "1px solid #21262d",
            borderRadius: 10, overflow: "hidden",
          }}>
            <div style={{
              background: "#161b22", borderBottom: "1px solid #21262d",
              padding: "10px 16px",
              fontFamily: "monospace", fontSize: 10, color: "#7d8590", letterSpacing: "0.15em",
            }}>SESSION TRADE LOG</div>
            {logs.map((log, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 16px",
                borderBottom: i < logs.length - 1 ? "1px solid #21262d" : "none",
                fontSize: 13,
              }}>
                <span style={{ color: "#7d8590", fontFamily: "monospace", fontSize: 11 }}>{log.time}</span>
                <span style={{ fontFamily: "monospace", fontWeight: 700, color: "#e6edf3", minWidth: 60 }}>{log.ticker}</span>
                <span style={{ color: log.type === "LONG" ? "#00d4aa" : "#ff4d4f", fontSize: 11, fontWeight: 700 }}>{log.type}</span>
                <span style={{ fontFamily: "monospace", color: "#58a6ff" }}>{log.score}%</span>
                <span style={{
                  marginLeft: "auto",
                  color: log.verdict === "STRONG GO" ? "#00d4aa" : log.verdict === "GO" ? "#7ee787" : log.verdict === "WAIT" ? "#f0a500" : "#ff4d4f",
                  fontWeight: 700, fontSize: 12,
                }}>{log.verdict}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── HOW THIS BECOMES YOUR BOT ── */}
        <div style={{
          background: "#0d1117",
          border: "1px solid #58a6ff33",
          borderRadius: 10,
          padding: "16px 18px",
        }}>
          <div style={{ fontFamily: "monospace", fontSize: 10, color: "#58a6ff", letterSpacing: "0.15em", marginBottom: 10 }}>
            HOW THIS BECOMES YOUR BOT
          </div>
          {[
            { phase: "Now",     text: "Use this scorer manually while paper trading. Check boxes as you read the chart." },
            { phase: "Phase 2", text: "Bot reads the chart automatically and checks these boxes for you in real time." },
            { phase: "Phase 3", text: "Bot sends you an alert when score hits 65%+ — you just approve the trade." },
            { phase: "Phase 4", text: "Bot executes the trade automatically on Webull when score hits 80%+." },
          ].map(({ phase, text }) => (
            <div key={phase} style={{
              display: "flex", gap: 12, padding: "7px 0",
              borderBottom: "1px solid #21262d", fontSize: 13,
            }}>
              <span style={{
                color: "#58a6ff", fontFamily: "monospace", fontSize: 11,
                fontWeight: 700, minWidth: 55, flexShrink: 0,
              }}>{phase}</span>
              <span style={{ color: "#7d8590" }}>{text}</span>
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}
