import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Search, ChevronDown } from "lucide-react";
import { PageHeader } from "./PageHeader";

type FAQ = {
  q: string;
  a: string;
};

type Topic = {
  id: string;
  label: string;
  faqs: FAQ[];
};

const topics: Topic[] = [
  {
    id: "getting-started",
    label: "Getting started",
    faqs: [
      { q: "What is the Woven Basket?", a: "Trezo's seven wealth layers, ordered outer (most volatile) to inner (most protected). Each layer is its own bot with its own strategy and risk profile. They share capital but never fight for it." },
      { q: "Do I have to use all 7 layers?", a: "No. Toggle any layer on or off in its detail page. Most operators run 3–5 active layers and reserve the rest for later." },
      { q: "What's the difference between Paper and Live mode?", a: "Paper simulates every trade — nothing leaves the sandbox. Live routes real orders through your broker. You can switch back to paper instantly without losing positions." },
    ],
  },
  {
    id: "agents",
    label: "Bots & strategies",
    faqs: [
      { q: "What does TCS mean?", a: "Trezo Confidence Score, 0–1000. It's how the bot ranks a signal across pattern strength, options environment, fundamentals, risk/reward, and market context. 700+ is the live-trade threshold." },
      { q: "Why do some layers say 'idle'?", a: "Idle means the bot is waiting — usually for a weekly close, an ex-dividend date, or a regime shift. Paused means you turned it off. Idle is normal; paused is intentional." },
      { q: "How fast do tuning changes take effect?", a: "Within ~30 seconds. Daily profit target and loss limit apply immediately on the next tick." },
    ],
  },
  {
    id: "capital",
    label: "Capital & sleeves",
    faqs: [
      { q: "What is a capital sleeve?", a: "A portion of equity bounded by trade horizon. Active sleeve = intraday→next-day. Quick Options = 2–3 day. Holding = days→indefinite. Each sleeve has its own profit and hold rules — fast-recycling capital takes a bigger per-trade bite than locked capital." },
      { q: "Can the bot borrow across sleeves?", a: "No. Each sleeve is governed independently. This prevents a fast-strategy drawdown from eating into your long-term Holding allocation." },
    ],
  },
  {
    id: "taxes",
    label: "Taxes",
    faqs: [
      { q: "Are the tax numbers official?", a: "No. They're estimates based on your inputs and current federal brackets. For anything material, talk to a CPA. The Tax Optimizer is a planning tool, not advice." },
      { q: "What is tax-loss harvesting?", a: "Selling positions at a loss to offset realized gains, reducing the tax you owe. Trezo's optimizer flags candidates but doesn't auto-execute — you approve each harvest." },
    ],
  },
  {
    id: "security",
    label: "Security & privacy",
    faqs: [
      { q: "Does Trezo see my broker password?", a: "Never. You sign in on the broker's own OAuth page; they hand Trezo a refresh token. The token is encrypted at rest with your account key, and you can revoke it at any time." },
      { q: "What happens to data I import?", a: "The Budget Mirror parses statements locally in your browser. Nothing is uploaded, stored, or transmitted. Close the tab and the data is gone." },
    ],
  },
];

const vehicles = [
  {
    id: "options",
    label: "Options (calls, puts, spreads)",
    body: "Contracts that give the right to buy (call) or sell (put) a stock at a chosen price by a chosen date. A spread is two contracts together that cap both the cost and the maximum loss. Trezo uses defined-risk spreads — never naked options.",
  },
  {
    id: "income-etfs",
    label: "Income ETFs (JEPI, SCHD, O)",
    body: "ETFs designed for regular distributions. JEPI uses covered-call income, SCHD holds high-quality dividend stocks, O is a REIT that pays monthly. These feed the Dividends layer.",
  },
  {
    id: "futures",
    label: "Futures (and why Trezo doesn't trade them)",
    body: "Standardized contracts to buy or sell something at a future date. High leverage, fast-moving, and require a separate margin account. Trezo doesn't trade futures today — equity options give 90% of the same exposure with less margin risk.",
  },
  {
    id: "annuities",
    label: "Annuities",
    body: "Insurance contracts that pay a stream of income, typically in retirement. Trezo doesn't sell them — they're mentioned here because the Future Index Accounts (KINDRIP) use a similar long-horizon framing without the insurance layer or fees.",
  },
  {
    id: "crypto",
    label: "Crypto (spot & perpetual)",
    body: "Spot crypto = you own the coin. Perpetual = a futures-like contract with no expiry, used for leveraged exposure. Layer 1 trades both, with strict size limits relative to your crypto allocation.",
  },
];

