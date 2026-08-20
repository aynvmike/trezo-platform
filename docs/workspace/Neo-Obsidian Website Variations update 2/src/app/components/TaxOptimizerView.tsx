import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown, AlertTriangle } from "lucide-react";
import { PageHeader } from "./PageHeader";

const accountTypes = [
  {
    id: "roth",
    name: "Roth IRA",
    accent: "var(--emerald)",
    short: "Tax-free growth, tax-free withdrawals after 59½",
    body: "You contribute money you've already paid taxes on. Inside the account it grows untaxed forever, and you owe nothing when you pull it out (as long as you wait until 59½). The single most powerful account if you expect to be in a higher bracket later.",
  },
  {
    id: "trad",
    name: "Traditional IRA / 401(k)",
    accent: "var(--sky)",
    short: "Tax break today, taxed when withdrawn",
    body: "Contributions reduce your current taxable income. Growth is untaxed inside the account, but every dollar withdrawn in retirement counts as ordinary income. Best when you expect a lower bracket in retirement.",
  },
  {
    id: "taxable",
    name: "Taxable brokerage",
    accent: "var(--amber)",
    short: "No tax shelter, but no rules — pure flexibility",
    body: "No contribution limits, no withdrawal age. You owe capital gains tax when you sell (long-term rates are favorable if held over a year). This is where tax-loss harvesting earns its keep.",
  },
  {
    id: "future",
    name: "Future Index Accounts (KINDRIP)",
    accent: "var(--treasure)",
    short: "Custodial UTMA/529 — the children's vault",
    body: "Used by Layer 7 (KINDRIP). The KINDRIP layer drips small recurring buys of responsible index funds into custodial accounts for future generations. Tax treatment depends on which vehicle (UTMA = beneficiary's rate; 529 = tax-free for qualified education).",
  },
];

const quarterlies = [
  { q: "Q1 2026", realized: 4280, acquired: "Jan–Mar", due: 642, status: "paid" },
  { q: "Q2 2026", realized: 6420, acquired: "Apr–Jun", due: 963, status: "due", deadline: "Jun 15" },
  { q: "Q3 2026", realized: 0, acquired: "Jul–Sep", due: 0, status: "upcoming" },
  { q: "Q4 2026", realized: 0, acquired: "Oct–Dec", due: 0, status: "upcoming" },
];

const statusStyles: Record<string, { color: string; bg: string; label: string }> = {
  paid: { color: "var(--emerald)", bg: "rgba(16,185,129,0.12)", label: "Paid" },
  due: { color: "var(--amber)", bg: "rgba(245,158,11,0.12)", label: "Due soon" },
  upcoming: { color: "var(--muted-foreground)", bg: "var(--muted)", label: "Upcoming" },
};

