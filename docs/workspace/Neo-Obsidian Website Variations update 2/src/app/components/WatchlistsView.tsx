import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Plus, ChevronDown, Star, Filter } from "lucide-react";
import { PageHeader } from "./PageHeader";

type Watchlist = {
  id: string;
  name: string;
  type: "stock" | "crypto" | "etf";
  isDefault?: boolean;
  tickers: { symbol: string; name: string; price: number; change: number }[];
};

const watchlists: Watchlist[] = [
  {
    id: "core",
    name: "Core 8",
    type: "stock",
    isDefault: true,
    tickers: [
      { symbol: "NVDA", name: "NVIDIA", price: 891.45, change: 1.97 },
      { symbol: "AAPL", name: "Apple", price: 189.15, change: -0.84 },
      { symbol: "MSFT", name: "Microsoft", price: 425.30, change: 1.12 },
      { symbol: "GOOGL", name: "Alphabet", price: 174.20, change: 0.65 },
      { symbol: "META", name: "Meta", price: 512.80, change: 2.31 },
      { symbol: "AMZN", name: "Amazon", price: 195.40, change: 0.94 },
      { symbol: "TSLA", name: "Tesla", price: 254.10, change: 3.42 },
      { symbol: "AMD", name: "AMD", price: 152.80, change: -1.85 },
    ],
  },
  {
    id: "crypto",
    name: "Crypto Majors",
    type: "crypto",
    tickers: [
      { symbol: "BTC", name: "Bitcoin", price: 68910, change: 2.49 },
      { symbol: "ETH", name: "Ethereum", price: 3090, change: -2.98 },
      { symbol: "SOL", name: "Solana", price: 148.60, change: 4.12 },
      { symbol: "AVAX", name: "Avalanche", price: 36.20, change: -1.45 },
    ],
  },
  {
    id: "growth",
    name: "Growth Speculation",
    type: "stock",
    tickers: [
      { symbol: "PLTR", name: "Palantir", price: 28.40, change: 3.21 },
      { symbol: "SHOP", name: "Shopify", price: 64.20, change: 1.45 },
      { symbol: "CRWD", name: "CrowdStrike", price: 342.80, change: -0.92 },
    ],
  },
];

const incomeETFs = [
  { symbol: "SCHD", name: "Schwab US Dividend Equity", yield: "3.6%" },
  { symbol: "JEPI", name: "JPMorgan Equity Premium Income", yield: "7.8%" },
  { symbol: "O", name: "Realty Income", yield: "5.9%" },
  { symbol: "VYM", name: "Vanguard High Dividend Yield", yield: "2.9%" },
  { symbol: "DGRO", name: "iShares Dividend Growth", yield: "2.4%" },
  { symbol: "HDV", name: "iShares Core High Dividend", yield: "3.8%" },
];

const typeColors: Record<string, string> = {
  stock: "var(--sky)",
  crypto: "var(--treasure)",
  etf: "var(--emerald)",
};

