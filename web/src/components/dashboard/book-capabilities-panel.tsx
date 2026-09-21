"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useLiteRefresh } from "@/lib/use-lite";
import type { BookCapabilities, CapabilitiesResponse, TradingCapability } from "@/lib/agent-capabilities";

const STATUS: Record<TradingCapability["status"], string> = {
  enabled: "Enabled", disabled: "Switched off", unavailable: "Unavailable", unverified: "Unverified",
};

export function BookCapabilitiesPanel({ accountKey }: { accountKey?: string }) {
  const [books, setBooks] = useState<BookCapabilities[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshMs = useLiteRefresh(30) * 1000;
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/api/agents/capabilities", { cache: "no-store" });
        const body = await response.json() as CapabilitiesResponse;
        if (!response.ok || body.error) throw new Error(body.error || "Unable to verify capabilities.");
        if (!cancelled) { setBooks(body.books ?? []); setWarnings(body.warnings ?? []); setError(null); }
      } catch (err) {
        if (!cancelled) { setBooks([]); setWarnings([]); setError(err instanceof Error ? err.message : "Unable to verify capabilities."); }
      } finally { if (!cancelled) setLoading(false); }
    }
    void load();
    const interval = setInterval(load, refreshMs);
    return () => { cancelled = true; clearInterval(interval); };
  }, [refreshMs]);
  const visibleBooks = accountKey ? books.filter((book) => book.book_id === accountKey) : books;
  return <section className="space-y-3">
    <div>
      <h2 className="font-serif text-xl text-weave-800">Trading possibilities by account</h2>
      <p className="mt-1 text-sm text-weave-500">Each book has its own permissions and strategy switches. Enabled strategies still need a valid setup, available capital and passing risk checks.</p>
    </div>
    {warnings.map((warning) => <p role="alert" key={warning} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{warning}</p>)}
    {error ? <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Capabilities could not be verified: {error}</p>
      : loading ? <p className="text-sm text-weave-500">Checking each account…</p>
      : !visibleBooks.length ? <p className="text-sm text-weave-500">No trading account available.</p>
      : visibleBooks.map((book) => <div key={book.book_id} className="rounded-xl border border-weave-100 bg-white overflow-hidden">
        <div className="flex items-center justify-between gap-3 p-4 border-b border-weave-100">
          <h3 className="font-medium text-weave-800">{book.label}</h3>
          <Link className="text-xs text-weave-600 underline" href={`/dashboard/settings/bot?account=${encodeURIComponent(book.book_id)}`}>Tune this book</Link>
        </div>
        {book.note && <p className="px-4 py-2 text-xs text-weave-600">{book.note}</p>}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm min-w-[540px]">
          <thead className="text-xs text-weave-500 bg-weave-50"><tr><th className="p-3">Strategy</th><th className="p-3">Market direction</th><th className="p-3">Availability</th><th className="p-3">Details / next requirement</th></tr></thead>
          <tbody>{book.capabilities.map((lane) => <tr key={lane.id} className="border-t border-weave-50">
            <td className="p-3 font-medium text-weave-800">{lane.label}</td>
            <td className="p-3 text-weave-600">{lane.directions.map((direction) => direction.replace(/_/g, " ")).join(" / ") || "—"}</td>
            <td className="p-3"><span className={cn("rounded-full px-2 py-1 text-xs whitespace-nowrap", lane.status === "enabled" ? "bg-emerald-100 text-emerald-800" : lane.status === "disabled" ? "bg-weave-100 text-weave-600" : "bg-amber-100 text-amber-900")}>{STATUS[lane.status] ?? "Unverified"}</span></td>
            <td className="p-3 text-xs text-weave-600 leading-relaxed">{lane.reason}</td>
          </tr>)}</tbody>
        </table></div>
      </div>)}
  </section>;
}
