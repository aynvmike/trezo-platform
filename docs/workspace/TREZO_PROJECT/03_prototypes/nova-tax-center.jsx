import { useState, useRef } from "react";

// ── TAX BRACKETS 2025 ─────────────────────────────────────────────────────────
const TAX_CONFIG = {
  brackets: {
    single:   [{ max: 11600, rate: 0.10 }, { max: 47150, rate: 0.12 }, { max: 100525, rate: 0.22 }, { max: 191950, rate: 0.24 }, { max: 243725, rate: 0.32 }, { max: 609350, rate: 0.35 }, { max: Infinity, rate: 0.37 }],
    married_joint: [{ max: 23200, rate: 0.10 }, { max: 94300, rate: 0.12 }, { max: 201050, rate: 0.22 }, { max: 383900, rate: 0.24 }, { max: 487450, rate: 0.32 }, { max: 731200, rate: 0.35 }, { max: Infinity, rate: 0.37 }],
    married_sep:   [{ max: 11600, rate: 0.10 }, { max: 47150, rate: 0.12 }, { max: 100525, rate: 0.22 }, { max: 191950, rate: 0.24 }, { max: 243725, rate: 0.32 }, { max: 365600, rate: 0.35 }, { max: Infinity, rate: 0.37 }],
    head:          [{ max: 16550, rate: 0.10 }, { max: 63100, rate: 0.12 }, { max: 100500, rate: 0.22 }, { max: 191950, rate: 0.24 }, { max: 243700, rate: 0.32 }, { max: 609350, rate: 0.35 }, { max: Infinity, rate: 0.37 }],
  },
  ltcg: { // Long-term capital gains rates
    single:        [{ max: 47025, rate: 0.00 }, { max: 518900, rate: 0.15 }, { max: Infinity, rate: 0.20 }],
    married_joint: [{ max: 94050, rate: 0.00 }, { max: 583750, rate: 0.15 }, { max: Infinity, rate: 0.20 }],
    married_sep:   [{ max: 47025, rate: 0.00 }, { max: 291850, rate: 0.15 }, { max: Infinity, rate: 0.20 }],
    head:          [{ max: 63000, rate: 0.00 }, { max: 551350, rate: 0.15 }, { max: Infinity, rate: 0.20 }],
  },
  netInvestmentTax: 0.038, // 3.8% NIIT on high earners
  standardDeduction: { single: 14600, married_joint: 29200, married_sep: 14600, head: 21900 },
};

const FILING_LABELS = { single: "Single", married_joint: "Married Filing Jointly", married_sep: "Married Filing Separately", head: "Head of Household" };
const INCOME_BRACKETS = ["Under $11,600", "$11,600–$47,150", "$47,150–$100,525", "$100,525–$191,950", "$191,950–$243,725", "Over $243,725"];
const INCOME_VALUES =   [8000, 30000, 70000, 140000, 215000, 300000];

// ── TAX MATH ──────────────────────────────────────────────────────────────────
function getMarginalRate(income, filing) {
  const brackets = TAX_CONFIG.brackets[filing];
  for (const b of brackets) if (income <= b.max) return b.rate;
  return 0.37;
}
function getLTCGRate(income, filing) {
  const brackets = TAX_CONFIG.ltcg[filing];
  for (const b of brackets) if (income <= b.max) return b.rate;
  return 0.20;
}
function calcTaxOwed(gains, rate) { return Math.max(0, gains * rate); }

// ── PALETTE ───────────────────────────────────────────────────────────────────
const C = {
  bg:      "#f8f4ef",
  surface: "#ffffff",
  card:    "#fdfaf7",
  border:  "#e8e0d8",
  borderD: "#d4c8bc",
  ink:     "#1a1410",
  inkMid:  "#5c4f44",
  inkDim:  "#9c8c7e",
  red:     "#c0392b",
  redDim:  "#fdf0ee",
  green:   "#1a7a4a",
  greenDim:"#edf7f2",
  gold:    "#b8860b",
  goldDim: "#fdf8ed",
  blue:    "#1a4a8a",
  blueDim: "#edf2fb",
  accent:  "#8b4513",
  accentDim:"#fdf5f0",
};

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700;900&family=Source+Code+Pro:wght@400;600&display=swap');
  * { box-sizing: border-box; }
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: ${C.border}; }
  ::-webkit-scrollbar-thumb { background: ${C.inkDim}; border-radius: 3px; }
  @keyframes fadeIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
  @keyframes slideIn { from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:translateX(0)} }