export function HelpView() {
  const [query, setQuery] = useState("");
  const [openQ, setOpenQ] = useState<string | null>("getting-started-0");
  const [openV, setOpenV] = useState<string | null>(null);

  const filteredTopics = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return topics;
    return topics
      .map((t) => ({
        ...t,
        faqs: t.faqs.filter((f) => f.q.toLowerCase().includes(q) || f.a.toLowerCase().includes(q)),
      }))
      .filter((t) => t.faqs.length > 0);
  }, [query]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Quick answers"
        title="Help & FAQ"
        subtitle="Plain-language answers — search or browse by topic, so the rest of the app stays uncluttered."
      />

      {/* Search */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="relative"
      >
        <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2" style={{ color: "var(--muted-foreground)" }} />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the help — try 'paper mode' or 'TCS'…"
          className="w-full pl-11 pr-4 py-3 rounded-xl border border-border text-[13px] outline-none focus:border-treasure transition-colors"
          style={{ background: "var(--card)", color: "var(--foreground)" }}
        />
      </motion.div>

      {/* Topics */}
      {filteredTopics.length > 0 ? (
        filteredTopics.map((topic, ti) => (
          <section key={topic.id}>
            <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
              {topic.label}
            </h2>
            <div className="rounded-xl border border-border obsidian-panel divide-y divide-border overflow-hidden" style={{ background: "var(--card)" }}>
              {topic.faqs.map((faq, fi) => {
                const key = `${topic.id}-${fi}`;
                const open = openQ === key;
                return (
                  <motion.div
                    key={key}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: ti * 0.03 + fi * 0.03 }}
                  >
                    <button
                      onClick={() => setOpenQ(open ? null : key)}
                      className="w-full px-5 py-3.5 flex items-center justify-between text-left"
                    >
                      <span className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>{faq.q}</span>
                      <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }} style={{ color: "var(--muted-foreground)" }}>
                        <ChevronDown size={14} />
                      </motion.span>
                    </button>
                    <AnimatePresence initial={false}>
                      {open && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.22 }}
                          style={{ overflow: "hidden" }}
                        >
                          <p className="px-5 pb-4 text-[12px] leading-relaxed" style={{ color: "var(--muted-foreground)" }}>
                            {faq.a}
                          </p>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })}
            </div>
          </section>
        ))
      ) : (
        <div className="rounded-xl border border-dashed border-border p-8 text-center" style={{ background: "var(--card)" }}>
          <p className="text-[13px]" style={{ color: "var(--muted-foreground)" }}>
            No matches for "<span style={{ color: "var(--treasure)" }}>{query}</span>" — try a different term.
          </p>
        </div>
      )}

      {/* Investment Vehicles education */}
      <section className="pt-2">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-0.5 h-5 rounded-full" style={{ background: "var(--treasure)" }} />
          <div>
            <h2 className="text-[14px]" style={{ fontWeight: 500, fontFamily: "var(--font-serif)" }}>Investment Vehicles</h2>
            <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>The instruments Trezo uses, in plain words</p>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-2">
          {vehicles.map((v, i) => {
            const open = openV === v.id;
            return (
              <motion.div
                key={v.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className="rounded-xl border border-border obsidian-panel overflow-hidden"
                style={{ background: "var(--card)" }}
              >
                <button
                  onClick={() => setOpenV(open ? null : v.id)}
                  className="w-full px-5 py-3 flex items-center justify-between text-left"
                >
                  <span className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>{v.label}</span>
                  <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }} style={{ color: "var(--muted-foreground)" }}>
                    <ChevronDown size={14} />
                  </motion.span>
                </button>
                <AnimatePresence initial={false}>
                  {open && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.22 }}
                      style={{ overflow: "hidden" }}
                    >
                      <p className="px-5 pb-4 text-[12px] leading-relaxed" style={{ color: "var(--muted-foreground)" }}>
                        {v.body}
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>
      </section>

      <div className="h-4" />
    </div>
  );
}
