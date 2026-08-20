import { useState } from "react";

const theme = {
  bg: "#0a0c0f",
  surface: "#111418",
  card: "#161b22",
  border: "#21262d",
  accent: "#00d4aa",
  accentDim: "#00d4aa22",
  accentWarm: "#f0a500",
  accentWarmDim: "#f0a50022",
  red: "#ff4d4f",
  redDim: "#ff4d4f22",
  green: "#00d4aa",
  text: "#e6edf3",
  muted: "#7d8590",
  highlight: "#58a6ff",
};

const tabs = ["Overview", "Stock Filter", "Entry Rules", "Risk Rules", "Bot Roadmap"];

const Tag = ({ color, children }) => (
  <span style={{
    background: color + "22",
    color,
    border: `1px solid ${color}44`,
    borderRadius: 4,
    padding: "2px 8px",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
    fontFamily: "'JetBrains Mono', monospace",
  }}>{children}</span>
);

const Card = ({ children, style = {} }) => (
  <div style={{
    background: theme.card,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: "16px 20px",
    ...style
  }}>{children}</div>
);

const SectionTitle = ({ children, accent = theme.accent }) => (
  <div style={{
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.15em",
    textTransform: "uppercase",
    color: accent,
    marginBottom: 12,
    display: "flex",
    alignItems: "center",
    gap: 8,
  }}>
    <div style={{ width: 3, height: 12, background: accent, borderRadius: 2 }} />
    {children}
  </div>
);