`;

// ── COMPONENTS ────────────────────────────────────────────────────────────────
const mono = "'Source Code Pro', monospace";
const serif = "'Playfair Display', Georgia, serif";

const Divider = () => <div style={{ height: 1, background: C.border, margin: "4px 0" }} />;

const StatBox = ({ label, value, sub, color = C.ink, accent = C.border }) => (
  <div style={{
    background: C.surface, border: `1px solid ${accent}`,
    borderRadius: 6, padding: "14px 16px",
    borderLeft: `3px solid ${color}`,
  }}>
    <div style={{ fontSize: 9, color: C.inkDim, letterSpacing: ".15em", textTransform: "uppercase", fontFamily: mono, marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 700, color, fontFamily: serif }}>{value}</div>
    {sub && <div style={{ fontSize: 10, color: C.inkDim, marginTop: 3, fontFamily: mono }}>{sub}</div>}
  </div>
);

const Tag = ({ color, bg, children }) => (
  <span style={{
    background: bg, color, border: `1px solid ${color}44`,
    borderRadius: 3, padding: "1px 7px", fontSize: 9,
    fontFamily: mono, fontWeight: 600, letterSpacing: ".06em", textTransform: "uppercase",
  }}>{children}</span>
);

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function NovaTaxCenter() {
  const [tab, setTab] = useState("dashboard");
  const [settings, setSettings] = useState({
    filing: "single",
    incomeBracket: 1, // index into INCOME_VALUES
    taxYear: 2025,
  });

  // ── TRADE LOG STATE ────────────────────────────────────────────────────────
  const [trades, setTrades] = useState([
    { id: 1, date: "2025-01-15", type: "stock",  symbol: "TRAW",  proceeds: 340,  cost: 280,  holdDays: 1,  category: "day_trade" },
    { id: 2, date: "2025-02-03", type: "crypto", symbol: "XRP",   proceeds: 520,  cost: 390,  holdDays: 45, category: "short_term" },
    { id: 3, date: "2025-03-12", type: "crypto", symbol: "ETH",   proceeds: 890,  cost: 1100, holdDays: 120,category: "long_term" },
    { id: 4, date: "2025-04-01", type: "stock",  symbol: "DRUG",  proceeds: 180,  cost: 240,  holdDays: 1,  category: "day_trade" },
    { id: 5, date: "2025-05-08", type: "crypto", symbol: "SOL",   proceeds: 760,  cost: 580,  holdDays: 200,category: "long_term" },
  ]);

  const [dividends, setDividends] = useState([
    { id: 1, date: "2025-01-20", symbol: "NVDY",  amount: 27.08,  rocPct: 0,    qualified: false },
    { id: 2, date: "2025-01-27", symbol: "GOOY",  amount: 60.18,  rocPct: 97.9, qualified: false },
    { id: 3, date: "2025-02-03", symbol: "AIYY",  amount: 63.27,  rocPct: 96.1, qualified: false },
    { id: 4, date: "2025-02-10", symbol: "AMZY",  amount: 47.62,  rocPct: 97.7, qualified: false },
    { id: 5, date: "2025-02-17", symbol: "TSLY",  amount: 36.43,  rocPct: 100,  qualified: false },
    { id: 6, date: "2025-03-03", symbol: "NVDY",  amount: 27.08,  rocPct: 0,    qualified: false },
    { id: 7, date: "2025-03-10", symbol: "GOOY",  amount: 60.18,  rocPct: 97.9, qualified: false },
  ]);

  // ── NEW ENTRY FORMS ────────────────────────────────────────────────────────
  const [newTrade, setNewTrade] = useState({ date: "", type: "stock", symbol: "", proceeds: "", cost: "", holdDays: "1" });
  const [newDiv, setNewDiv] = useState({ date: "", symbol: "", amount: "", rocPct: "0" });

  const income = INCOME_VALUES[settings.incomeBracket];
  const marginalRate = getMarginalRate(income, settings.filing);
  const ltcgRate = getLTCGRate(income, settings.filing);

  // ── CALCULATIONS ──────────────────────────────────────────────────────────
  const tradeCalcs = trades.map(t => {
    const pnl = t.proceeds - t.cost;
    const isLong = t.holdDays >= 365;
    const rate = isLong ? ltcgRate : marginalRate;
    const taxOwed = pnl > 0 ? calcTaxOwed(pnl, rate) : 0;
    const taxSaved = pnl < 0 ? Math.abs(pnl) * marginalRate : 0;
    return { ...t, pnl, isLong, rate, taxOwed, taxSaved };
  });

  const divCalcs = dividends.map(d => {
    const rocAmt = d.amount * (d.rocPct / 100);
    const taxableAmt = d.amount - rocAmt;
    const taxOwed = calcTaxOwed(taxableAmt, marginalRate);
    return { ...d, rocAmt, taxableAmt, taxOwed };
  });

  // ── SUMMARY TOTALS ─────────────────────────────────────────────────────────
  const totalPnl = tradeCalcs.reduce((s, t) => s + t.pnl, 0);
  const stGains = tradeCalcs.filter(t => !t.isLong && t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
  const ltGains = tradeCalcs.filter(t => t.isLong && t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
  const losses = tradeCalcs.filter(t => t.pnl < 0).reduce((s, t) => s + t.pnl, 0);
  const tradeTax = tradeCalcs.reduce((s, t) => s + t.taxOwed, 0);
  const divTaxable = divCalcs.reduce((s, d) => s + d.taxableAmt, 0);
  const divTax = divCalcs.reduce((s, d) => s + d.taxOwed, 0);
  const totalTax = tradeTax + divTax;
  const totalDivIncome = dividends.reduce((s, d) => s + d.amount, 0);
  const netAfterTax = totalPnl + totalDivIncome - totalTax;

  // ── QUARTERLY ESTIMATES ───────────────────────────────────────────────────
  const quarters = ["Q1 (Jan–Mar)", "Q2 (Apr–Jun)", "Q3 (Jul–Sep)", "Q4 (Oct–Dec)"];
  const qDue = ["Apr 15", "Jun 17", "Sep 16", "Jan 15, 2026"];
  const qTax = [totalTax * 0.25, totalTax * 0.25, totalTax * 0.25, totalTax * 0.25];

  // ── ADD TRADE ─────────────────────────────────────────────────────────────
  const addTrade = () => {
    if (!newTrade.date || !newTrade.symbol || !newTrade.proceeds || !newTrade.cost) return;
    const hold = parseInt(newTrade.holdDays) || 1;
    setTrades(prev => [...prev, {
      id: Date.now(), ...newTrade,
      proceeds: parseFloat(newTrade.proceeds),
      cost: parseFloat(newTrade.cost),
      holdDays: hold,
      category: hold >= 365 ? "long_term" : hold <= 1 ? "day_trade" : "short_term",
    }]);
    setNewTrade({ date: "", type: "stock", symbol: "", proceeds: "", cost: "", holdDays: "1" });
  };

  const addDiv = () => {
    if (!newDiv.date || !newDiv.symbol || !newDiv.amount) return;
    setDividends(prev => [...prev, { id: Date.now(), ...newDiv, amount: parseFloat(newDiv.amount), rocPct: parseFloat(newDiv.rocPct) || 0, qualified: false }]);
    setNewDiv({ date: "", symbol: "", amount: "", rocPct: "0" });
  };

  // ── CSV EXPORT ────────────────────────────────────────────────────────────
  const exportCSV = () => {
    const rows = [
      ["DATE", "TYPE", "SYMBOL", "PROCEEDS", "COST BASIS", "P&L", "HOLD DAYS", "TERM", "TAX RATE", "TAX OWED"],
      ...tradeCalcs.map(t => [t.date, t.type.toUpperCase(), t.symbol, t.proceeds.toFixed(2), t.cost.toFixed(2), t.pnl.toFixed(2), t.holdDays, t.isLong ? "LONG" : "SHORT", `${(t.rate * 100).toFixed(0)}%`, t.taxOwed.toFixed(2)]),
      [], ["DIVIDENDS", "", "", "", "", "", "", "", "", ""],
      ["DATE", "SYMBOL", "TOTAL DIST", "ROC %", "ROC AMOUNT", "TAXABLE AMT", "TAX RATE", "TAX OWED"],
      ...divCalcs.map(d => [d.date, d.symbol, d.amount.toFixed(2), `${d.rocPct}%`, d.rocAmt.toFixed(2), d.taxableAmt.toFixed(2), `${(marginalRate * 100).toFixed(0)}%`, d.taxOwed.toFixed(2)]),
      [], ["SUMMARY"],
      ["Total Trading P&L", totalPnl.toFixed(2)],
      ["ST Gains", stGains.toFixed(2)],
      ["LT Gains", ltGains.toFixed(2)],
      ["Losses", losses.toFixed(2)],
      ["Total Dividend Income", totalDivIncome.toFixed(2)],
      ["Taxable Dividends", divTaxable.toFixed(2)],
      ["Estimated Total Tax", totalTax.toFixed(2)],
      ["Net After Tax", netAfterTax.toFixed(2)],
    ];
    const csv = rows.map(r => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `nova_tax_${settings.taxYear}.csv`; a.click();
  };

  const TABS = ["dashboard", "trades", "dividends", "quarterly", "settings"];

  const inputStyle = {
    background: C.surface, border: `1px solid ${C.border}`,
    borderRadius: 5, padding: "7px 10px", fontSize: 12,
    fontFamily: mono, color: C.ink, outline: "none", width: "100%",
  };

  const btnStyle = (color) => ({
    background: color, border: "none", borderRadius: 5,
    padding: "8px 16px", cursor: "pointer", fontSize: 11,
    fontFamily: mono, fontWeight: 600, color: C.surface,
    letterSpacing: ".05em",
  });

  return (
    <>
      <style>{CSS}</style>
      <div style={{ background: C.bg, minHeight: "100vh", fontFamily: mono, color: C.ink, paddingBottom: 60 }}>

        {/* ── HEADER ── */}
        <div style={{
          background: C.ink, color: C.bg,
          padding: "18px 28px",
          display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12,
        }}>
          <div>
            <div style={{ fontSize: 9, letterSpacing: ".25em", color: C.inkDim, marginBottom: 3, fontFamily: mono }}>NOVA BOT FAMILY</div>
            <div style={{ fontFamily: serif, fontSize: 22, fontWeight: 900, letterSpacing: ".02em" }}>Tax Command Center</div>
            <div style={{ fontSize: 10, color: "#9c8c7e", marginTop: 2, fontFamily: mono }}>
              {settings.taxYear} · {FILING_LABELS[settings.filing]} · Marginal Rate {(marginalRate * 100).toFixed(0)}% · LTCG Rate {(ltcgRate * 100).toFixed(0)}%
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Tag color={C.green} bg={C.surface}>All Sources</Tag>
            <Tag color={C.blue} bg={C.surface}>2025 Tax Year</Tag>
            <button onClick={exportCSV} style={btnStyle(C.accent)}>⬇ Export CSV</button>
          </div>
        </div>

        {/* ── TABS ── */}
        <div style={{
          background: C.surface, borderBottom: `1px solid ${C.border}`,
          padding: "0 28px", display: "flex", gap: 0, overflowX: "auto",
        }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: "none", border: "none", cursor: "pointer",
              borderBottom: tab === t ? `2px solid ${C.accent}` : "2px solid transparent",
              color: tab === t ? C.accent : C.inkDim,
              padding: "12px 18px", fontSize: 11, fontFamily: mono,
              fontWeight: tab === t ? 700 : 400, letterSpacing: ".08em",
              textTransform: "uppercase", whiteSpace: "nowrap",
            }}>{t}</button>
          ))}
        </div>

        <div style={{ maxWidth: 1000, margin: "0 auto", padding: "22px 24px" }}>

          {/* ══ DASHBOARD TAB ══ */}
          {tab === "dashboard" && (
            <div style={{ display: "grid", gap: 16, animation: "fadeIn .3s ease" }}>

              {/* Top stats */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
                <StatBox label="Total P&L" value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`} color={totalPnl >= 0 ? C.green : C.red} sub="All trades combined" />
                <StatBox label="Dividend Income" value={`$${totalDivIncome.toFixed(2)}`} color={C.blue} sub={`$${divTaxable.toFixed(2)} taxable after ROC`} />
                <StatBox label="Estimated Tax Owed" value={`$${totalTax.toFixed(2)}`} color={C.red} sub={`Set aside now`} />
                <StatBox label="Net After Tax" value={`$${netAfterTax.toFixed(2)}`} color={netAfterTax >= 0 ? C.green : C.red} sub="Keep this" />
                <StatBox label="ST Gains" value={`$${stGains.toFixed(2)}`} color={C.gold} sub={`Taxed at ${(marginalRate * 100).toFixed(0)}%`} />
                <StatBox label="LT Gains" value={`$${ltGains.toFixed(2)}`} color={C.green} sub={`Taxed at ${(ltcgRate * 100).toFixed(0)}%`} />
              </div>

              {/* Tax breakdown */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "18px 20px" }}>
                  <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 700, marginBottom: 14, color: C.ink }}>Tax Breakdown</div>
                  {[
                    { label: "Short-Term Trading Tax", value: tradeCalcs.filter(t => !t.isLong).reduce((s, t) => s + t.taxOwed, 0), color: C.red },
                    { label: "Long-Term Trading Tax", value: tradeCalcs.filter(t => t.isLong).reduce((s, t) => s + t.taxOwed, 0), color: C.gold },
                    { label: "YieldMax Dividend Tax", value: divTax, color: C.blue },
                    { label: "Capital Loss Offset", value: losses * marginalRate, color: C.green, prefix: "–" },
                    { label: "TOTAL ESTIMATED TAX", value: totalTax, color: C.red, bold: true },
                  ].map((row, i) => (
                    <div key={i} style={{
                      display: "flex", justifyContent: "space-between",
                      padding: "8px 0", borderBottom: `1px solid ${C.border}`,
                      fontSize: 12,
                    }}>
                      <span style={{ color: C.inkMid, fontWeight: row.bold ? 700 : 400 }}>{row.label}</span>
                      <span style={{ color: row.color, fontWeight: 700, fontFamily: mono }}>
                        {row.prefix || ""} ${Math.abs(row.value).toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>

                <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "18px 20px" }}>
                  <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 700, marginBottom: 14 }}>Key Tax Rules for You</div>
                  {[
                    { rule: "Day Trades (≤1 day)", treatment: `Ordinary income — ${(marginalRate * 100).toFixed(0)}% rate`, color: C.red },
                    { rule: "Short Term (<1 year)", treatment: `Ordinary income — ${(marginalRate * 100).toFixed(0)}% rate`, color: C.gold },
                    { rule: "Long Term (>1 year)", treatment: `Preferential rate — ${(ltcgRate * 100).toFixed(0)}%`, color: C.green },
                    { rule: "YieldMax Distributions", treatment: "Mostly ROC — reduces cost basis", color: C.blue },
                    { rule: "ROC Portion", treatment: "Not taxed NOW — taxed on sale", color: C.inkMid },
                    { rule: "Capital Losses", treatment: "Offset gains dollar for dollar", color: C.green },
                    { rule: "Wash Sale Rule", treatment: "No repurchase within 30 days", color: C.red },
                    { rule: "Crypto = Property", treatment: "Every trade is a taxable event", color: C.gold },
                  ].map((r, i) => (
                    <div key={i} style={{
                      display: "flex", justifyContent: "space-between", alignItems: "flex-start",
                      padding: "7px 0", borderBottom: `1px solid ${C.border}`, gap: 8,
                    }}>
                      <span style={{ fontSize: 11, color: C.inkMid, flex: 1 }}>{r.rule}</span>
                      <span style={{ fontSize: 10, color: r.color, fontWeight: 600, textAlign: "right", maxWidth: 180 }}>{r.treatment}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* YieldMax ROC Explainer */}
              <div style={{
                background: C.blueDim, border: `1px solid ${C.blue}44`,
                borderRadius: 8, padding: "16px 20px",
              }}>
                <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 700, color: C.blue, marginBottom: 10 }}>
                  📌 YieldMax ROC — The Hidden Tax Advantage
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, fontSize: 11, color: C.inkMid, lineHeight: 1.7 }}>
                  <div><strong style={{ color: C.ink }}>What is ROC?</strong><br />Return of Capital means the fund is returning your own money. It is NOT taxable income when received.</div>
                  <div><strong style={{ color: C.ink }}>When do you pay?</strong><br />ROC reduces your cost basis. You only pay tax when you SELL the ETF shares — and at the lower long-term rate if held 1+ year.</div>
                  <div><strong style={{ color: C.ink }}>Your situation</strong><br />~78% of your YieldMax distributions are ROC. Only ~22% is taxable income right now. This is a significant tax deferral advantage.</div>
                  <div><strong style={{ color: C.ink }}>Watch out for</strong><br />If ROC reduces your cost basis to $0, further ROC becomes a capital gain. Track your adjusted cost basis annually.</div>
                </div>
              </div>

            </div>
          )}

          {/* ══ TRADES TAB ══ */}
          {tab === "trades" && (
            <div style={{ display: "grid", gap: 16, animation: "fadeIn .3s ease" }}>

              {/* Add trade form */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "18px 20px" }}>
                <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 700, marginBottom: 14 }}>Log a Trade</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
                  <div>
                    <div style={{ fontSize: 9, color: C.inkDim, marginBottom: 4, letterSpacing: ".1em" }}>DATE</div>
                    <input type="date" style={inputStyle} value={newTrade.date} onChange={e => setNewTrade(p => ({ ...p, date: e.target.value }))} />
                  </div>
                  <div>
                    <div style={{ fontSize: 9, color: C.inkDim, marginBottom: 4, letterSpacing: ".1em" }}>TYPE</div>
                    <select style={inputStyle} value={newTrade.type} onChange={e => setNewTrade(p => ({ ...p, type: e.target.value }))}>
                      <option value="stock">Stock</option>
                      <option value="crypto">Crypto</option>
                    </select>
                  </div>
                  <div>
                    <div style={{ fontSize: 9, color: C.inkDim, marginBottom: 4, letterSpacing: ".1em" }}>SYMBOL</div>
                    <input style={inputStyle} placeholder="TRAW" value={newTrade.symbol} onChange={e => setNewTrade(p => ({ ...p, symbol: e.target.value.toUpperCase() }))} />
                  </div>
                  <div>
                    <div style={{ fontSize: 9, color: C.inkDim, marginBottom: 4, letterSpacing: ".1em" }}>PROCEEDS $</div>
                    <input type="number" style={inputStyle} placeholder="500.00" value={newTrade.proceeds} onChange={e => setNewTrade(p => ({ ...p, proceeds: e.target.value }))} />
                  </div>
                  <div>
                    <div style={{ fontSize: 9, color: C.inkDim, marginBottom: 4, letterSpacing: ".1em" }}>COST BASIS $</div>
                    <input type="number" style={inputStyle} placeholder="420.00" value={newTrade.cost} onChange={e => setNewTrade(p => ({ ...p, cost: e.target.value }))} />
                  </div>
                  <div>
                    <div style={{ fontSize: 9, color: C.inkDim, marginBottom: 4, letterSpacing: ".1em" }}>HOLD DAYS</div>
                    <input type="number" style={inputStyle} placeholder="1" value={newTrade.holdDays} onChange={e => setNewTrade(p => ({ ...p, holdDays: e.target.value }))} />
                  </div>
                </div>
                <button onClick={addTrade} style={{ ...btnStyle(C.green), marginTop: 12 }}>+ Add Trade</button>
              </div>

              {/* Trades table */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, overflow: "hidden" }}>
                <div style={{ background: C.ink, padding: "10px 18px", display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 9, color: C.bg, letterSpacing: ".15em" }}>ALL TRADES — {settings.taxYear}</span>
                  <span style={{ fontSize: 9, color: C.inkDim }}>{trades.length} entries</span>
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${C.border}` }}>
                        {["DATE","TYPE","SYMBOL","PROCEEDS","COST","P&L","DAYS","TERM","RATE","TAX OWED","ACTION"].map(h => (
                          <th key={h} style={{ padding: "9px 12px", color: C.inkDim, textAlign: "left", fontSize: 8, letterSpacing: ".12em", fontWeight: 600, whiteSpace: "nowrap" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {tradeCalcs.map((t, i) => (
                        <tr key={t.id} style={{ borderBottom: `1px solid ${C.border}`, background: i % 2 === 0 ? C.card : C.surface }}>
                          <td style={{ padding: "9px 12px", color: C.inkMid }}>{t.date}</td>
                          <td style={{ padding: "9px 12px" }}>
                            <Tag color={t.type === "stock" ? C.blue : C.gold} bg={t.type === "stock" ? C.blueDim : C.goldDim}>{t.type}</Tag>
                          </td>
                          <td style={{ padding: "9px 12px", fontWeight: 700, color: C.ink }}>{t.symbol}</td>
                          <td style={{ padding: "9px 12px", color: C.ink }}>${t.proceeds.toFixed(2)}</td>
                          <td style={{ padding: "9px 12px", color: C.inkMid }}>${t.cost.toFixed(2)}</td>
                          <td style={{ padding: "9px 12px", color: t.pnl >= 0 ? C.green : C.red, fontWeight: 700 }}>{t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}</td>
                          <td style={{ padding: "9px 12px", color: C.inkDim }}>{t.holdDays}d</td>
                          <td style={{ padding: "9px 12px" }}>
                            <Tag color={t.isLong ? C.green : C.red} bg={t.isLong ? C.greenDim : C.redDim}>{t.isLong ? "LONG" : "SHORT"}</Tag>
                          </td>
                          <td style={{ padding: "9px 12px", color: t.isLong ? C.green : C.red }}>{(t.rate * 100).toFixed(0)}%</td>
                          <td style={{ padding: "9px 12px", color: t.taxOwed > 0 ? C.red : C.green, fontWeight: 700 }}>
                            {t.taxOwed > 0 ? `-$${t.taxOwed.toFixed(2)}` : `+$${t.taxSaved.toFixed(2)}`}
                          </td>
                          <td style={{ padding: "9px 12px" }}>
                            <button onClick={() => setTrades(prev => prev.filter(x => x.id !== t.id))}
                              style={{ background: "none", border: `1px solid ${C.border}`, borderRadius: 3, padding: "2px 7px", cursor: "pointer", fontSize: 9, color: C.red, fontFamily: mono }}>
                              remove
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ══ DIVIDENDS TAB ══ */}
          {tab === "dividends" && (
            <div style={{ display: "grid", gap: 16, animation: "fadeIn .3s ease" }}>
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "18px 20px" }}>
                <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 700, marginBottom: 14 }}>Log a Dividend / Distribution</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
                  {[
                    { label: "DATE", key: "date", type: "date", ph: "" },
                    { label: "SYMBOL", key: "symbol", type: "text", ph: "NVDY" },
                    { label: "AMOUNT $", key: "amount", type: "number", ph: "27.08" },
                    { label: "ROC % (from 1099)", key: "rocPct", type: "number", ph: "0" },
                  ].map(f => (
                    <div key={f.key}>
                      <div style={{ fontSize: 9, color: C.inkDim, marginBottom: 4, letterSpacing: ".1em" }}>{f.label}</div>
                      <input type={f.type} style={inputStyle} placeholder={f.ph} value={newDiv[f.key]}
                        onChange={e => setNewDiv(p => ({ ...p, [f.key]: f.key === "symbol" ? e.target.value.toUpperCase() : e.target.value }))} />
                    </div>
                  ))}
                </div>
                <button onClick={addDiv} style={{ ...btnStyle(C.blue), marginTop: 12 }}>+ Add Dividend</button>
              </div>

              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, overflow: "hidden" }}>
                <div style={{ background: C.ink, padding: "10px 18px" }}>
                  <span style={{ fontSize: 9, color: C.bg, letterSpacing: ".15em" }}>YIELDMAX DISTRIBUTIONS — {settings.taxYear}</span>
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${C.border}` }}>
                        {["DATE","SYMBOL","TOTAL DIST","ROC %","ROC AMT","TAXABLE","RATE","TAX OWED","ACTION"].map(h => (
                          <th key={h} style={{ padding: "9px 12px", color: C.inkDim, textAlign: "left", fontSize: 8, letterSpacing: ".12em", fontWeight: 600, whiteSpace: "nowrap" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {divCalcs.map((d, i) => (
                        <tr key={d.id} style={{ borderBottom: `1px solid ${C.border}`, background: i % 2 === 0 ? C.card : C.surface }}>
                          <td style={{ padding: "9px 12px", color: C.inkMid }}>{d.date}</td>
                          <td style={{ padding: "9px 12px", fontWeight: 700, color: C.blue }}>{d.symbol}</td>
                          <td style={{ padding: "9px 12px", color: C.ink }}>${d.amount.toFixed(2)}</td>
                          <td style={{ padding: "9px 12px", color: d.rocPct > 90 ? C.green : C.gold }}>{d.rocPct}%</td>
                          <td style={{ padding: "9px 12px", color: C.green }}>${d.rocAmt.toFixed(2)}</td>
                          <td style={{ padding: "9px 12px", color: d.taxableAmt > 0 ? C.red : C.green }}>${d.taxableAmt.toFixed(2)}</td>
                          <td style={{ padding: "9px 12px", color: C.inkMid }}>{(marginalRate * 100).toFixed(0)}%</td>
                          <td style={{ padding: "9px 12px", color: C.red, fontWeight: 700 }}>-${d.taxOwed.toFixed(2)}</td>
                          <td style={{ padding: "9px 12px" }}>
                            <button onClick={() => setDividends(prev => prev.filter(x => x.id !== d.id))}
                              style={{ background: "none", border: `1px solid ${C.border}`, borderRadius: 3, padding: "2px 7px", cursor: "pointer", fontSize: 9, color: C.red, fontFamily: mono }}>
                              remove
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ══ QUARTERLY TAB ══ */}
          {tab === "quarterly" && (
            <div style={{ display: "grid", gap: 16, animation: "fadeIn .3s ease" }}>
              <div style={{ background: C.redDim, border: `1px solid ${C.red}44`, borderRadius: 8, padding: "16px 20px" }}>
                <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 700, color: C.red, marginBottom: 8 }}>⚠️ Estimated Tax Payments</div>
                <div style={{ fontSize: 12, color: C.inkMid, lineHeight: 1.7 }}>
                  If you expect to owe more than <strong>$1,000</strong> in taxes this year, the IRS requires quarterly estimated payments.
                  Missing these triggers an <strong>underpayment penalty</strong>. Set aside your tax estimate weekly from bot profits.
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
                {quarters.map((q, i) => (
                  <div key={q} style={{
                    background: C.surface, border: `1px solid ${C.border}`,
                    borderRadius: 8, padding: "16px 18px",
                    borderTop: `3px solid ${i < 2 ? C.red : C.gold}`,
                  }}>
                    <div style={{ fontSize: 9, color: C.inkDim, letterSpacing: ".12em", marginBottom: 6 }}>{q}</div>
                    <div style={{ fontFamily: serif, fontSize: 22, fontWeight: 700, color: C.red }}>${qTax[i].toFixed(2)}</div>
                    <div style={{ fontSize: 10, color: C.inkDim, marginTop: 4 }}>Due: <strong style={{ color: C.ink }}>{qDue[i]}</strong></div>
                    <div style={{ fontSize: 10, color: C.inkMid, marginTop: 6 }}>
                      Weekly set-aside: <strong style={{ color: C.ink }}>${(qTax[i] / 13).toFixed(2)}</strong>
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "18px 20px" }}>
                <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 700, marginBottom: 14 }}>Year-End Tax Projection</div>
                {[
                  ["Estimated Annual Trading P&L", `$${(totalPnl * 4).toFixed(2)}`],
                  ["Estimated Annual Dividends", `$${(totalDivIncome * 4).toFixed(2)}`],
                  ["Estimated Total Tax Owed", `$${(totalTax * 4).toFixed(2)}`],
                  ["Weekly Amount to Set Aside", `$${(totalTax * 4 / 52).toFixed(2)}`],
                  ["Effective Tax Rate", `${totalPnl + totalDivIncome > 0 ? ((totalTax / (totalPnl + totalDivIncome)) * 100).toFixed(1) : 0}%`],
                ].map(([k, v], i) => (
                  <div key={i} style={{
                    display: "flex", justifyContent: "space-between",
                    padding: "9px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12,
                  }}>
                    <span style={{ color: C.inkMid }}>{k}</span>
                    <span style={{ color: C.ink, fontWeight: 700 }}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ══ SETTINGS TAB ══ */}
          {tab === "settings" && (
            <div style={{ display: "grid", gap: 16, animation: "fadeIn .3s ease" }}>
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "22px 24px" }}>
                <div style={{ fontFamily: serif, fontSize: 16, fontWeight: 700, marginBottom: 18 }}>Tax Profile Settings</div>
                <div style={{ display: "grid", gap: 18 }}>
                  <div>
                    <div style={{ fontSize: 10, color: C.inkDim, marginBottom: 6, letterSpacing: ".1em" }}>FILING STATUS</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {Object.entries(FILING_LABELS).map(([key, label]) => (
                        <button key={key} onClick={() => setSettings(p => ({ ...p, filing: key }))}
                          style={{
                            background: settings.filing === key ? C.ink : C.surface,
                            color: settings.filing === key ? C.bg : C.inkMid,
                            border: `1px solid ${settings.filing === key ? C.ink : C.border}`,
                            borderRadius: 5, padding: "7px 14px", cursor: "pointer",
                            fontSize: 11, fontFamily: mono,
                          }}>{label}</button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: C.inkDim, marginBottom: 6, letterSpacing: ".1em" }}>INCOME BRACKET (excluding trading income)</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {INCOME_BRACKETS.map((label, i) => (
                        <button key={i} onClick={() => setSettings(p => ({ ...p, incomeBracket: i }))}
                          style={{
                            background: settings.incomeBracket === i ? C.ink : C.surface,
                            color: settings.incomeBracket === i ? C.bg : C.inkMid,
                            border: `1px solid ${settings.incomeBracket === i ? C.ink : C.border}`,
                            borderRadius: 5, padding: "7px 14px", cursor: "pointer",
                            fontSize: 10, fontFamily: mono,
                          }}>{label}</button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: C.inkDim, marginBottom: 6, letterSpacing: ".1em" }}>TAX YEAR</div>
                    <div style={{ display: "flex", gap: 8 }}>
                      {[2024, 2025, 2026].map(yr => (
                        <button key={yr} onClick={() => setSettings(p => ({ ...p, taxYear: yr }))}
                          style={{
                            background: settings.taxYear === yr ? C.ink : C.surface,
                            color: settings.taxYear === yr ? C.bg : C.inkMid,
                            border: `1px solid ${settings.taxYear === yr ? C.ink : C.border}`,
                            borderRadius: 5, padding: "7px 18px", cursor: "pointer",
                            fontSize: 12, fontFamily: mono,
                          }}>{yr}</button>
                      ))}
                    </div>
                  </div>
                </div>
                <div style={{ marginTop: 20, padding: 16, background: C.greenDim, borderRadius: 6, border: `1px solid ${C.green}44`, fontSize: 11, color: C.inkMid, lineHeight: 1.7 }}>
                  <strong style={{ color: C.green }}>Your current rates:</strong><br />
                  Marginal income tax rate: <strong>{(marginalRate * 100).toFixed(0)}%</strong> (short-term gains, dividends, day trades)<br />
                  Long-term capital gains rate: <strong>{(ltcgRate * 100).toFixed(0)}%</strong> (held 1+ year)<br />
                  Standard deduction: <strong>${TAX_CONFIG.standardDeduction[settings.filing].toLocaleString()}</strong><br />
                  <strong style={{ color: C.red }}>Note:</strong> This tool is for planning purposes only. Consult a CPA for official tax advice.
                </div>
              </div>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
