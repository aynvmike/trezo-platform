import { useState, useEffect, useRef } from "react";

// ── TAX ENGINE ────────────────────────────────────────────────────────────────
const TAX_BRACKETS = {
  single: [
    { max: 11600, rate: 0.10 }, { max: 47150, rate: 0.12 },
    { max: 100525, rate: 0.22 }, { max: 191950, rate: 0.24 },
    { max: Infinity, rate: 0.32 },
  ],
};
const LTCG_RATES = { single: [{ max: 47025, rate: 0.00 }, { max: 518900, rate: 0.15 }, { max: Infinity, rate: 0.20 }] };

function getMarginalRate(income, filing = "single") {
  for (const b of TAX_BRACKETS[filing]) if (income <= b.max) return b.rate;
  return 0.37;
}
function getLTCGRate(income, filing = "single") {
  for (const b of LTCG_RATES[filing]) if (income <= b.max) return b.rate;
  return 0.20;
}

// ── THEME ─────────────────────────────────────────────────────────────────────
const T = {
  bg:      "#07080f",
  surface: "#0d0f1a",
  card:    "#111525",
  border:  "#1c2035",
  borderHi:"#2a3060",
  green:   "#00e676",
  greenDim:"#00e67618",
  red:     "#ff1744",
  redDim:  "#ff174418",
  gold:    "#ffd740",
  goldDim: "#ffd74018",
  blue:    "#448aff",
  blueDim: "#448aff18",
  cyan:    "#00e5ff",
  cyanDim: "#00e5ff18",
  purple:  "#e040fb",
  text:    "#e8eaf6",
  muted:   "#42476b",
  mono:    "'Courier New', monospace",
};

// ── CONSTANTS ─────────────────────────────────────────────────────────────────
const BASE_INCOME = 30000;
const FILING = "single";
const STOCK_ACCOUNT = 1500;
const CRYPTO_ACCOUNT = 4636.70;
const STOCK_TICKERS = ["MESO","DRUG","TRAW","SHOT","CYTO","VERB","GHSI","AGRI"];
const CRYPTO_COINS = {
  XRP: { price: 1.45, vol: 0.04, color: T.cyan },
  ETH: { price: 2260, vol: 0.03, color: T.purple },
  SOL: { price: 93.81, vol: 0.05, color: T.gold, locked: true },
};
const CATALYSTS = ["FDA Approval","Earnings Beat","Contract Win","Short Squeeze","Partnership","Phase 3 Trial"];

