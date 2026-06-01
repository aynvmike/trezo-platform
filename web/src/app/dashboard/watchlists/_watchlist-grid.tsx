"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import type { IncomeEtf, IncomeEtfFamily } from "@/lib/positions";

type ListItem = {
  id: string;
  name: string;
  is_default: boolean;
  item_count: number;
  tickers?: { ticker: string; asset_type: string }[];
};

/**
 * The watchlists grid. Every list is a uniform card, plus an Income
 * ETF picker card that opens a full grouped library + custom-add form
 * below. Adding from the library or a custom ticker writes straight
 * to the Dividends layer (user_positions, asset_type=yieldmax).
 */
export function WatchlistGrid({
  lists,
  library,
  heldTickers,
  addHolding
}: {
  lists: ListItem[];
  library: IncomeEtf[];
  heldTickers: string[];
  addHolding: (formData: FormData) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  // Per-card expansion. Each card opens independently - Mike 2026-06-01:
  // "each box works individually and does not populate if another box
  // opens up." No accordion auto-collapse; expanding one doesn't
  // close any other.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpanded = (id: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const router = useRouter();
  const [removing, setRemoving] = useState<Set<string>>(new Set());
  async function removeTicker(listId: string, itemId: string) {
    setRemoving((s) => new Set(s).add(itemId));
    try {
      await fetch(`/api/watchlists/${listId}/items/${itemId}`, {
        method: "DELETE",
      });
      router.refresh();
    } finally {
      setRemoving((s) => {
        const next = new Set(s);
        next.delete(itemId);
        return next;
      });
    }
  }
  const held = useMemo(
    () => new Set(heldTickers.map((t) => t.toUpperCase())),
    [heldTickers]
  );
  const heldCount = useMemo(
    () => library.filter((e) => held.has(e.ticker.toUpperCase())).length,
    [library, held]
  );

  // Group library by family for grouped render.
  const FAMILY_ORDER: IncomeEtfFamily[] = useMemo(
    () => [
      "YieldMax",
      "REX / NEOS / Roundhill",
      "JPMorgan premium income",
      "Global X covered call",
      "iShares dividend",
      "Schwab / Vanguard dividend growth",
      "High-yield bond",
      "REIT, MLP & preferred"
    ],
    []
  );
  const byFamily = useMemo(() => {
    const m: Record<string, IncomeEtf[]> = {};
    for (const e of library) (m[e.family] ??= []).push(e);
    return m;
  }, [library]);

  return (
    <section className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {lists.map((l) => {
          const isOpen = expanded.has(l.id);
          return (
            <div
              key={l.id}
              className={cn(
                "rounded-xl border bg-white transition",
                isOpen
                  ? "border-weave-300 shadow-sm sm:col-span-2 lg:col-span-3"
                  : "border-weave-100 hover:-translate-y-0.5 hover:shadow-md"
              )}
            >
              <button
                type="button"
                onClick={() => toggleExpanded(l.id)}
                className="w-full text-left p-5"
                aria-expanded={isOpen}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-weave-800">{l.name}</p>
                  <div className="flex items-center gap-2">
                    {l.is_default && (
                      <span className="shrink-0 text-[10px] uppercase tracking-widest rounded-full bg-treasure-100 text-treasure-700 px-2 py-0.5">
                        Default
                      </span>
                    )}
                    <span className="text-[10px] uppercase tracking-widest text-weave-500">
                      {isOpen ? "Close" : "Open"}
                    </span>
                  </div>
                </div>
                <p className="mt-1.5 text-sm text-weave-500 leading-relaxed">
                  {l.is_default
                    ? "Your core hand-picked tickers — the names you trade and track most."
                    : "A ticker group you put together and manage."}
                </p>
                <p className="mt-2 text-sm text-weave-500">
                  {(l.tickers?.length ?? l.item_count)}{" "}
                  {(l.tickers?.length ?? l.item_count) === 1 ? "ticker" : "tickers"}
                </p>
              </button>

              {isOpen ? (
                <div className="border-t border-weave-100 p-4 space-y-2">
                  {(!l.tickers || l.tickers.length === 0) ? (
                    <p className="text-xs text-weave-500 italic">
                      Empty. Use the Add a ticker form at the top of the
                      page and pick this watchlist&apos;s chip.
                    </p>
                  ) : (
                    <ul className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1.5">
                      {l.tickers.map((t) => (
                        <li
                          key={`${l.id}-${t.ticker}`}
                          className="flex items-center justify-between gap-1.5 rounded border border-weave-100 bg-weave-50/30 px-2 py-1.5"
                        >
                          <span className="font-mono text-xs text-weave-800">
                            {t.ticker}
                            {t.asset_type === "crypto" ? (
                              <span className="ml-1 text-[9px] uppercase tracking-widest text-treasure-600">
                                C
                              </span>
                            ) : null}
                          </span>
                          {/* Remove uses the item id; the tickers prop
                              only carries ticker+asset_type for the
                              fast list view, so the deep-link Manage
                              button below handles edits per item. */}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="pt-2 border-t border-weave-50 flex items-center justify-between gap-2">
                    <p className="text-[11px] text-weave-500">
                      To rename, reorder, or per-ticker edit, open the full
                      manager.
                    </p>
                    <Link
                      href={`/dashboard/watchlists/${l.id}`}
                      className="text-[11px] text-weave-700 hover:text-weave-900 underline"
                    >
                      Manage →
                    </Link>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}

        {/* Income ETF picker — uniform card; opens the library below */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className={cn(
            "text-left rounded-xl border p-5 transition hover:-translate-y-0.5 hover:shadow-md",
            open ? "border-weave-300 bg-weave-50" : "border-weave-100 bg-white"
          )}
        >
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium text-weave-800">Income ETF picker</p>
            <span className="shrink-0 text-[10px] uppercase tracking-widest rounded-full bg-treasure-100 text-treasure-700 px-2 py-0.5">
              Dividends
            </span>
          </div>
          <p className="mt-1.5 text-sm text-weave-500 leading-relaxed">
            Pick from {library.length} ETFs across YieldMax, REX, JEPI,
            Global X, iShares, Schwab, bonds and REITs — or add any
            dividend-paying ticker the market data feed knows.
          </p>
          <p className="mt-2 text-sm text-weave-600">
            {heldCount} of {library.length} held ·{" "}
            <span className="text-weave-500">
              {open ? "tap to hide" : "tap to browse"}
            </span>
          </p>
        </button>
      </div>

      {open && (
        <div className="rounded-xl border border-weave-200 bg-white p-5 space-y-6">
          <div className="flex items-baseline justify-between gap-4 flex-wrap">
            <div>
              <h3 className="font-serif text-lg text-weave-800">
                Income ETF library
              </h3>
              <p className="beginner-only text-xs text-weave-500 leading-relaxed">
                Adding here writes to your Dividends layer — see them on the{" "}
                <Link
                  href="/dashboard/yieldmax"
                  className="underline hover:text-weave-700"
                >
                  Dividends page
                </Link>{" "}
                with live prices and DRIP tracking.
              </p>
            </div>
            <Link
              href="/dashboard/yieldmax"
              className="text-sm text-weave-600 hover:underline"
            >
              View your dividend holdings →
            </Link>
          </div>

          {FAMILY_ORDER.map((fam) => {
            const items = byFamily[fam] ?? [];
            if (items.length === 0) return null;
            return (
              <div key={fam} className="space-y-2">
                <h4 className="font-medium text-weave-800">{fam}</h4>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {items.map((etf) => {
                    const isHeld = held.has(etf.ticker.toUpperCase());
                    return (
                      <div
                        key={etf.ticker}
                        className={cn(
                          "rounded-lg border p-3 flex items-center justify-between gap-3",
                          isHeld
                            ? "border-emerald-200 bg-emerald-50"
                            : "border-weave-100 bg-weave-50/40"
                        )}
                      >
                        <div className="min-w-0">
                          <div className="flex items-baseline gap-2 flex-wrap">
                            <p className="font-mono font-medium text-weave-800">
                              {etf.ticker}
                            </p>
                            <span className="text-[10px] font-mono text-treasure-700">
                              ~{etf.dist_yield_pct}%
                            </span>
                          </div>
                          <p className="truncate text-xs text-weave-500">
                            {etf.name}
                          </p>
                        </div>
                        {isHeld ? (
                          <span className="text-[10px] uppercase tracking-widest rounded-full bg-emerald-100 text-emerald-800 px-2 py-0.5 shrink-0">
                            Held
                          </span>
                        ) : (
                          <form action={addHolding}>
                            <input type="hidden" name="ticker" value={etf.ticker} />
                            <input type="hidden" name="asset_type" value="yieldmax" />
                            <button
                              type="submit"
                              className="rounded-md bg-weave-600 px-3 py-1 text-xs font-medium text-treasure-50 hover:bg-weave-700 shrink-0"
                            >
                              Add
                            </button>
                          </form>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* Custom ticker add - "Add any dividend-paying ticker" */}
          <div className="border-t border-weave-100 pt-4 space-y-2">
            <h4 className="font-medium text-weave-800">
              Add any dividend-paying ticker
            </h4>
            <p className="text-xs text-weave-500 leading-relaxed">
              Not just the library. Type any symbol; if FINNHUB_API_KEY
              is set on the web service, the company name auto-fills
              from market data. Yield is optional - set it on the
              holding card once added.
            </p>
            <form action={addHolding} className="flex flex-wrap items-end gap-3">
              <label className="space-y-1">
                <span className="block text-[11px] uppercase tracking-widest text-weave-500">
                  Ticker
                </span>
                <input
                  type="text"
                  name="ticker"
                  placeholder="E.G. SCHD"
                  className="rounded border border-weave-200 px-2 py-1.5 text-sm font-mono uppercase w-32"
                  required
                />
              </label>
              <label className="space-y-1">
                <span className="block text-[11px] uppercase tracking-widest text-weave-500">
                  Shares
                </span>
                <input
                  type="number"
                  name="shares"
                  min={0}
                  step="0.01"
                  defaultValue={0}
                  className="rounded border border-weave-200 px-2 py-1.5 text-sm font-mono w-24"
                />
              </label>
              <label className="space-y-1">
                <span className="block text-[11px] uppercase tracking-widest text-weave-500">
                  Yield % (optional)
                </span>
                <input
                  type="number"
                  name="dist_yield_pct"
                  min={0}
                  step="0.01"
                  defaultValue={0}
                  className="rounded border border-weave-200 px-2 py-1.5 text-sm font-mono w-24"
                />
              </label>
              <input type="hidden" name="asset_type" value="yieldmax" />
              <button
                type="submit"
                className="rounded-md bg-weave-600 px-4 py-1.5 text-sm font-medium text-treasure-50 hover:bg-weave-700"
              >
                Add holding
              </button>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
