"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Chip = {
  id: string;
  name: string;
  default_asset_type: "stock" | "crypto";
};

/**
 * GlobalTickerAdd - one form at the top of /dashboard/watchlists that
 * replaces the per-list "Add any dividend-paying ticker" forms. The
 * user types a ticker, clicks a chip for which watchlist it lands in,
 * hits Add. The chip's default_asset_type drives whether the row is
 * stored as a stock or crypto so the user never has to think about it.
 *
 * Mike 2026-06-01: "remove the add separate stock from each box and
 * just have it as a pop loader for the page with tags of the
 * watchlists that are present and you select which tag to put it in."
 */
export function GlobalTickerAdd({ chips }: { chips: Chip[] }) {
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [pickedId, setPickedId] = useState<string | null>(
    chips.length === 1 ? chips[0].id : null
  );
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  if (chips.length === 0) return null;

  async function submit() {
    if (!ticker.trim() || !pickedId) {
      setMsg({ ok: false, text: "Pick a watchlist chip and enter a ticker." });
      return;
    }
    const chip = chips.find((c) => c.id === pickedId);
    if (!chip) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch(`/api/watchlists/${pickedId}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.trim().toUpperCase(),
          asset_type: chip.default_asset_type,
        }),
      });
      const j = await r.json();
      if (!r.ok || j.error) {
        setMsg({ ok: false, text: j.error ?? "Add failed." });
      } else {
        setMsg({ ok: true, text: `Added ${ticker.toUpperCase()} to ${chip.name}.` });
        setTicker("");
        router.refresh();
      }
    } catch (e) {
      setMsg({
        ok: false,
        text: e instanceof Error ? e.message : "Network error.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
      <div>
        <h2 className="font-medium text-weave-800">Add a ticker</h2>
        <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
          One form for every list. Type a symbol, click the watchlist
          chip you want it to land in, hit Add. The chip&apos;s default
          asset type (stock or crypto) is used automatically.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="e.g. AAPL"
          className="rounded border border-weave-200 px-3 py-1.5 text-sm font-mono uppercase w-32"
        />
        <button
          type="button"
          onClick={submit}
          disabled={busy || !ticker.trim() || !pickedId}
          className="rounded-md bg-weave-600 px-4 py-1.5 text-sm font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-50"
        >
          {busy ? "Adding..." : "Add"}
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {chips.map((c) => {
          const picked = pickedId === c.id;
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => setPickedId(c.id)}
              className={
                "text-xs rounded-full border px-3 py-1 transition " +
                (picked
                  ? "border-weave-600 bg-weave-600 text-treasure-50"
                  : "border-weave-200 bg-white text-weave-700 hover:bg-weave-50")
              }
            >
              {c.name}
              <span className="opacity-60 ml-1.5">
                {c.default_asset_type === "crypto" ? "(crypto)" : "(stock)"}
              </span>
            </button>
          );
        })}
      </div>

      {msg ? (
        <p
          className={
            "text-xs " + (msg.ok ? "text-emerald-700" : "text-red-700")
          }
        >
          {msg.text}
        </p>
      ) : null}
    </section>
  );
}