export function WatchlistsView() {
  const [expandedId, setExpandedId] = useState<string | null>("core");
  const [newTicker, setNewTicker] = useState("");
  const [targetList, setTargetList] = useState("core");
  const [pickedETFs, setPickedETFs] = useState<string[]>(["SCHD", "JEPI"]);

  const toggleETF = (sym: string) =>
    setPickedETFs((cur) => (cur.includes(sym) ? cur.filter((x) => x !== sym) : [...cur, sym]));

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Plan & Research"
        title="Your watchlists"
        subtitle="What the bot scans. Group tickers by theme; the income-ETF library feeds the Dividends layer."
        action={
          <button
            className="flex items-center gap-1.5 px-3 py-2 rounded-md text-[12px]"
            style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
          >
            <Plus size={13} /> New watchlist
          </button>
        }
      />

      {/* Global add ticker bar */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="rounded-xl border border-border obsidian-panel p-4"
        style={{ background: "var(--card)" }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[200px]">
            <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Add ticker
            </div>
            <input
              type="text"
              value={newTicker}
              onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
              placeholder="e.g. NVDA, BTC, SCHD"
              className="w-full px-3 py-2 rounded-md border border-border text-[13px] outline-none"
              style={{ background: "var(--background)", color: "var(--foreground)", fontFamily: "var(--font-mono)" }}
            />
          </div>

          <div className="flex-1 min-w-[280px]">
            <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Add to list
            </div>
            <div className="flex flex-wrap gap-1.5">
              {watchlists.map((w) => (
                <button
                  key={w.id}
                  onClick={() => setTargetList(w.id)}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] border transition-colors"
                  style={{
                    background: targetList === w.id ? "var(--accent)" : "var(--background)",
                    borderColor: targetList === w.id ? "var(--treasure)" : "var(--border)",
                    color: targetList === w.id ? "var(--treasure)" : "var(--foreground)",
                  }}
                >
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: typeColors[w.type] }} />
                  {w.name}
                </button>
              ))}
            </div>
          </div>

          <button
            className="px-4 py-2 rounded-md text-[12px] mt-5"
            style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
          >
            Add
          </button>
        </div>

        <div className="flex items-center gap-2 mt-3 text-[11px]" style={{ color: "var(--muted-foreground)" }}>
          <Filter size={11} />
          <span>Ethical filters auto-applied — defense, tobacco, and fossil-fuel majors blocked.</span>
        </div>
      </motion.div>

      {/* Watchlist cards with inline accordion */}
      <div className="space-y-3">
        {watchlists.map((list, i) => {
          const expanded = expandedId === list.id;
          return (
            <motion.div
              key={list.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: i * 0.06 }}
              className="rounded-xl border border-border obsidian-panel overflow-hidden"
              style={{ background: "var(--card)" }}
            >
              <button
                onClick={() => setExpandedId(expanded ? null : list.id)}
                className="w-full px-5 py-4 flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ background: typeColors[list.type], boxShadow: `0 0 8px ${typeColors[list.type]}` }}
                  />
                  <span className="text-[14px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>
                    {list.name}
                  </span>
                  {list.isDefault && (
                    <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(196,150,74,0.12)", color: "var(--treasure)" }}>
                      <Star size={9} /> Default
                    </span>
                  )}
                  <span className="text-[11px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                    {list.tickers.length} items
                  </span>
                </div>
                <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.2 }} style={{ color: "var(--muted-foreground)" }}>
                  <ChevronDown size={15} />
                </motion.span>
              </button>

              <AnimatePresence initial={false}>
                {expanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.25 }}
                    style={{ overflow: "hidden" }}
                  >
                    <div className="border-t border-border">
                      {list.tickers.map((t, ti) => (
                        <motion.div
                          key={t.symbol}
                          initial={{ opacity: 0, x: -6 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: ti * 0.03 }}
                          className="px-5 py-2.5 flex items-center justify-between hover:bg-muted/50 transition-colors"
                          style={{ borderBottom: ti < list.tickers.length - 1 ? "1px solid var(--border)" : "none" }}
                        >
                          <div className="flex items-center gap-3">
                            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--foreground)", minWidth: "60px" }}>
                              {t.symbol}
                            </span>
                            <span className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>{t.name}</span>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className="text-[12px]" style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>
                              ${t.price.toLocaleString()}
                            </span>
                            <span
                              className="text-[12px] min-w-[60px] text-right"
                              style={{ fontFamily: "var(--font-mono)", color: t.change >= 0 ? "var(--emerald)" : "var(--rose)" }}
                            >
                              {t.change >= 0 ? "+" : ""}{t.change.toFixed(2)}%
                            </span>
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>

      {/* Income ETF library — sub-section */}
      <section className="pt-4">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-0.5 h-5 rounded-full" style={{ background: "var(--treasure)" }} />
          <div>
            <h2 className="text-[14px]" style={{ fontWeight: 500, fontFamily: "var(--font-serif)" }}>Income ETF Library</h2>
            <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Selected ETFs pour into the Dividends layer (Layer 6)</p>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {incomeETFs.map((etf, i) => {
            const picked = pickedETFs.includes(etf.symbol);
            return (
              <motion.button
                key={etf.symbol}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.05 + i * 0.04 }}
                whileHover={{ y: -2 }}
                onClick={() => toggleETF(etf.symbol)}
                className="rounded-lg border p-3 text-left transition-colors"
                style={{
                  background: picked ? "var(--accent)" : "var(--card)",
                  borderColor: picked ? "var(--treasure)" : "var(--border)",
                }}
              >
                <div className="flex items-start justify-between mb-1">
                  <div style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--foreground)" }}>{etf.symbol}</div>
                  <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: "rgba(16,185,129,0.12)", color: "var(--emerald)", fontFamily: "var(--font-mono)" }}>
                    {etf.yield}
                  </span>
                </div>
                <div className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{etf.name}</div>
              </motion.button>
            );
          })}
        </div>

        <div className="mt-3 px-3 py-2 rounded-md border border-dashed border-border flex items-center gap-2 text-[11px]" style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}>
          <span style={{ color: "var(--treasure)" }}>●</span>
          <span><span style={{ color: "var(--foreground)", fontWeight: 500 }}>{pickedETFs.length}</span> selected — these will feed Layer 6 dividend capture cycles.</span>
        </div>
      </section>

      <div className="h-4" />
    </div>
  );
}
