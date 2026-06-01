"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Star, Trash2, ChevronUp, ChevronDown, Upload, AlertTriangle } from "lucide-react";

type Watchlist = { id: string; name: string; is_default: boolean };
type Item = {
  id: string;
  ticker: string;
  notes: string | null;
  starred: boolean;
  position: number;
  ethical_override: boolean;
  ethical_override_reason: string | null;
};

type BlockedDecision = {
  ok: false;
  tier: 1 | 2 | 3 | 4;
  category: string;
  source: string;
  sourceUrl: string | null;
  evidence: string | null;
  overridable: boolean;
};

export function WatchlistDetail({
  watchlist,
  initialItems
}: {
  watchlist: Watchlist;
  initialItems: Item[];
}) {
  const router = useRouter();
  const [items, setItems] = useState<Item[]>(initialItems);
  const [error, setError] = useState<string | null>(null);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<{
    ticker: string;
    decision: BlockedDecision;
  } | null>(null);

  // ---- Add ticker ----
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<{ symbol: string; description: string }[]>([]);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (!query) {
      setSuggestions([]);
      return;
    }
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      try {
        const r = await fetch(`/api/tickers/search?q=${encodeURIComponent(query)}`);
        const j = (await r.json()) as { matches?: { symbol: string; description: string }[] };
        setSuggestions(j.matches ?? []);
      } catch {
        setSuggestions([]);
      }
    }, 200);
  }, [query]);

  async function addTicker(symbol: string, override?: { reason: string }) {
    setError(null);
    setAdding(true);
    try {
      const r = await fetch(`/api/watchlists/${watchlist.id}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: symbol,
          override: !!override,
          override_reason: override?.reason
        })
      });
      const j = await r.json();
      if (r.status === 201) {
        setItems((prev) => [...prev, j.item]);
        setQuery("");
        setSuggestions([]);
        setBlocked(null);
        return;
      }
      if (r.status === 409 && j.decision) {
        setBlocked({ ticker: symbol, decision: j.decision });
        return;
      }
      if (r.status === 403 && j.decision) {
        setError(
          `Tier ${j.decision.tier} block: ${j.decision.evidence ?? j.decision.category} — cannot override.`
        );
        return;
      }
      setError(j.error ?? "Add failed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Add failed");
    } finally {
      setAdding(false);
    }
  }

  async function removeItem(id: string) {
    if (!confirm("Remove this ticker?")) return;
    const prev = items;
    setItems((cur) => cur.filter((i) => i.id !== id));
    const r = await fetch(`/api/watchlists/${watchlist.id}/items/${id}`, {
      method: "DELETE"
    });
    if (!r.ok) {
      setError("Remove failed");
      setItems(prev);
    }
  }

  async function patchItem(id: string, body: Record<string, unknown>) {
    const r = await fetch(`/api/watchlists/${watchlist.id}/items/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (!r.ok) setError("Update failed");
  }

  function reorder(id: string, direction: "up" | "down") {
    const idx = items.findIndex((i) => i.id === id);
    if (idx < 0) return;
    const swap = direction === "up" ? idx - 1 : idx + 1;
    if (swap < 0 || swap >= items.length) return;
    const next = [...items];
    [next[idx], next[swap]] = [next[swap], next[idx]];
    setItems(next);
    void patchItem(id, { reorder: direction });
  }

  // QW7: native drag-drop reorder. Reorders the list in one gesture, then
  // persists by walking the dragged row to its new slot one swap at a time
  // (the API supports adjacent swaps; a multi-step drag is N of them).
  function moveItem(fromIdx: number, toIdx: number) {
    if (fromIdx === toIdx) return;
    const ordered = [...sortedItems];
    const [moved] = ordered.splice(fromIdx, 1);
    ordered.splice(toIdx, 0, moved);
    setItems(ordered.map((it, i) => ({ ...it, position: i })));
    const steps = Math.abs(toIdx - fromIdx);
    const dir: "up" | "down" = toIdx > fromIdx ? "down" : "up";
    void (async () => {
      for (let k = 0; k < steps; k++) {
        await patchItem(moved.id, { reorder: dir });
      }
    })();
  }

  async function toggleStar(item: Item) {
    setItems((cur) =>
      cur.map((i) => (i.id === item.id ? { ...i, starred: !i.starred } : i))
    );
    void patchItem(item.id, { starred: !item.starred });
  }

  async function importCsv(file: File) {
    setError(null);
    const text = await file.text();
    const symbols = Array.from(
      new Set(
        text
          .split(/[\s,;\n\r]+/)
          .map((s) => s.trim().toUpperCase())
          .filter((s) => /^[A-Z][A-Z0-9.\-]{0,11}$/.test(s))
      )
    );
    let added = 0;
    for (const s of symbols) {
      // Sequential to respect ethical filter checks and Finnhub rate limits
      try {
        const r = await fetch(`/api/watchlists/${watchlist.id}/items`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker: s })
        });
        const j = await r.json();
        if (r.status === 201) {
          setItems((cur) => [...cur, j.item]);
          added++;
        }
      } catch {
        // skip
      }
    }
    setError(`CSV import: ${added} of ${symbols.length} added (blocked/duplicate tickers skipped).`);
  }

  const sortedItems = useMemo(
    () => [...items].sort((a, b) => Number(b.starred) - Number(a.starred) || a.position - b.position),
    [items]
  );

  return (
    <div className="space-y-6">
      <header>
        <Link href="/dashboard/watchlists" className="text-sm text-weave-600 hover:underline">
          ← All watchlists
        </Link>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          {watchlist.name}
          {watchlist.is_default && (
            <span className="ml-3 align-middle text-[10px] uppercase tracking-widest rounded-full bg-treasure-100 text-treasure-700 px-2 py-0.5">
              Default
            </span>
          )}
        </h1>
      </header>

      {/* Add ticker */}
      <section className="rounded-xl border border-weave-100 bg-white p-4">
        <div className="flex items-end gap-2 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <label className="text-xs uppercase tracking-widest text-weave-500" htmlFor="add-ticker">
              Add ticker
            </label>
            <Input
              id="add-ticker"
              value={query}
              onChange={(e) => setQuery(e.target.value.toUpperCase())}
              placeholder="e.g. NVDA"
              autoComplete="off"
            />
            {suggestions.length > 0 && (
              <ul className="mt-1 rounded-md border border-weave-100 bg-white shadow-sm overflow-hidden">
                {suggestions.map((s) => (
                  <li key={s.symbol}>
                    <button
                      type="button"
                      onClick={() => addTicker(s.symbol)}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-weave-50 flex items-center justify-between"
                    >
                      <span className="font-mono">{s.symbol}</span>
                      <span className="text-weave-500 text-xs truncate ml-3">{s.description}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <Button
            onClick={() => query && addTicker(query.toUpperCase())}
            disabled={!query || adding}
          >
            {adding ? "Adding…" : "Add"}
          </Button>

          <label className="inline-flex items-center gap-2 cursor-pointer text-sm text-weave-600 hover:text-weave-800 px-3 py-2 rounded-md border border-weave-200">
            <Upload className="h-4 w-4" />
            CSV import
            <input
              type="file"
              accept=".csv,.txt"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void importCsv(f);
                e.currentTarget.value = "";
              }}
            />
          </label>
        </div>
        {error && (
          <p className="mt-3 text-sm text-amber-700" role="alert">
            {error}
          </p>
        )}
      </section>

      {/* Items */}
      <section className="rounded-xl border border-weave-100 bg-white overflow-hidden">
        {sortedItems.length === 0 ? (
          <p className="p-6 text-center text-sm text-weave-500">
            No tickers yet. Search or import to add some.
          </p>
        ) : (
          <ul className="divide-y divide-weave-50">
            {sortedItems.map((item, idx) => (
              <li
                key={item.id}
                draggable
                onDragStart={() => setDraggedId(item.id)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (!draggedId) return;
                  const from = sortedItems.findIndex((i) => i.id === draggedId);
                  if (from >= 0 && from !== idx) moveItem(from, idx);
                  setDraggedId(null);
                }}
                onDragEnd={() => setDraggedId(null)}
                className={cn(
                  "px-4 py-3 flex items-center gap-3 cursor-move",
                  draggedId === item.id && "opacity-50"
                )}
              >
                <div className="flex flex-col">
                  <button
                    onClick={() => reorder(item.id, "up")}
                    disabled={idx === 0}
                    className="text-weave-400 hover:text-weave-700 disabled:opacity-30"
                    aria-label="Move up"
                  >
                    <ChevronUp className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => reorder(item.id, "down")}
                    disabled={idx === sortedItems.length - 1}
                    className="text-weave-400 hover:text-weave-700 disabled:opacity-30"
                    aria-label="Move down"
                  >
                    <ChevronDown className="h-4 w-4" />
                  </button>
                </div>
                <button
                  onClick={() => toggleStar(item)}
                  aria-label={item.starred ? "Unstar" : "Star"}
                  className={cn(
                    "p-1 rounded hover:bg-weave-50",
                    item.starred ? "text-treasure-500" : "text-weave-300"
                  )}
                >
                  <Star
                    className={cn("h-4 w-4", item.starred && "fill-current")}
                  />
                </button>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-medium text-weave-800">{item.ticker}</span>
                    {item.ethical_override && (
                      <span
                        title={item.ethical_override_reason ?? "Ethical override"}
                        className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest rounded-full bg-amber-100 text-amber-800 px-2 py-0.5"
                      >
                        <AlertTriangle className="h-3 w-3" /> Override
                      </span>
                    )}
                  </div>
                  {item.notes && (
                    <p className="text-xs text-weave-500 truncate">{item.notes}</p>
                  )}
                </div>
                <button
                  onClick={() => removeItem(item.id)}
                  className="text-weave-400 hover:text-red-600 p-1 rounded"
                  aria-label="Remove"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Override dialog */}
      {blocked && (
        <OverrideDialog
          ticker={blocked.ticker}
          decision={blocked.decision}
          onCancel={() => setBlocked(null)}
          onConfirm={async (reason) => {
            await addTicker(blocked.ticker, { reason });
          }}
        />
      )}
    </div>
  );
}

function OverrideDialog({
  ticker,
  decision,
  onCancel,
  onConfirm
}: {
  ticker: string;
  decision: BlockedDecision;
  onCancel: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="fixed inset-0 bg-weave-900/40 z-50 grid place-items-center px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-6 w-6 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <h2 className="font-serif text-xl text-weave-800">
              {ticker} is filtered out
            </h2>
            <p className="mt-2 text-sm text-weave-600 leading-relaxed">
              <span className="font-medium">Category:</span> {decision.category}
              <br />
              <span className="font-medium">Source:</span> {decision.source}
              {decision.evidence && (
                <>
                  <br />
                  <span className="font-medium">Note:</span> {decision.evidence}
                </>
              )}
            </p>
            <p className="mt-3 text-xs text-weave-500">
              You can override Tier {decision.tier} exclusions, but the action is
              logged. Tier 1 (human rights) is never overridable.
            </p>
          </div>
        </div>
        <label className="mt-5 block text-sm font-medium text-weave-700">
          Why are you overriding?
        </label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          rows={3}
          className="mt-1 w-full rounded-md border border-weave-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-weave-500"
          placeholder="Free-text reason — at least 4 characters."
        />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={reason.trim().length < 4 || busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm(reason.trim());
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Adding…" : "Override and add"}
          </Button>
        </div>
      </div>
    </div>
  );
}