export function TaxOptimizerView() {
  const [filing, setFiling] = useState("Single");
  const [income, setIncome] = useState(85000);
  const [openAcct, setOpenAcct] = useState<string | null>(null);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-7">
      <PageHeader
        eyebrow="Plan & Research"
        title="Your tax picture"
        subtitle="A plain-English view of what you'll likely owe, your quarterly payments, and which accounts shelter growth."
      />

      {/* Disclaimer banner */}
      <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg border border-dashed" style={{ borderColor: "rgba(245,158,11,0.4)", background: "rgba(245,158,11,0.05)" }}>
        <AlertTriangle size={13} style={{ color: "var(--amber)", marginTop: "2px", flexShrink: 0 }} />
        <p className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>
          <span style={{ color: "var(--amber)", fontWeight: 500 }}>Estimates, not tax advice.</span> These numbers come from your inputs and 2026 federal brackets. For anything material, talk to a CPA.
        </p>
      </div>

      {/* Estimated tax breakdown — hero tiles */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Estimated 2026 liability
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { label: "Federal income tax", value: "$12,840", sub: "22% bracket", color: "var(--foreground)" },
            { label: "Self-employment tax", value: "$4,260", sub: "15.3% on trading gains", color: "var(--amber)" },
            { label: "Capital gains tax", value: "$2,180", sub: "15% long-term rate", color: "var(--sky)" },
            { label: "Total est. owed", value: "$19,280", sub: "After deductions", color: "var(--treasure)" },
          ].map((stat, i) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: i * 0.07 }}
              whileHover={{ y: -2 }}
              className="rounded-xl border border-border obsidian-panel p-4"
              style={{ background: "var(--card)" }}
            >
              <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                {stat.label}
              </div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "22px", fontWeight: 500, color: stat.color }}>
                {stat.value}
              </div>
              <div className="text-[11px] mt-1" style={{ color: "var(--muted-foreground)" }}>{stat.sub}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Profile settings */}
      <section className="rounded-xl border border-border obsidian-panel p-5" style={{ background: "var(--card)" }}>
        <h3 className="text-[13px] mb-4" style={{ fontWeight: 500 }}>Tax Profile</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Filing Status
            </div>
            <div className="flex flex-wrap gap-1.5">
              {["Single", "Married", "HoH"].map((s) => (
                <button
                  key={s}
                  onClick={() => setFiling(s)}
                  className="px-3 py-1.5 rounded-md text-[11px] border transition-colors"
                  style={{
                    background: filing === s ? "var(--accent)" : "var(--background)",
                    borderColor: filing === s ? "var(--treasure)" : "var(--border)",
                    color: filing === s ? "var(--treasure)" : "var(--foreground)",
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="flex items-end justify-between mb-2">
              <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                W-2 / Earned Income
              </span>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--treasure)", fontSize: "13px", fontWeight: 500 }}>
                ${income.toLocaleString()}
              </span>
            </div>
            <input
              type="range"
              min={20000} max={400000} step={5000}
              value={income}
              onChange={(e) => setIncome(Number(e.target.value))}
              className="w-full"
              style={{ accentColor: "var(--treasure)" }}
            />
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Trading P&L YTD
            </div>
            <div className="px-3 py-1.5 rounded-md border border-border text-[13px]" style={{ background: "var(--background)", fontFamily: "var(--font-mono)", color: "var(--emerald)" }}>
              +$28,140
            </div>
          </div>
        </div>
      </section>

      {/* Quarterly payments */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Quarterly Estimated Payments
        </h2>
        <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
          <table className="w-full text-[12px]">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Quarter", "Acquired", "Realized Gain", "Amount Due", "Status"].map((c) => (
                  <th key={c} className="px-5 py-3 text-left" style={{ color: "var(--muted-foreground)", fontWeight: 500, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {quarterlies.map((q, i) => {
                const ss = statusStyles[q.status];
                return (
                  <motion.tr
                    key={q.q}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.1 + i * 0.06 }}
                    style={{ borderBottom: i < quarterlies.length - 1 ? "1px solid var(--border)" : "none" }}
                  >
                    <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}>{q.q}</td>
                    <td className="px-5 py-3" style={{ color: "var(--muted-foreground)" }}>{q.acquired}</td>
                    <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", color: q.realized > 0 ? "var(--emerald)" : "var(--muted-foreground)" }}>
                      {q.realized > 0 ? `+$${q.realized.toLocaleString()}` : "—"}
                    </td>
                    <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: q.due > 0 ? "var(--foreground)" : "var(--muted-foreground)" }}>
                      {q.due > 0 ? `$${q.due.toLocaleString()}` : "—"}
                    </td>
                    <td className="px-5 py-3">
                      <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: ss.bg, color: ss.color }}>
                        {ss.label}{q.deadline ? ` · ${q.deadline}` : ""}
                      </span>
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Account types — nested disclosures */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Tax-Advantaged Accounts
        </h2>
        <p className="text-[12px] mb-3" style={{ color: "var(--muted-foreground)" }}>
          The four shelters Trezo's strategies route through. Tap any one to expand.
        </p>

        <div className="space-y-2">
          {accountTypes.map((a, i) => {
            const open = openAcct === a.id;
            return (
              <motion.div
                key={a.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.06 }}
                className="rounded-xl border border-border obsidian-panel overflow-hidden"
                style={{ background: "var(--card)" }}
              >
                <button
                  onClick={() => setOpenAcct(open ? null : a.id)}
                  className="w-full px-5 py-3.5 flex items-center justify-between text-left"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ background: a.accent, boxShadow: `0 0 8px ${a.accent}` }}
                    />
                    <div>
                      <div className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>{a.name}</div>
                      <div className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{a.short}</div>
                    </div>
                  </div>
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
                      transition={{ duration: 0.25 }}
                      style={{ overflow: "hidden" }}
                    >
                      <div className="px-5 pb-4 pt-1 border-t border-border" style={{ background: "var(--muted)" }}>
                        <p className="text-[12px] leading-relaxed pt-3" style={{ color: "var(--muted-foreground)" }}>
                          {a.body}
                        </p>
                      </div>
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