const Row = ({ label, value, color = theme.text }) => (
  <div style={{
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "7px 0",
    borderBottom: `1px solid ${theme.border}`,
    fontSize: 13,
  }}>
    <span style={{ color: theme.muted, fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{label}</span>
    <span style={{ color, fontWeight: 600 }}>{value}</span>
  </div>
);

const Check = ({ ok }) => (
  <span style={{ color: ok ? theme.green : theme.red, fontSize: 14 }}>{ok ? "✓" : "✗"}</span>
);

function OverviewTab() {
  return (
    <div style={{ display: "grid", gap: 16 }}>

      {/* Account + Broker Banner */}
      <div style={{
        background: `linear-gradient(135deg, ${theme.accentDim}, ${theme.accentWarmDim})`,
        border: `1px solid ${theme.accent}44`,
        borderRadius: 8,
        padding: "16px 20px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 12,
      }}>
        <div>
          <div style={{ color: theme.muted, fontSize: 11, fontFamily: "monospace", marginBottom: 4 }}>TRADING PROFILE</div>
          <div style={{ color: theme.text, fontSize: 20, fontWeight: 700 }}>Small Account — Webull</div>
          <div style={{ color: theme.muted, fontSize: 13, marginTop: 4 }}>PDT Rule lifted June 4, 2026 · Unlimited day trades</div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Tag color={theme.accent}>$500–$2,000</Tag>
          <Tag color={theme.accentWarm}>Mixed Style</Tag>
          <Tag color={theme.highlight}>Bot-Ready</Tag>
        </div>
      </div>

      {/* 3 Style Modes */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
        {[
          {
            label: "⚡ Scalp Mode",
            time: "1–5 min charts",
            window: "9:30–10:30 AM",
            signal: "VWAP cross + volume spike",
            target: "+1–3% quick exit",
            color: theme.red,
          },
          {
            label: "🚀 Momentum Mode",
            time: "5 min charts",
            window: "7:00–11:00 AM",
            signal: "Bull flag / flat top breakout",
            target: "+10–20% move",
            color: theme.accent,
          },
          {
            label: "📈 Swing Mode",
            time: "Daily chart",
            window: "End of day setup",
            signal: "EMA 50/200 + FVG fill",
            target: "+20–30% over days",
            color: theme.highlight,
          },
        ].map((m) => (
          <Card key={m.label} style={{ borderTop: `2px solid ${m.color}` }}>
            <div style={{ color: m.color, fontWeight: 700, fontSize: 14, marginBottom: 10 }}>{m.label}</div>
            <Row label="Timeframe" value={m.time} color={theme.text} />
            <Row label="Window" value={m.window} color={theme.text} />
            <Row label="Signal" value={m.signal} color={m.color} />
            <Row label="Target" value={m.target} color={theme.green} />
          </Card>
        ))}
      </div>

      {/* Core Indicators */}
      <Card>
        <SectionTitle>Core Indicator Stack</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
          {[
            { name: "VWAP", role: "Entry trigger", use: "Long above / Short below", color: theme.accent },
            { name: "MACD", role: "Momentum confirm", use: "Crossover = entry / exit signal", color: theme.accentWarm },
            { name: "EMA 50", role: "Intermediate trend", use: "Dynamic S/R level", color: theme.highlight },
            { name: "EMA 200", role: "Macro trend filter", use: "Above = longs only bias", color: theme.highlight },
            { name: "Volume", role: "Participation filter", use: "Must be ≥ 50% of 20-bar avg", color: theme.green },
            { name: "Senkou Span B", role: "Direction filter", use: "Above = long / Below = short", color: "#c792ea" },
            { name: "FVG", role: "Liquidity magnet", use: "Pullback target / entry zone", color: "#ffcb6b" },
            { name: "PDH / PDL", role: "Key levels", use: "Prior day high/low as targets", color: theme.muted },
          ].map((ind) => (
            <div key={ind.name} style={{
              background: theme.surface,
              border: `1px solid ${theme.border}`,
              borderLeft: `3px solid ${ind.color}`,
              borderRadius: 6,
              padding: "10px 12px",
            }}>
              <div style={{ color: ind.color, fontWeight: 700, fontSize: 13, fontFamily: "monospace" }}>{ind.name}</div>
              <div style={{ color: theme.muted, fontSize: 11, marginTop: 2 }}>{ind.role}</div>
              <div style={{ color: theme.text, fontSize: 12, marginTop: 4 }}>{ind.use}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* Pre-Market Checklist */}
      <Card>
        <SectionTitle accent={theme.accentWarm}>Pre-Market Checklist (7:00–9:30 AM)</SectionTitle>
        {[
          "Rate market strength 1–10 (Iran news, macro, futures)",
          "Check gap scanner — top 5 gappers with catalyst",
          "Identify the OBVIOUS stock today",
          "Hot cycle or cold cycle? Adjust aggression accordingly",
          "Check prior day highs/lows on watchlist",
          "Confirm you're rested and mentally ready",
        ].map((item, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "flex-start", gap: 10,
            padding: "8px 0", borderBottom: `1px solid ${theme.border}`,
            fontSize: 13, color: theme.text,
          }}>
            <div style={{
              width: 18, height: 18, border: `1px solid ${theme.accent}`,
              borderRadius: 3, flexShrink: 0, marginTop: 1,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: theme.accent, fontSize: 10,
            }}>□</div>
            {item}
          </div>
        ))}
      </Card>
    </div>
  );
}

function StockFilterTab() {
  const criteria = [
    { label: "Price Range", value: "$1.00 – $20.00", note: "Sweet spot $5–$10", ok: true },
    { label: "Already Up", value: "≥ 10% on the day", note: "Or continuation from prior day", ok: true },
    { label: "Relative Volume", value: "≥ 5x average", note: "STMS: 5x minimum; higher is better", ok: true },
    { label: "News Catalyst", value: "Required", note: "FDA, earnings, partnership, PR", ok: true },
    { label: "Float", value: "< 20 million shares", note: "Under 10M preferred in cold market", ok: true },
    { label: "Market Cap", value: "Small cap", note: "$1–$20 range stocks only", ok: true },
  ];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Card>
        <SectionTitle>Stock Selection Criteria (A-Grade Only)</SectionTitle>
        <div style={{ fontSize: 12, color: theme.muted, marginBottom: 12 }}>
          All 5 criteria must be met. If a stock fails even one — skip it.
        </div>
        {criteria.map((c, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "10px 0", borderBottom: `1px solid ${theme.border}`,
          }}>
            <Check ok={c.ok} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, color: theme.text, fontWeight: 600 }}>{c.label} — <span style={{ color: theme.accent }}>{c.value}</span></div>
              <div style={{ fontSize: 11, color: theme.muted, marginTop: 2 }}>{c.note}</div>
            </div>
          </div>
        ))}
      </Card>

      <Card>
        <SectionTitle accent={theme.accentWarm}>Catalyst Types (Ranked by Strength)</SectionTitle>
        {[
          { rank: "S", cat: "FDA Approval / Drug Trial Result", strength: "🔥🔥🔥🔥🔥" },
          { rank: "A", cat: "Earnings Beat + Guidance Raise", strength: "🔥🔥🔥🔥" },
          { rank: "A", cat: "Major Partnership / Contract Award", strength: "🔥🔥🔥🔥" },
          { rank: "B", cat: "Analyst Upgrade + Price Target Raise", strength: "🔥🔥🔥" },
          { rank: "B", cat: "Sector News / Macro Tailwind", strength: "🔥🔥🔥" },
          { rank: "C", cat: "No News — Sympathy Play", strength: "🔥 (avoid)" },
        ].map((c, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "9px 0", borderBottom: `1px solid ${theme.border}`, fontSize: 13,
          }}>
            <div style={{
              width: 24, height: 24, borderRadius: 4,
              background: c.rank === "S" ? theme.accent : c.rank === "A" ? theme.accentWarm : c.rank === "B" ? theme.highlight : theme.red,
              color: "#000", fontWeight: 900, fontSize: 12,
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>{c.rank}</div>
            <span style={{ flex: 1, color: theme.text }}>{c.cat}</span>
            <span style={{ fontSize: 12 }}>{c.strength}</span>
          </div>
        ))}
      </Card>

      <Card>
        <SectionTitle accent={theme.highlight}>Scanner Settings for Webull</SectionTitle>
        <div style={{ display: "grid", gap: 8 }}>
          {[
            ["Sort by", "% Change (highest first)"],
            ["Price filter", "$1.00 – $20.00"],
            ["Volume filter", "> 500K shares today"],
            ["Relative Volume", "> 5x"],
            ["Market Cap", "Under $500M"],
            ["Time", "Check at 7:00 AM, 9:00 AM, 9:30 AM"],
          ].map(([k, v]) => (
            <div key={k} style={{
              display: "flex", justifyContent: "space-between",
              background: theme.surface, padding: "8px 12px", borderRadius: 6,
              fontSize: 13,
            }}>
              <span style={{ color: theme.muted, fontFamily: "monospace", fontSize: 12 }}>{k}</span>
              <span style={{ color: theme.highlight, fontWeight: 600 }}>{v}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function EntryRulesTab() {
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Momentum / Scalp Entry */}
      <Card style={{ borderTop: `2px solid ${theme.accent}` }}>
        <SectionTitle>Momentum / Scalp Entry (5-Min Chart)</SectionTitle>
        <div style={{ display: "grid", gap: 10 }}>
          {[
            { step: "1", label: "Direction Filter", desc: "Price above Senkou Span B → Longs only. Below → Shorts only." },
            { step: "2", label: "Volume Confirm", desc: "Current volume ≥ 50% of 20-bar average. If not, wait." },
            { step: "3", label: "VWAP Trigger", desc: "Aggressive: Buy first candle that breaks above VWAP. Conservative: Wait for retest — 3-candle confirmation." },
            { step: "4", label: "MACD Confirm", desc: "MACD line crossing above signal line = go. Crossing below signal line = exit." },
            { step: "5", label: "Pattern", desc: "Bull Flag: buy first candle making new high. Flat Top: buy first candle breaking resistance." },
          ].map((s) => (
            <div key={s.step} style={{
              display: "flex", gap: 12, alignItems: "flex-start",
              padding: "10px 0", borderBottom: `1px solid ${theme.border}`,
            }}>
              <div style={{
                width: 26, height: 26, borderRadius: "50%",
                background: theme.accentDim, border: `1px solid ${theme.accent}`,
                color: theme.accent, fontWeight: 700, fontSize: 12,
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              }}>{s.step}</div>
              <div>
                <div style={{ color: theme.accent, fontWeight: 700, fontSize: 13 }}>{s.label}</div>
                <div style={{ color: theme.text, fontSize: 13, marginTop: 3 }}>{s.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Swing Entry */}
      <Card style={{ borderTop: `2px solid ${theme.highlight}` }}>
        <SectionTitle accent={theme.highlight}>Swing Entry (Daily Chart)</SectionTitle>
        <div style={{ display: "grid", gap: 10 }}>
          {[
            { step: "1", label: "Trend Bias", desc: "Price above EMA 200 on daily = bull bias. Below = bear bias." },
            { step: "2", label: "EMA 50 Touch", desc: "Wait for price to pull back to EMA 50. This is your entry zone." },
            { step: "3", label: "FVG Identification", desc: "Mark Fair Value Gaps from prior sessions. These are magnet zones price wants to fill." },
            { step: "4", label: "PDH / PDL Confluence", desc: "Entry near prior day low with FVG support = highest conviction setup." },
            { step: "5", label: "Entry Trigger", desc: "Wait for bullish engulfing or hammer candle at the confluence zone. MACD momentum turning up confirms." },
          ].map((s) => (
            <div key={s.step} style={{
              display: "flex", gap: 12, alignItems: "flex-start",
              padding: "10px 0", borderBottom: `1px solid ${theme.border}`,
            }}>
              <div style={{
                width: 26, height: 26, borderRadius: "50%",
                background: "#58a6ff22", border: `1px solid ${theme.highlight}`,
                color: theme.highlight, fontWeight: 700, fontSize: 12,
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              }}>{s.step}</div>
              <div>
                <div style={{ color: theme.highlight, fontWeight: 700, fontSize: 13 }}>{s.label}</div>
                <div style={{ color: theme.text, fontSize: 13, marginTop: 3 }}>{s.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Exit / Invalidation */}
      <Card style={{ borderTop: `2px solid ${theme.red}` }}>
        <SectionTitle accent={theme.red}>Exit / Invalidation Signals</SectionTitle>
        {[
          ["MACD crosses signal line (bearish)", "EXIT immediately"],
          ["Volume drops below 50% avg", "EXIT — no participation"],
          ["Jackknife / wick rejection candle", "EXIT — reversal signal"],
          ["Price breaks back below VWAP", "EXIT long position"],
          ["3 consecutive losing trades", "DONE for the day"],
          ["Daily max loss hit (-10% account)", "STOP — walk away"],
        ].map(([trigger, action], i) => (
          <div key={i} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "9px 0", borderBottom: `1px solid ${theme.border}`, gap: 8,
          }}>
            <span style={{ color: theme.text, fontSize: 13, flex: 1 }}>⚠ {trigger}</span>
            <Tag color={theme.red}>{action}</Tag>
          </div>
        ))}
      </Card>
    </div>
  );
}

function RiskRulesTab() {
  const [accountSize, setAccountSize] = useState(1000);
  const risk = Math.round(accountSize * 0.05);
  const target = Math.round(accountSize * 0.10);
  const maxLoss = Math.round(accountSize * 0.10);
  const maxLossDaily = Math.round(accountSize * 0.10);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Dynamic Calculator */}
      <Card style={{ borderTop: `2px solid ${theme.accentWarm}` }}>
        <SectionTitle accent={theme.accentWarm}>Risk Calculator</SectionTitle>
        <div style={{ marginBottom: 16 }}>
          <label style={{ color: theme.muted, fontSize: 12, fontFamily: "monospace", display: "block", marginBottom: 6 }}>
            ACCOUNT SIZE: ${accountSize.toLocaleString()}
          </label>
          <input
            type="range" min={500} max={2000} step={100}
            value={accountSize}
            onChange={(e) => setAccountSize(Number(e.target.value))}
            style={{ width: "100%", accentColor: theme.accentWarm }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: theme.muted, fontFamily: "monospace" }}>
            <span>$500</span><span>$2,000</span>
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {[
            { label: "Risk Per Trade (5%)", value: `$${risk}`, color: theme.red },
            { label: "Target Per Trade (10%)", value: `$${target}`, color: theme.green },
            { label: "Daily Max Loss (10%)", value: `-$${maxLossDaily}`, color: theme.red },
            { label: "2:1 R/R Ratio", value: `$${risk} → $${risk * 2}`, color: theme.accentWarm },
          ].map((m) => (
            <div key={m.label} style={{
              background: theme.surface, borderRadius: 6,
              padding: "12px 14px", border: `1px solid ${theme.border}`,
            }}>
              <div style={{ color: theme.muted, fontSize: 11, fontFamily: "monospace" }}>{m.label}</div>
              <div style={{ color: m.color, fontSize: 20, fontWeight: 700, marginTop: 4 }}>{m.value}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* Hard Rules */}
      <Card>
        <SectionTitle>The 3 Hard Rules (Never Break)</SectionTitle>
        {[
          { num: "01", rule: "Risk 5% to make 10%", detail: "Every trade must have a defined stop and 2:1 reward-to-risk minimum." },
          { num: "02", rule: "Daily max loss = 10%", detail: "Hit it and you're done. No revenge trades. Webull lets you set this as an alert." },
          { num: "03", rule: "3 consecutive losers = stop", detail: "Your mindset is compromised. Come back tomorrow. Protect the account above all." },
        ].map((r) => (
          <div key={r.num} style={{
            display: "flex", gap: 14, padding: "12px 0",
            borderBottom: `1px solid ${theme.border}`,
          }}>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 22, fontWeight: 900,
              color: theme.accentWarm, opacity: 0.4, flexShrink: 0, lineHeight: 1,
            }}>{r.num}</div>
            <div>
              <div style={{ color: theme.accentWarm, fontWeight: 700, fontSize: 14 }}>{r.rule}</div>
              <div style={{ color: theme.muted, fontSize: 12, marginTop: 3 }}>{r.detail}</div>
            </div>
          </div>
        ))}
      </Card>

      {/* Profit Trifecta */}
      <Card>
        <SectionTitle accent={theme.highlight}>Profit Trifecta Goals (Your Progression)</SectionTitle>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                {["Goal", "Novice (Wk 1–4)", "Beginner (Mo 2)", "Advanced (Mo 4)", "Pro"].map((h) => (
                  <th key={h} style={{ padding: "8px 10px", color: theme.muted, fontFamily: "monospace", fontSize: 11, textAlign: "left", fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { goal: "Consistency", vals: ["1 week", "2 weeks", "3–5 weeks", "5+ weeks"], colors: [theme.muted, theme.accent, theme.accent, theme.accentWarm] },
                { goal: "Accuracy", vals: ["40–50%", "50–60%", "60–70%", ">70%"], colors: [theme.muted, theme.accent, theme.accent, theme.accentWarm] },
                { goal: "P/L Ratio", vals: ["0.5–1", "1.0–1.5", "1.5–2.0", ">2.0"], colors: [theme.muted, theme.accent, theme.accent, theme.accentWarm] },
              ].map((row) => (
                <tr key={row.goal} style={{ borderBottom: `1px solid ${theme.border}` }}>
                  <td style={{ padding: "10px 10px", color: theme.text, fontWeight: 600 }}>{row.goal}</td>
                  {row.vals.map((v, i) => (
                    <td key={i} style={{ padding: "10px 10px", color: row.colors[i], fontFamily: "monospace" }}>{v}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function BotRoadmapTab() {
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Card style={{ borderTop: `2px solid ${theme.highlight}` }}>
        <SectionTitle accent={theme.highlight}>Bot Development Roadmap</SectionTitle>
        <div style={{ fontSize: 12, color: theme.muted, marginBottom: 14 }}>
          Build in phases — master the strategy manually before automating each layer.
        </div>
        {[
          {
            phase: "Phase 1",
            title: "Manual + Journal",
            timeline: "Weeks 1–4",
            color: theme.accent,
            items: [
              "Paper trade / sim on Webull first",
              "Log every trade: entry, exit, reason, result",
              "Track: accuracy %, P/L ratio, best setups",
              "Goal: identify YOUR highest-win patterns",
            ],
          },
          {
            phase: "Phase 2",
            title: "Signal Dashboard",
            timeline: "Month 2",
            color: theme.accentWarm,
            items: [
              "Build a React dashboard (like this one) that displays live signals",
              "Pull stock data via Webull API or Yahoo Finance",
              "Display: VWAP position, MACD cross alert, Volume ratio",
              "Chart grid: 4-panel view (1min, 5min, 15min, Daily)",
            ],
          },
          {
            phase: "Phase 3",
            title: "Alert Bot",
            timeline: "Month 3",
            color: theme.highlight,
            items: [
              "Bot scans for stocks meeting all 5 criteria",
              "Sends alerts: 'TRAW meets A-grade criteria — check entry'",
              "Tracks your watchlist in real time",
              "No auto-execution yet — YOU make the call",
            ],
          },
          {
            phase: "Phase 4",
            title: "Semi-Auto Bot",
            timeline: "Month 4–6",
            color: "#c792ea",
            items: [
              "Bot identifies setup AND suggests entry/stop/target",
              "You approve or reject each trade",
              "Logs P/L automatically",
              "Backtests your rules against historical data",
            ],
          },
          {
            phase: "Phase 5",
            title: "Full Auto Bot",
            timeline: "Month 6+",
            color: theme.accentWarm,
            items: [
              "Full execution via Webull API",
              "Enforces all risk rules automatically (max loss, stop loss)",
              "Chart grid with live annotations",
              "Performance dashboard with drawdown, win rate, Sharpe ratio",
            ],
          },
        ].map((ph) => (
          <div key={ph.phase} style={{
            borderLeft: `3px solid ${ph.color}`,
            paddingLeft: 16, marginBottom: 20,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <Tag color={ph.color}>{ph.phase}</Tag>
              <span style={{ color: ph.color, fontWeight: 700, fontSize: 15 }}>{ph.title}</span>
              <span style={{ color: theme.muted, fontSize: 12, marginLeft: "auto", fontFamily: "monospace" }}>{ph.timeline}</span>
            </div>
            {ph.items.map((item, i) => (
              <div key={i} style={{
                display: "flex", gap: 8, fontSize: 13, color: theme.text,
                padding: "4px 0",
              }}>
                <span style={{ color: ph.color, flexShrink: 0 }}>→</span>
                {item}
              </div>
            ))}
          </div>
        ))}
      </Card>

      <Card>
        <SectionTitle>Chart Grid Spec (Phase 2 Target)</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {[
            { panel: "Panel 1", tf: "1-Min Chart", use: "Scalp entries / VWAP micro-crosses", color: theme.red },
            { panel: "Panel 2", tf: "5-Min Chart", use: "Main momentum setup / MACD", color: theme.accent },
            { panel: "Panel 3", tf: "15-Min Chart", use: "Trend context / Senkou Span B", color: theme.highlight },
            { panel: "Panel 4", tf: "Daily Chart", use: "Swing bias / EMA 50 & 200 / FVGs", color: theme.accentWarm },
          ].map((p) => (
            <div key={p.panel} style={{
              background: theme.surface, borderRadius: 6, padding: "12px 14px",
              border: `1px solid ${theme.border}`, borderLeft: `3px solid ${p.color}`,
            }}>
              <div style={{ color: p.color, fontFamily: "monospace", fontSize: 11, fontWeight: 700 }}>{p.panel}</div>
              <div style={{ color: theme.text, fontWeight: 700, fontSize: 14, marginTop: 4 }}>{p.tf}</div>
              <div style={{ color: theme.muted, fontSize: 12, marginTop: 4 }}>{p.use}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <SectionTitle accent={theme.accentWarm}>Tech Stack Recommendation</SectionTitle>
        {[
          ["Frontend (Chart Grid)", "React + Recharts or TradingView Lightweight Charts"],
          ["Data Feed", "Webull API / Yahoo Finance / Polygon.io"],
          ["Alerts", "Telegram Bot or Discord Webhook"],
          ["Backend Logic", "Python (pandas, ta-lib for indicators)"],
          ["Backtesting", "Backtrader or VectorBT"],
          ["Execution (Phase 5)", "Webull Python SDK or Alpaca API"],
        ].map(([tech, rec]) => (
          <div key={tech} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "9px 0", borderBottom: `1px solid ${theme.border}`, gap: 8, flexWrap: "wrap",
          }}>
            <span style={{ color: theme.muted, fontFamily: "monospace", fontSize: 12 }}>{tech}</span>
            <span style={{ color: theme.text, fontSize: 13 }}>{rec}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}

export default function TradingStrategy() {
  const [activeTab, setActiveTab] = useState(0);

  const tabContent = [
    <OverviewTab />,
    <StockFilterTab />,
    <EntryRulesTab />,
    <RiskRulesTab />,
    <BotRoadmapTab />,
  ];

  return (
    <div style={{
      background: theme.bg,
      minHeight: "100vh",
      fontFamily: "'Segoe UI', sans-serif",
      color: theme.text,
      padding: "0 0 40px 0",
    }}>
      {/* Header */}
      <div style={{
        background: theme.surface,
        borderBottom: `1px solid ${theme.border}`,
        padding: "16px 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
      }}>
        <div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: theme.accent, letterSpacing: "0.2em", marginBottom: 2 }}>NOVA TRADING SYSTEM</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: theme.text }}>Small Account Strategy v1.0</div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Tag color={theme.accent}>Webull</Tag>
          <Tag color={theme.accentWarm}>PDT-Free June 4</Tag>
          <Tag color={theme.highlight}>Bot-Ready</Tag>
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        background: theme.surface,
        borderBottom: `1px solid ${theme.border}`,
        padding: "0 24px",
        display: "flex",
        gap: 0,
        overflowX: "auto",
      }}>
        {tabs.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === i ? `2px solid ${theme.accent}` : "2px solid transparent",
              color: activeTab === i ? theme.accent : theme.muted,
              padding: "12px 16px",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: activeTab === i ? 700 : 400,
              whiteSpace: "nowrap",
              transition: "all 0.15s",
            }}
          >{tab}</button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: "20px 24px", maxWidth: 900, margin: "0 auto" }}>
        {tabContent[activeTab]}
      </div>
    </div>
  );
}
