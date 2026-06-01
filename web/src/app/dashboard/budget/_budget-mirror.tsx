"use client";

import { useMemo, useState } from "react";
import { analyze, type Txn, type BudgetAnalysis } from "@/lib/budget";
import { InputPanel } from "./_input-panel";
import { Simulator } from "./_simulator";
import { Planner } from "./_planner";

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

function usd2(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  });
}

function monthLabel(key: string): string {
  const [y, m] = key.split("-");
  const d = new Date(Number(y), Number(m) - 1, 1);
  if (Number.isNaN(d.getTime())) return key;
  return d.toLocaleString(undefined, { month: "short", year: "numeric" });
}

export function BudgetMirror() {
  const [txns, setTxns] = useState<Txn[]>([]);
  const analysis = useMemo<BudgetAnalysis | null>(
    () => (txns.length > 0 ? analyze(txns) : null),
    [txns]
  );

  return (
    <section className="space-y-6">
      <InputPanel
        onAdd={(added) => setTxns((prev) => [...prev, ...added])}
        onClear={() => setTxns([])}
        count={txns.length}
      />
      {analysis ? (
        <>
          <Dashboard a={analysis} />
          <Simulator a={analysis} />
        </>
      ) : (
        <NoDataHint />
      )}
      {/* The planner + spend-vs-save comparison work standalone — */}
      {/* no uploaded data required. */}
      <Planner a={analysis} />
    </section>
  );
}

function Dashboard({ a }: { a: BudgetAnalysis }) {
  const catMax = Math.max(1, ...a.byCategory.map((c) => c.total));
  const recentMonths = a.byMonth.slice(-12);
  const monthMax = Math.max(1, ...recentMonths.map((m) => m.total));
  const range =
    a.firstDate && a.lastDate
      ? `${a.firstDate} → ${a.lastDate}`
      : "dates not detected";

  return (
    <div className="space-y-6">
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-3">
        <KPI label="Total spend" value={usd(a.total)} />
        <KPI label="This month" value={usd(a.thisMonth)} />
        <KPI label="Year to date" value={usd(a.ytd)} />
        <KPI label="Per-month average" value={usd(a.perMonthAvg)} />
        <KPI label="Avg per transaction" value={usd2(a.average)} />
        <KPI label="Transactions" value={String(a.txnCount)} />
      </div>
      <p className="text-xs text-weave-500">
        {a.txnCount} transactions over {a.monthsCovered} month
        {a.monthsCovered === 1 ? "" : "s"} · {range}
      </p>

      <div>
        <h3 className="font-medium text-weave-800 mb-3">By category</h3>
        <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
          {a.byCategory.map((c) => (
            <div key={c.category}>
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-weave-700">{c.category}</span>
                <span className="font-mono text-weave-800">
                  {usd(c.total)}{" "}
                  <span className="text-xs text-weave-400">({c.count})</span>
                </span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-weave-100 overflow-hidden">
                <div
                  className="h-full bg-treasure-500"
                  style={{ width: `${(c.total / catMax) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {recentMonths.length > 1 && (
        <div>
          <h3 className="font-medium text-weave-800 mb-3">Monthly spending</h3>
          <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-2">
            {recentMonths.map((m) => (
              <div key={m.month} className="flex items-center gap-3">
                <span className="w-24 shrink-0 text-xs text-weave-500">
                  {monthLabel(m.month)}
                </span>
                <div className="flex-1 h-3 rounded-full bg-weave-100 overflow-hidden">
                  <div
                    className="h-full bg-weave-500"
                    style={{ width: `${(m.total / monthMax) * 100}%` }}
                  />
                </div>
                <span className="w-20 shrink-0 text-right font-mono text-sm text-weave-800">
                  {usd(m.total)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <h3 className="font-medium text-weave-800 mb-3">
          Most frequent merchants
        </h3>
        <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[420px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-4 py-3">Merchant</th>
                <th className="px-4 py-3 text-right">Count</th>
                <th className="px-4 py-3 text-right">Total</th>
                <th className="px-4 py-3 text-right">Avg</th>
              </tr>
            </thead>
            <tbody>
              {a.topMerchants.map((m) => (
                <tr
                  key={m.merchant}
                  className="border-b border-weave-50 last:border-0"
                >
                  <td className="px-4 py-2.5 text-weave-800">{m.merchant}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-weave-500">
                    {m.count}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-weave-800">
                    {usd(m.total)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-weave-500">
                    {usd2(m.total / Math.max(1, m.count))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function NoDataHint() {
  return (
    <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-600 leading-relaxed">
      <p className="font-medium text-weave-800">
        Add some transactions to unlock the full picture.
      </p>
      <p className="mt-1">
        Upload a CSV, scan a receipt or statement, or type a few entries
        above — that unlocks your spending dashboard and the savings
        simulator. The goal planner and spend-vs-save comparison below
        work right now, with no data needed.
      </p>
    </div>
  );
}

function KPI({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5">
      <p className="text-xs uppercase tracking-widest text-weave-500">{label}</p>
      <p className="mt-2 font-serif text-2xl text-weave-800">{value}</p>
    </div>
  );
}