// ── HELPERS ───────────────────────────────────────────────────────────────────
const ts = () => new Date().toLocaleTimeString("en", { hour12: false });
const fmt$ = (n) => `${n >= 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
const fmtTax = (n) => `-$${Math.abs(n).toFixed(2)}`;
const uid = () => Date.now() + Math.random();

function calcTaxOnTrade(pnl, holdDays, income) {
  if (pnl <= 0) return { taxOwed: 0, rate: 0, saved: Math.abs(pnl) * getMarginalRate(income) };
  const rate = holdDays >= 365 ? getLTCGRate(income) : getMarginalRate(income);
  return { taxOwed: pnl * rate, rate, saved: 0 };
}

// ── ANIMATIONS ────────────────────────────────────────────────────────────────
const CSS = `
@keyframes pulse { 0%,100%{opacity:1}50%{opacity:.3} }
@keyframes fadeUp { from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)} }
@keyframes glow { 0%,100%{box-shadow:0 0 12px #00e67644}50%{box-shadow:0 0 28px #00e67699} }
@keyframes ticker { 0%{opacity:0;transform:translateX(-10px)}100%{opacity:1;transform:translateX(0)} }
@keyframes spin { from{transform:rotate(0deg)}to{transform:rotate(360deg)} }
`;

// ── MINI COMPONENTS ───────────────────────────────────────────────────────────
const Dot = ({ color, pulse }) => (
  <span style={{
    width: 7, height: 7, borderRadius: "50%", display: "inline-block",
    background: color, boxShadow: `0 0 5px ${color}`,
    animation: pulse ? "pulse 1.2s infinite" : "none", flexShrink: 0,
  }} />
);

const Tag = ({ color, children, sm }) => (
  <span style={{
    background: color + "22", color, border: `1px solid ${color}44`,
    borderRadius: 3, padding: sm ? "1px 5px" : "2px 8px",
    fontSize: sm ? 9 : 10, fontFamily: T.mono,
    fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase",
    whiteSpace: "nowrap",
  }}>{children}</span>
);

const MBar = ({ value, max, color, height = 4 }) => (
  <div style={{ background: T.border, borderRadius: 2, height, overflow: "hidden", flex: 1 }}>
    <div style={{
      height: "100%", borderRadius: 2, transition: "width .5s ease",
      width: `${Math.min(100, Math.max(0, (value / max) * 100))}%`,
      background: color,
    }} />
  </div>
);

const SCard = ({ label, value, sub, color = T.text, icon }) => (
  <div style={{
    background: T.card, border: `1px solid ${T.border}`,
    borderRadius: 8, padding: "13px 15px",
    borderTop: `2px solid ${color}`,
  }}>
    <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".15em", marginBottom: 5, fontFamily: T.mono }}>
      {icon} {label}
    </div>
    <div style={{ fontSize: 19, fontWeight: 900, color, fontFamily: T.mono }}>{value}</div>
    {sub && <div style={{ fontSize: 9, color: T.muted, marginTop: 3 }}>{sub}</div>}
  </div>
);

// ── MAIN APP ──────────────────────────────────────────────────────────────────
export default function NovaUnified() {
  // ── STATE ──────────────────────────────────────────────────────────────────
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState("overview");
  const [solUnlocked, setSolUnlocked] = useState(false);
  const [tick, setTick] = useState(0);

  // Bot states
  const [stockActive, setStockActive] = useState(true);
  const [cryptoActive, setCryptoActive] = useState(true);

  // P&L
  const [stockPnl, setStockPnl] = useState(0);
  const [cryptoPnl, setCryptoPnl] = useState(0);
  const [dailyLossStock, setDailyLossStock] = useState(0);
  const [dailyLossCrypto, setDailyLossCrypto] = useState(0);

  // Trades
  const [allTrades, setAllTrades] = useState([]);
  const [activeTrades, setActiveTrades] = useState({});
  const [stats, setStats] = useState({ sw: 0, sl: 0, cw: 0, cl: 0 });

  // Tax engine — live running totals
  const [taxLedger, setTaxLedger] = useState({
    stGains: 0, ltGains: 0, losses: 0,
    taxOwed: 0, taxSaved: 0, netAfterTax: 0,
    weeklySetAside: 0, yearProjection: 0,
    trades: [],
  });

  // Crypto prices
  const [prices, setPrices] = useState({ XRP: 1.45, ETH: 2260, SOL: 93.81 });
  const [priceHistory, setPriceHistory] = useState({ XRP: [1.45], ETH: [2260], SOL: [93.81] });

  // Log
  const [log, setLog] = useState([]);
  const intRef = useRef(null);
  const margRate = getMarginalRate(BASE_INCOME);
  const ltcgRate = getLTCGRate(BASE_INCOME);

  const addLog = (msg, color = T.muted, source = "") =>
    setLog(p => [{
      msg, color, source, time: ts(), id: uid(),
    }, ...p].slice(0, 100));

  // ── TAX UPDATE ─────────────────────────────────────────────────────────────
  function applyTradeToTax(trade) {
    const { pnl, holdDays = 1, symbol, type } = trade;
    const { taxOwed, rate, saved } = calcTaxOnTrade(pnl, holdDays, BASE_INCOME);
    const net = pnl - taxOwed;
    const isLong = holdDays >= 365;

    setTaxLedger(prev => {
      const newST = prev.stGains + (pnl > 0 && !isLong ? pnl : 0);
      const newLT = prev.ltGains + (pnl > 0 && isLong ? pnl : 0);
      const newLoss = prev.losses + (pnl < 0 ? pnl : 0);
      const newOwed = prev.taxOwed + taxOwed;
      const newSaved = prev.taxSaved + saved;
      const totalGains = newST + newLT + newLoss;
      const weekly = newOwed / Math.max(1, Math.ceil(new Date().getDate() / 7)) / 4;
      const yearProj = newOwed * (52 / Math.max(1, new Date().getMonth() + 1));

      return {
        stGains: newST, ltGains: newLT, losses: newLoss,
        taxOwed: newOwed, taxSaved: newSaved,
        netAfterTax: prev.netAfterTax + net,
        weeklySetAside: weekly,
        yearProjection: yearProj,
        trades: [{ ...trade, taxOwed, rate, saved, net, isLong, id: uid() }, ...prev.trades].slice(0, 50),
      };
    });

    return { taxOwed, rate, net };
  }

  // ── BOT LOOP ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!running) return;
    intRef.current = setInterval(() => {
      setTick(t => t + 1);
      const now = new Date();
      const hour = now.getHours();
      const inWindow = hour >= 7 && hour < 11;

      // ── UPDATE CRYPTO PRICES ────────────────────────────────────────────
      setPrices(prev => {
        const next = { ...prev };
        Object.keys(CRYPTO_COINS).forEach(sym => {
          if (sym === "SOL" && !solUnlocked) return;
          const coin = CRYPTO_COINS[sym];
          const drift = (Math.random() - 0.495) * coin.vol;
          next[sym] = +(prev[sym] * (1 + drift)).toFixed(prev[sym] > 100 ? 2 : 4);
        });
        return next;
      });

      setPriceHistory(prev => {
        const next = { ...prev };
        Object.keys(CRYPTO_COINS).forEach(sym => {
          next[sym] = [...(prev[sym] || []), prices[sym]].slice(-20);
        });
        return next;
      });

      // ── STOCK BOT ──────────────────────────────────────────────────────
      if (stockActive && inWindow && dailyLossStock < STOCK_ACCOUNT * 0.10) {
        const found = Math.random() > 0.45;
        if (found && !activeTrades["STOCK"]) {
          const ticker = STOCK_TICKERS[Math.floor(Math.random() * STOCK_TICKERS.length)];
          const price = +(1 + Math.random() * 18).toFixed(2);
          const relVol = +(5 + Math.random() * 30).toFixed(1);
          const score = Math.round(60 + Math.random() * 35);
          const catalyst = CATALYSTS[Math.floor(Math.random() * CATALYSTS.length)];

          if (score >= 65) {
            const risk = STOCK_ACCOUNT * 0.05;
            const stopDist = price * 0.05;
            const shares = Math.max(1, Math.floor(risk / stopDist));
            const stop = +(price * 0.95).toFixed(2);
            const target = +(price * 1.10).toFixed(2);
            // Indicator snapshot at entry
            const rsiVal = +(42 + Math.random() * 22).toFixed(1);
            const macdBull = Math.random() > 0.35;
            const aboveVwap = Math.random() > 0.25;
            const aboveSenkou = Math.random() > 0.3;
            const volOk = Math.random() > 0.3;
            const floatM = +(1.5 + Math.random() * 17).toFixed(1);
            const changeP = +(10 + Math.random() * 80).toFixed(1);
            const setup = Math.random() > 0.5 ? "Bull Flag" : "Flat Top Breakout";
            const indicators = { rsiVal, macdBull, aboveVwap, aboveSenkou, volOk, relVol, floatM, changeP, setup };
            const trade = { id: uid(), ticker, price, shares, stop, target, risk: +(risk).toFixed(2), score, catalyst, type: "stock", time: ts(), indicators };

            setActiveTrades(p => ({ ...p, STOCK: trade }));
            addLog(`⚡ STOCK: ${ticker} @ $${price} | Score ${score}% | ${catalyst}`, T.green, "STOCK");

            setTimeout(() => {
              const win = Math.random() < 0.65;
              const exit = win ? +(price * (1.05 + Math.random() * 0.06)).toFixed(2) : +(price * (0.93 + Math.random() * 0.03)).toFixed(2);
              const pnl = +((exit - price) * shares).toFixed(2);
              const { taxOwed, rate, net } = applyTradeToTax({ pnl, holdDays: 1, symbol: ticker, type: "stock" });

              const closed = { ...trade, exit, pnl, taxOwed, rate, net, status: win ? "WIN" : "LOSS", closedAt: ts() };
              setAllTrades(p => [closed, ...p].slice(0, 60));
              setActiveTrades(p => { const n = { ...p }; delete n.STOCK; return n; });
              setStockPnl(p => +(p + pnl).toFixed(2));
              setStats(p => ({ ...p, sw: p.sw + (win ? 1 : 0), sl: p.sl + (win ? 0 : 1) }));
              if (!win) setDailyLossStock(d => +(d + Math.abs(pnl)).toFixed(2));

              addLog(
                win
                  ? `💰 STOCK WIN: ${ticker} | P&L ${fmt$(pnl)} | Tax ${fmtTax(taxOwed)} | Net ${fmt$(net)}`
                  : `❌ STOCK LOSS: ${ticker} | P&L ${fmt$(pnl)} | Tax offset +$${(Math.abs(pnl) * margRate).toFixed(2)}`,
                win ? T.green : T.red, "STOCK"
              );
            }, 3000 + Math.random() * 5000);
          }
        }
      } else if (stockActive && !inWindow && hour >= 11) {
        setStockActive(false);
        addLog(`⏹ STOCK BOT: Trading window closed (11AM) — session complete`, T.gold, "STOCK");
      }

      // ── CRYPTO BOT ─────────────────────────────────────────────────────
      if (cryptoActive && dailyLossCrypto < CRYPTO_ACCOUNT * 0.10) {
        const tradableCoins = Object.keys(CRYPTO_COINS).filter(sym =>
          sym !== "SOL" || solUnlocked
        );

        tradableCoins.forEach(sym => {
          if (activeTrades[sym]) return;
          const coin = CRYPTO_COINS[sym];
          const price = prices[sym];
          const hist = priceHistory[sym] || [price];
          const last = hist[hist.length - 1] || price;
          const rsi = 40 + Math.random() * 30;
          const macdBull = Math.random() > 0.45;

          const shouldEnter = macdBull && rsi > 42 && rsi < 68 && Math.random() > 0.55;
          if (!shouldEnter) return;

          const risk = CRYPTO_ACCOUNT * 0.05;
          const stopDist = price * 0.05;
          const qty = +(risk / stopDist).toFixed(4);
          const stop = +(price * 0.95).toFixed(4);
          const target = +(price * 1.10).toFixed(4);
          const mode = rsi < 40 ? "DCA" : rsi > 65 ? "SCALP" : "SWING";
          const trendStr = +(40 + Math.random() * 55).toFixed(1);
          const bbPos = +(30 + Math.random() * 50).toFixed(1);
          const volPct = +(50 + Math.random() * 50).toFixed(1);
          const indicators = { rsi: +rsi.toFixed(1), macdBull, trendStr, bbPos, volPct, mode };
          const trade = { id: uid(), ticker: sym, price, qty, stop, target, mode, type: "crypto", time: ts(), indicators };
          setActiveTrades(p => ({ ...p, [sym]: trade }));
          addLog(`⚡ CRYPTO ${mode}: ${sym} @ $${price} | Qty ${qty}`, coin.color, "CRYPTO");

          setTimeout(() => {
            const win = Math.random() < 0.62;
            const exit = win ? +(price * (1.05 + Math.random() * 0.07)).toFixed(4) : +(price * (0.93 + Math.random() * 0.04)).toFixed(4);
            const pnl = +((exit - price) * qty).toFixed(2);
            const holdDays = mode === "SWING" ? Math.floor(1 + Math.random() * 30) : 1;
            const { taxOwed, rate, net } = applyTradeToTax({ pnl, holdDays, symbol: sym, type: "crypto" });

            const closed = { ...trade, exit, pnl, taxOwed, rate, net, holdDays, status: win ? "WIN" : "LOSS", closedAt: ts() };
            setAllTrades(p => [closed, ...p].slice(0, 60));
            setActiveTrades(p => { const n = { ...p }; delete n[sym]; return n; });
            setCryptoPnl(p => +(p + pnl).toFixed(2));
            setStats(p => ({ ...p, cw: p.cw + (win ? 1 : 0), cl: p.cl + (win ? 0 : 1) }));
            if (!win) setDailyLossCrypto(d => +(d + Math.abs(pnl)).toFixed(2));

            addLog(
              win
                ? `💰 CRYPTO WIN: ${sym} | P&L ${fmt$(pnl)} | Tax ${fmtTax(taxOwed)} (${(rate * 100).toFixed(0)}%) | Net ${fmt$(net)}`
                : `❌ CRYPTO LOSS: ${sym} | P&L ${fmt$(pnl)} | Offset +$${(Math.abs(pnl) * margRate).toFixed(2)}`,
              win ? T.green : T.red, "CRYPTO"
            );
          }, 2000 + Math.random() * 8000);
        });
      }

    }, 4000 + Math.random() * 2000);

    return () => clearInterval(intRef.current);
  }, [running, prices, priceHistory, activeTrades, dailyLossStock, dailyLossCrypto, solUnlocked, stockActive, cryptoActive]);

  // ── COMPUTED ──────────────────────────────────────────────────────────────
  const totalPnl = stockPnl + cryptoPnl;
  const totalTrades = stats.sw + stats.sl + stats.cw + stats.cl;
  const stockWR = stats.sw + stats.sl > 0 ? ((stats.sw / (stats.sw + stats.sl)) * 100).toFixed(0) : "—";
  const cryptoWR = stats.cw + stats.cl > 0 ? ((stats.cw / (stats.cw + stats.cl)) * 100).toFixed(0) : "—";
  const TABS = ["overview", "trades", "tax ledger", "log"];

  const startBot = () => {
    setRunning(true);
    setStockActive(true);
    setCryptoActive(true);
    setStockPnl(0); setCryptoPnl(0);
    setDailyLossStock(0); setDailyLossCrypto(0);
    setAllTrades([]); setActiveTrades({});
    setStats({ sw: 0, sl: 0, cw: 0, cl: 0 });
    setTaxLedger({ stGains: 0, ltGains: 0, losses: 0, taxOwed: 0, taxSaved: 0, netAfterTax: 0, weeklySetAside: 0, yearProjection: 0, trades: [] });
    setLog([]);
    addLog("🚀 NOVA UNIFIED BOT — All systems activated", T.green, "SYSTEM");
    addLog(`📊 Tax Engine: ${(margRate * 100).toFixed(0)}% marginal | ${(ltcgRate * 100).toFixed(0)}% LTCG | Filing: Single`, T.blue, "TAX");
    addLog("📈 Stock Bot: Scanning for A-grade setups (7AM–11AM window)", T.green, "STOCK");
    addLog("🪙 Crypto Bot: XRP + ETH active 24/7 | SOL unlocks in ~4 days", T.cyan, "CRYPTO");
  };

  return (
    <>
      <style>{CSS}</style>
      <div style={{ background: T.bg, minHeight: "100vh", color: T.text, fontFamily: T.mono, paddingBottom: 60,
        backgroundImage: `radial-gradient(ellipse 70% 40% at 5% 0%, #091830 0%, transparent 60%),radial-gradient(ellipse 50% 30% at 95% 100%, #130930 0%, transparent 60%)`,
      }}>

        {/* ── HEADER ── */}
        <div style={{
          background: T.surface, borderBottom: `1px solid ${T.border}`,
          padding: "14px 22px",
          display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10, fontSize: 20,
              background: `linear-gradient(135deg, ${T.green}33, ${T.cyan}33)`,
              border: `1px solid ${T.green}55`,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>⚡</div>
            <div>
              <div style={{ fontSize: 9, color: T.green, letterSpacing: ".22em", marginBottom: 1 }}>NOVA BOT FAMILY</div>
              <div style={{ fontSize: 16, fontWeight: 800 }}>UNIFIED TRADING + TAX ENGINE</div>
              <div style={{ fontSize: 9, color: T.muted, marginTop: 1 }}>
                Stock Bot (7–11AM) + Crypto Bot (24/7) + Live Tax Tracking
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {!solUnlocked && (
              <button onClick={() => { setSolUnlocked(true); addLog("🔓 SOL delegation unlocked — SOL added to crypto bot", T.gold, "CRYPTO"); }}
                style={{ background: T.goldDim, border: `1px solid ${T.gold}66`, color: T.gold, borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontSize: 10, fontFamily: T.mono, fontWeight: 700 }}>
                UNLOCK SOL ⏳
              </button>
            )}
            <button onClick={() => { if (running) { setRunning(false); addLog("⏹ Bot stopped", T.red, "SYSTEM"); } else startBot(); }}
              style={{
                background: running ? T.redDim : T.greenDim,
                border: `1px solid ${running ? T.red : T.green}`,
                color: running ? T.red : T.green,
                borderRadius: 6, padding: "9px 22px", cursor: "pointer",
                fontSize: 12, fontFamily: T.mono, fontWeight: 800, letterSpacing: ".07em",
                animation: running ? "glow 2s infinite" : "none",
              }}>{running ? "■ STOP" : "▶ START ALL"}</button>
          </div>
        </div>

        {/* ── TABS ── */}
        <div style={{
          background: T.surface, borderBottom: `1px solid ${T.border}`,
          padding: "0 22px", display: "flex", gap: 0, overflowX: "auto",
        }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: "none", border: "none",
              borderBottom: tab === t ? `2px solid ${T.cyan}` : "2px solid transparent",
              color: tab === t ? T.cyan : T.muted,
              padding: "11px 18px", cursor: "pointer", fontSize: 11,
              fontFamily: T.mono, fontWeight: tab === t ? 700 : 400,
              letterSpacing: ".08em", textTransform: "uppercase", whiteSpace: "nowrap",
            }}>{t}</button>
          ))}
        </div>

        <div style={{ maxWidth: 1080, margin: "0 auto", padding: "18px 18px", display: "grid", gap: 14 }}>

          {/* ══ OVERVIEW ══ */}
          {tab === "overview" && (
            <div style={{ display: "grid", gap: 14, animation: "fadeUp .3s ease" }}>

              {/* Master stats */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
                <SCard label="TOTAL P&L" value={fmt$(totalPnl)} color={totalPnl >= 0 ? T.green : T.red} sub="Both bots" icon="📊" />
                <SCard label="NET AFTER TAX" value={fmt$(taxLedger.netAfterTax)} color={taxLedger.netAfterTax >= 0 ? T.green : T.red} sub="What you keep" icon="💵" />
                <SCard label="TAX OWED YTD" value={`$${taxLedger.taxOwed.toFixed(2)}`} color={T.red} sub="Set this aside" icon="🏛" />
                <SCard label="WEEKLY SET-ASIDE" value={`$${taxLedger.weeklySetAside.toFixed(2)}`} color={T.gold} sub="Per week for taxes" icon="📅" />
                <SCard label="STOCK WIN RATE" value={`${stockWR}%`} color={Number(stockWR) >= 60 ? T.green : T.gold} sub={`${stats.sw}W / ${stats.sl}L`} icon="📈" />
                <SCard label="CRYPTO WIN RATE" value={`${cryptoWR}%`} color={Number(cryptoWR) >= 60 ? T.green : T.gold} sub={`${stats.cw}W / ${stats.cl}L`} icon="🪙" />
              </div>

              {/* Two bot panels side by side */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>

                {/* Stock Bot */}
                <div style={{ background: T.card, border: `1px solid ${T.green}44`, borderRadius: 10 }}>
                  <div style={{ background: T.green + "14", borderBottom: `1px solid ${T.green}33`, padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Dot color={running && stockActive ? T.green : T.muted} pulse={running && stockActive} />
                      <span style={{ color: T.green, fontWeight: 800, fontSize: 13 }}>STOCK BOT</span>
                    </div>
                    <Tag color={running && stockActive ? T.green : T.muted} sm>{running && stockActive ? "ACTIVE" : "PAUSED"}</Tag>
                  </div>
                  <div style={{ padding: "12px 14px", display: "grid", gap: 8 }}>
                    {[
                      ["Platform", "Webull", T.blue],
                      ["Window", "7:00–11:00 AM", T.text],
                      ["Strategy", "Small Trades Momentum", T.green],
                      ["P&L Today", fmt$(stockPnl), stockPnl >= 0 ? T.green : T.red],
                      ["Daily Loss", `$${dailyLossStock.toFixed(2)} / $${(STOCK_ACCOUNT * 0.10).toFixed(0)}`, T.gold],
                      ["Active Trade", activeTrades["STOCK"] ? `$${activeTrades["STOCK"].ticker}` : "None", T.text],
                    ].map(([k, v, c]) => (
                      <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, padding: "4px 0", borderBottom: `1px solid ${T.border}44` }}>
                        <span style={{ color: T.muted }}>{k}</span>
                        <span style={{ color: c, fontWeight: 600 }}>{v}</span>
                      </div>
                    ))}
                    <div style={{ marginTop: 4 }}>
                      <div style={{ fontSize: 8, color: T.muted, marginBottom: 4 }}>DAILY LOSS METER</div>
                      <MBar value={dailyLossStock} max={STOCK_ACCOUNT * 0.10} color={dailyLossStock < STOCK_ACCOUNT * 0.05 ? T.green : T.red} />
                    </div>
                  </div>
                </div>

                {/* Crypto Bot */}
                <div style={{ background: T.card, border: `1px solid ${T.cyan}44`, borderRadius: 10 }}>
                  <div style={{ background: T.cyan + "14", borderBottom: `1px solid ${T.cyan}33`, padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Dot color={running && cryptoActive ? T.cyan : T.muted} pulse={running && cryptoActive} />
                      <span style={{ color: T.cyan, fontWeight: 800, fontSize: 13 }}>CRYPTO BOT</span>
                    </div>
                    <Tag color={T.cyan} sm>24/7</Tag>
                  </div>
                  <div style={{ padding: "12px 14px", display: "grid", gap: 8 }}>
                    {[
                      ["Platform", "Coinbase", T.blue],
                      ["Coins", solUnlocked ? "XRP + ETH + SOL" : "XRP + ETH", T.cyan],
                      ["P&L Session", fmt$(cryptoPnl), cryptoPnl >= 0 ? T.green : T.red],
                      ["Daily Loss", `$${dailyLossCrypto.toFixed(2)} / $${(CRYPTO_ACCOUNT * 0.10).toFixed(0)}`, T.gold],
                      ["XRP Price", `$${prices.XRP}`, T.cyan],
                      ["ETH Price", `$${prices.ETH}`, T.purple],
                      ["SOL Price", solUnlocked ? `$${prices.SOL}` : "Locked ⏳", T.gold],
                    ].map(([k, v, c]) => (
                      <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, padding: "4px 0", borderBottom: `1px solid ${T.border}44` }}>
                        <span style={{ color: T.muted }}>{k}</span>
                        <span style={{ color: c, fontWeight: 600 }}>{v}</span>
                      </div>
                    ))}
                    <div style={{ marginTop: 4 }}>
                      <div style={{ fontSize: 8, color: T.muted, marginBottom: 4 }}>DAILY LOSS METER</div>
                      <MBar value={dailyLossCrypto} max={CRYPTO_ACCOUNT * 0.10} color={dailyLossCrypto < CRYPTO_ACCOUNT * 0.05 ? T.green : T.red} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Live Tax Snapshot */}
              <div style={{ background: T.card, border: `1px solid ${T.red}44`, borderRadius: 10, padding: "16px 18px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                  <div style={{ fontSize: 10, color: T.red, letterSpacing: ".15em" }}>🏛 LIVE TAX SNAPSHOT — {new Date().getFullYear()}</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <Tag color={T.blue} sm>Single</Tag>
                    <Tag color={T.gold} sm>{(margRate * 100).toFixed(0)}% Marginal</Tag>
                    <Tag color={T.green} sm>{(ltcgRate * 100).toFixed(0)}% LTCG</Tag>
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                  {[
                    { label: "ST Gains", value: `$${taxLedger.stGains.toFixed(2)}`, note: `${(margRate * 100).toFixed(0)}% rate`, color: T.gold },
                    { label: "LT Gains", value: `$${taxLedger.ltGains.toFixed(2)}`, note: `${(ltcgRate * 100).toFixed(0)}% rate`, color: T.green },
                    { label: "Losses (Offset)", value: `$${Math.abs(taxLedger.losses).toFixed(2)}`, note: "Reduces tax owed", color: T.green },
                    { label: "Tax Owed YTD", value: `$${taxLedger.taxOwed.toFixed(2)}`, note: "Set aside now", color: T.red },
                    { label: "Tax Saved (Losses)", value: `$${taxLedger.taxSaved.toFixed(2)}`, note: "Loss offset value", color: T.green },
                    { label: "Year Projection", value: `$${taxLedger.yearProjection.toFixed(2)}`, note: "Est. full year", color: T.gold },
                  ].map(s => (
                    <div key={s.label} style={{
                      background: T.surface, borderRadius: 6, padding: "10px 12px",
                      borderLeft: `2px solid ${s.color}`,
                    }}>
                      <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".12em", marginBottom: 4 }}>{s.label}</div>
                      <div style={{ fontSize: 16, fontWeight: 800, color: s.color }}>{s.value}</div>
                      <div style={{ fontSize: 9, color: T.muted, marginTop: 2 }}>{s.note}</div>
                    </div>
                  ))}
                </div>

                {/* Weekly set-aside bar */}
                <div style={{ marginTop: 14, background: T.red + "12", border: `1px solid ${T.red}33`, borderRadius: 6, padding: "10px 14px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <span style={{ fontSize: 10, color: T.red }}>📅 SET ASIDE THIS WEEK FOR TAXES</span>
                    <span style={{ fontSize: 16, fontWeight: 900, color: T.red }}>${taxLedger.weeklySetAside.toFixed(2)}</span>
                  </div>
                  <div style={{ fontSize: 10, color: T.muted }}>
                    Every week both bots run, transfer this amount to a separate savings account. Do this consistently and April will never surprise you.
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ══ TRADES ══ */}
          {tab === "trades" && (
            <div style={{ display: "grid", gap: 14, animation: "fadeUp .3s ease" }}>

              {/* Summary bar */}
              <div style={{
                background: T.card, border: `1px solid ${T.border}`,
                borderRadius: 10, padding: "12px 18px",
                display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center",
              }}>
                {[
                  { label: "TOTAL TRADES", value: allTrades.length, color: T.text },
                  { label: "WINS", value: allTrades.filter(t => t.status === "WIN").length, color: T.green },
                  { label: "LOSSES", value: allTrades.filter(t => t.status === "LOSS").length, color: T.red },
                  { label: "GROSS P&L", value: fmt$(allTrades.reduce((s, t) => s + t.pnl, 0)), color: allTrades.reduce((s, t) => s + t.pnl, 0) >= 0 ? T.green : T.red },
                  { label: "TAX OWED", value: `-$${allTrades.reduce((s, t) => s + (t.taxOwed || 0), 0).toFixed(2)}`, color: T.red },
                  { label: "NET KEEP", value: fmt$(allTrades.reduce((s, t) => s + (t.net || t.pnl), 0)), color: T.cyan },
                  { label: "STOCK TRADES", value: allTrades.filter(t => t.type === "stock").length, color: T.green },
                  { label: "CRYPTO TRADES", value: allTrades.filter(t => t.type === "crypto").length, color: T.cyan },
                ].map(s => (
                  <div key={s.label}>
                    <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".12em", marginBottom: 2 }}>{s.label}</div>
                    <div style={{ fontSize: 15, fontWeight: 900, color: s.color }}>{s.value}</div>
                  </div>
                ))}
              </div>

              {/* Trade cards */}
              {allTrades.length === 0
                ? (
                  <div style={{ padding: 40, textAlign: "center", color: T.muted, fontSize: 11,
                    background: T.card, border: `1px solid ${T.border}`, borderRadius: 10 }}>
                    No closed trades yet — start the bot to see detailed trade cards
                  </div>
                )
                : (
                  <div style={{ display: "grid", gap: 12 }}>
                    {allTrades.map((t, i) => {
                      const isStock = t.type === "stock";
                      const botColor = isStock ? T.green : T.cyan;
                      const ind = t.indicators || {};
                      const modeColors = { SCALP: T.cyan, SWING: T.purple, DCA: T.gold };
                      const modeColor = modeColors[t.mode || "SCALP"] || T.cyan;
                      const pnlPct = t.price > 0 ? ((t.exit - t.price) / t.price * 100).toFixed(2) : 0;

                      return (
                        <div key={t.id} style={{
                          background: T.card,
                          border: `1px solid ${t.status === "WIN" ? T.green + "44" : T.red + "33"}`,
                          borderLeft: `3px solid ${t.status === "WIN" ? T.green : T.red}`,
                          borderRadius: 10, overflow: "hidden",
                          animation: i === 0 ? "ticker .4s ease" : "none",
                        }}>

                          {/* Card Header */}
                          <div style={{
                            background: T.surface, padding: "10px 16px",
                            display: "flex", justifyContent: "space-between", alignItems: "center",
                            flexWrap: "wrap", gap: 8,
                            borderBottom: `1px solid ${T.border}`,
                          }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                              <span style={{ fontSize: 18, fontWeight: 900, color: botColor }}>{t.ticker}</span>
                              <Tag color={botColor} sm>{t.type}</Tag>
                              {isStock
                                ? <Tag color={T.gold} sm>{ind.setup || "Momentum"}</Tag>
                                : <Tag color={modeColor} sm>{t.mode || "SCALP"}</Tag>
                              }
                              <Tag color={t.isLong ? T.green : T.gold} sm>{t.isLong ? "LONG-TERM" : "SHORT-TERM"}</Tag>
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                              <div style={{ textAlign: "right" }}>
                                <div style={{ fontSize: 9, color: T.muted, marginBottom: 1 }}>{t.closedAt}</div>
                                <Tag color={t.status === "WIN" ? T.green : T.red}>{t.status}</Tag>
                              </div>
                            </div>
                          </div>

                          <div style={{ padding: "12px 16px", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>

                            {/* Column 1 — Entry Details */}
                            <div>
                              <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".14em", marginBottom: 8 }}>TRADE DETAILS</div>
                              {[
                                ["Entry", `$${t.price}`, T.text],
                                ["Exit", `$${t.exit}`, t.pnl >= 0 ? T.green : T.red],
                                ["Move", `${pnlPct >= 0 ? "+" : ""}${pnlPct}%`, t.pnl >= 0 ? T.green : T.red],
                                isStock
                                  ? ["Shares", t.shares, T.text]
                                  : ["Qty", t.qty, T.text],
                                ["Stop", `$${t.stop}`, T.red],
                                ["Target", `$${t.target}`, T.green],
                                ["Risk", `$${t.risk?.toFixed(2) || "—"}`, T.gold],
                              ].map(([k, v, c]) => (
                                <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 10, padding: "3px 0", borderBottom: `1px solid ${T.border}44` }}>
                                  <span style={{ color: T.muted }}>{k}</span>
                                  <span style={{ color: c, fontWeight: 600 }}>{v}</span>
                                </div>
                              ))}
                            </div>

                            {/* Column 2 — Indicators */}
                            <div>
                              <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".14em", marginBottom: 8 }}>
                                {isStock ? "SIGNAL SNAPSHOT" : "INDICATOR SNAPSHOT"}
                              </div>
                              {isStock ? (
                                <div style={{ display: "grid", gap: 6 }}>
                                  {/* Score bar */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginBottom: 3 }}>
                                      <span style={{ color: T.muted }}>Entry Score</span>
                                      <span style={{ color: t.score >= 80 ? T.green : T.gold, fontWeight: 700 }}>{t.score}%</span>
                                    </div>
                                    <MBar value={t.score} max={100} color={t.score >= 80 ? T.green : T.gold} height={5} />
                                  </div>
                                  {/* Rel Volume */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginBottom: 3 }}>
                                      <span style={{ color: T.muted }}>Rel Volume</span>
                                      <span style={{ color: T.blue }}>{ind.relVol}x</span>
                                    </div>
                                    <MBar value={Math.min(ind.relVol * 2, 100)} max={100} color={T.blue} height={5} />
                                  </div>
                                  {/* Change % */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginBottom: 3 }}>
                                      <span style={{ color: T.muted }}>% Change</span>
                                      <span style={{ color: T.green }}>+{ind.changeP}%</span>
                                    </div>
                                    <MBar value={Math.min(ind.changeP, 100)} max={100} color={T.green} height={5} />
                                  </div>
                                  {/* Indicator checks */}
                                  <div style={{ marginTop: 4, display: "grid", gap: 3 }}>
                                    {[
                                      ["VWAP", ind.aboveVwap],
                                      ["MACD Bull", ind.macdBull],
                                      ["EMA 200", true],
                                      ["Senkou B", ind.aboveSenkou],
                                      ["Volume OK", ind.volOk],
                                    ].map(([label, ok]) => (
                                      <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 9 }}>
                                        <span style={{ color: T.muted }}>{label}</span>
                                        <span style={{ color: ok ? T.green : T.red }}>{ok ? "✓" : "✗"}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ) : (
                                <div style={{ display: "grid", gap: 6 }}>
                                  {/* RSI */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginBottom: 3 }}>
                                      <span style={{ color: T.muted }}>RSI</span>
                                      <span style={{ color: (ind.rsi > 70 || ind.rsi < 30) ? T.gold : T.cyan }}>{ind.rsi}</span>
                                    </div>
                                    <MBar value={ind.rsi || 50} max={100} color={(ind.rsi > 70 || ind.rsi < 30) ? T.gold : T.cyan} height={5} />
                                  </div>
                                  {/* Trend Strength */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginBottom: 3 }}>
                                      <span style={{ color: T.muted }}>Trend</span>
                                      <span style={{ color: T.purple }}>{ind.trendStr}%</span>
                                    </div>
                                    <MBar value={ind.trendStr || 50} max={100} color={T.purple} height={5} />
                                  </div>
                                  {/* BB Position */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginBottom: 3 }}>
                                      <span style={{ color: T.muted }}>BB Position</span>
                                      <span style={{ color: T.gold }}>{ind.bbPos}%</span>
                                    </div>
                                    <MBar value={ind.bbPos || 50} max={100} color={T.gold} height={5} />
                                  </div>
                                  {/* Volume */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginBottom: 3 }}>
                                      <span style={{ color: T.muted }}>Volume</span>
                                      <span style={{ color: T.green }}>{ind.volPct}%</span>
                                    </div>
                                    <MBar value={ind.volPct || 50} max={100} color={T.green} height={5} />
                                  </div>
                                  {/* MACD */}
                                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, marginTop: 4 }}>
                                    <span style={{ color: T.muted }}>MACD</span>
                                    <span style={{ color: ind.macdBull ? T.green : T.red }}>{ind.macdBull ? "▲ Bullish" : "▼ Bearish"}</span>
                                  </div>
                                </div>
                              )}
                            </div>

                            {/* Column 3 — Tax Breakdown */}
                            <div>
                              <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".14em", marginBottom: 8 }}>TAX BREAKDOWN</div>
                              <div style={{ display: "grid", gap: 4 }}>
                                {[
                                  ["Gross P&L", fmt$(t.pnl), t.pnl >= 0 ? T.green : T.red],
                                  ["Tax Rate", `${((t.rate || 0) * 100).toFixed(0)}%`, T.gold],
                                  ["Tax Owed", t.taxOwed > 0 ? fmtTax(t.taxOwed) : "$0.00", T.red],
                                  ["Net Keep", fmt$(t.net || t.pnl), (t.net || t.pnl) >= 0 ? T.green : T.red],
                                ].map(([k, v, c]) => (
                                  <div key={k} style={{
                                    display: "flex", justifyContent: "space-between",
                                    fontSize: 11, padding: "5px 0",
                                    borderBottom: `1px solid ${T.border}44`,
                                  }}>
                                    <span style={{ color: T.muted }}>{k}</span>
                                    <span style={{ color: c, fontWeight: 700 }}>{v}</span>
                                  </div>
                                ))}

                                {/* Net keep visual */}
                                <div style={{
                                  marginTop: 8,
                                  background: (t.net || t.pnl) >= 0 ? T.greenDim : T.redDim,
                                  border: `1px solid ${(t.net || t.pnl) >= 0 ? T.green : T.red}33`,
                                  borderRadius: 5, padding: "8px 10px",
                                  textAlign: "center",
                                }}>
                                  <div style={{ fontSize: 8, color: T.muted, marginBottom: 2 }}>YOU KEEP</div>
                                  <div style={{ fontSize: 18, fontWeight: 900, color: (t.net || t.pnl) >= 0 ? T.green : T.red }}>
                                    {fmt$(t.net || t.pnl)}
                                  </div>
                                </div>

                                {/* Catalyst / mode tag */}
                                {isStock && t.catalyst && (
                                  <div style={{ marginTop: 6, fontSize: 9, color: T.muted }}>
                                    📰 <span style={{ color: T.gold }}>{t.catalyst}</span>
                                  </div>
                                )}
                                {!isStock && (
                                  <div style={{ marginTop: 6 }}>
                                    <div style={{ fontSize: 9, color: T.muted, marginBottom: 3 }}>Hold: {t.holdDays || 1}d · Mode: <span style={{ color: modeColor }}>{t.mode}</span></div>
                                    <div style={{ fontSize: 9, color: T.muted }}>Float: {ind.floatM || "—"}M · Coin: {t.ticker}</div>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )
              }
            </div>
          )}

          {/* ══ TAX LEDGER ══ */}
          {tab === "tax ledger" && (
            <div style={{ display: "grid", gap: 14, animation: "fadeUp .3s ease" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
                {[
                  { label: "SHORT-TERM GAINS", value: `$${taxLedger.stGains.toFixed(2)}`, note: `Taxed at ${(margRate * 100).toFixed(0)}% (ordinary income)`, color: T.gold },
                  { label: "LONG-TERM GAINS", value: `$${taxLedger.ltGains.toFixed(2)}`, note: `Taxed at ${(ltcgRate * 100).toFixed(0)}% (preferred rate)`, color: T.green },
                  { label: "CAPITAL LOSSES", value: `-$${Math.abs(taxLedger.losses).toFixed(2)}`, note: "Offsets gains dollar for dollar", color: T.green },
                  { label: "TOTAL TAX OWED", value: `$${taxLedger.taxOwed.toFixed(2)}`, note: "Transfer to savings NOW", color: T.red },
                  { label: "NET AFTER TAX", value: fmt$(taxLedger.netAfterTax), note: "This is your real profit", color: taxLedger.netAfterTax >= 0 ? T.green : T.red },
                  { label: "YEAR PROJECTION", value: `$${taxLedger.yearProjection.toFixed(2)}`, note: "Estimated full year tax bill", color: T.purple },
                ].map(s => (
                  <div key={s.label} style={{
                    background: T.card, border: `1px solid ${s.color}44`,
                    borderRadius: 8, padding: "14px 16px",
                    borderLeft: `3px solid ${s.color}`,
                  }}>
                    <div style={{ fontSize: 8, color: T.muted, letterSpacing: ".14em", marginBottom: 5 }}>{s.label}</div>
                    <div style={{ fontSize: 22, fontWeight: 900, color: s.color }}>{s.value}</div>
                    <div style={{ fontSize: 9, color: T.muted, marginTop: 4 }}>{s.note}</div>
                  </div>
                ))}
              </div>

              {/* Tax rules reminder */}
              <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 10, padding: "16px 18px" }}>
                <div style={{ fontSize: 10, color: T.cyan, letterSpacing: ".15em", marginBottom: 12 }}>KEY TAX RULES — YOUR SITUATION</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
                  {[
                    { rule: "Day Trades (stocks)", rate: `${(margRate * 100).toFixed(0)}%`, detail: "Short-term ordinary income — every trade logged", color: T.red },
                    { rule: "Crypto Trades", rate: `${(margRate * 100).toFixed(0)}%`, detail: "Property — every swap is a taxable event", color: T.gold },
                    { rule: "Hold >1 Year", rate: `${(ltcgRate * 100).toFixed(0)}%`, detail: "Long-term preferred rate — hold SOL for this", color: T.green },
                    { rule: "YieldMax ROC", rate: "0% now", detail: "Deferred until you sell — reduces cost basis", color: T.blue },
                    { rule: "Loss Harvesting", rate: "Saves you $", detail: "Losses offset gains dollar for dollar", color: T.green },
                    { rule: "Wash Sale", rate: "30-day rule", detail: "Cannot repurchase same asset within 30 days", color: T.red },
                  ].map(r => (
                    <div key={r.rule} style={{
                      background: T.surface, borderRadius: 6, padding: "10px 12px",
                      borderLeft: `2px solid ${r.color}`,
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <span style={{ fontSize: 11, color: T.text, fontWeight: 600 }}>{r.rule}</span>
                        <Tag color={r.color} sm>{r.rate}</Tag>
                      </div>
                      <div style={{ fontSize: 10, color: T.muted }}>{r.detail}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Per-trade tax history */}
              {taxLedger.trades.length > 0 && (
                <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden" }}>
                  <div style={{ background: T.surface, borderBottom: `1px solid ${T.border}`, padding: "9px 16px" }}>
                    <span style={{ fontSize: 9, color: T.muted, letterSpacing: ".15em" }}>TAX LEDGER — EVERY TRADE</span>
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                          {["SYMBOL","TYPE","P&L","HOLD","TERM","RATE","TAX OWED","NET KEEP"].map(h => (
                            <th key={h} style={{ padding: "8px 12px", color: T.muted, textAlign: "left", fontSize: 8, letterSpacing: ".1em" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {taxLedger.trades.map((t, i) => (
                          <tr key={t.id} style={{ borderBottom: `1px solid ${T.border}44`, background: i % 2 === 0 ? T.surface + "44" : "transparent" }}>
                            <td style={{ padding: "8px 12px", fontWeight: 700, color: T.text }}>{t.symbol}</td>
                            <td style={{ padding: "8px 12px" }}><Tag color={t.type === "stock" ? T.green : T.cyan} sm>{t.type}</Tag></td>
                            <td style={{ padding: "8px 12px", color: t.pnl >= 0 ? T.green : T.red, fontWeight: 700 }}>{fmt$(t.pnl)}</td>
                            <td style={{ padding: "8px 12px", color: T.muted }}>{t.holdDays}d</td>
                            <td style={{ padding: "8px 12px" }}><Tag color={t.isLong ? T.green : T.gold} sm>{t.isLong ? "LT" : "ST"}</Tag></td>
                            <td style={{ padding: "8px 12px", color: T.muted }}>{(t.rate * 100).toFixed(0)}%</td>
                            <td style={{ padding: "8px 12px", color: T.red }}>{t.taxOwed > 0 ? fmtTax(t.taxOwed) : <span style={{ color: T.green }}>$0</span>}</td>
                            <td style={{ padding: "8px 12px", color: t.net >= 0 ? T.green : T.red, fontWeight: 700 }}>{fmt$(t.net)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ══ LOG ══ */}
          {tab === "log" && (
            <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden", animation: "fadeUp .3s ease" }}>
              <div style={{ background: T.surface, borderBottom: `1px solid ${T.border}`, padding: "10px 16px", display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontSize: 9, color: T.muted, letterSpacing: ".15em" }}>UNIFIED ACTIVITY LOG</span>
                <div style={{ display: "flex", gap: 8 }}>
                  <Tag color={T.green} sm>STOCK</Tag>
                  <Tag color={T.cyan} sm>CRYPTO</Tag>
                  <Tag color={T.red} sm>TAX</Tag>
                </div>
              </div>
              <div style={{ maxHeight: 500, overflowY: "auto", padding: "4px 0" }}>
                {log.length === 0
                  ? <div style={{ padding: 30, textAlign: "center", color: T.muted, fontSize: 11 }}>Start the bot to see activity</div>
                  : log.map(l => (
                    <div key={l.id} style={{ padding: "5px 18px", fontSize: 11, borderBottom: `1px solid ${T.border}33`, display: "flex", gap: 12, alignItems: "flex-start" }}>
                      <span style={{ color: T.muted, flexShrink: 0, fontSize: 9 }}>{l.time}</span>
                      {l.source && <Tag color={l.source === "STOCK" ? T.green : l.source === "CRYPTO" ? T.cyan : l.source === "TAX" ? T.red : T.muted} sm>{l.source}</Tag>}
                      <span style={{ color: l.color }}>{l.msg}</span>
                    </div>
                  ))
                }
              </div>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
