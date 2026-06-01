"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

type Override = {
  id: string;
  ticker: string;
  strategy: string;
  reason: string | null;
  expires_at: string | null;
  created_at: string;
};

type Disabled = {
  id: string;
  ticker: string;
  reason: string | null;
  expires_at: string | null;
  created_at: string;
};

const STRATEGIES = [
  { v: "default", l: "Default" },
  { v: "pattern", l: "Pattern Engine" },
  { v: "stms", l: "STMS" },
  { v: "orb", l: "ORB" },
  { v: "extended", l: "Extended" },
  { v: "crypto", l: "Crypto" },
  { v: "iv_crush_short", l: "IV Crush Short (pre-earnings)" },
  { v: "dividend_capture_long", l: "Dividend Capture Long" }
];

/**
 * Expert Overrides client component. Renders inside Bot Tuning when
 * `expert_mode_enabled` is on. Two tools:
 *   1. Per-stock strategy pin — force the bot to use a chosen
 *      strategy on a specific ticker.
 *   2. Per-stock disable list — Risk Manager vetoes every signal on
 *      a disabled ticker with the user's reason in the note.
 *
 * Both honor TTLs server-side; clearing here is immediate.
 */
export function ExpertOverrides() {
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [disabled, setDisabled] = useState<Disabled[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Add-override form
  const [pinTicker, setPinTicker] = useState("");
  const [pinStrategy, setPinStrategy] = useState("default");
  const [pinExpiresHours, setPinExpiresHours] = useState("");
  const [pinReason, setPinReason] = useState("");

  // Add-disabled form
  const [disTicker, setDisTicker] = useState("");
  const [disReason, setDisReason] = useState("");
  const [disExpiresHours, setDisExpiresHours] = useState("");

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const [oRes, dRes] = await Promise.all([
        fetch("/api/expert/overrides", { cache: "no-store" }),
        fetch("/api/expert/disabled", { cache: "no-store" })
      ]);
      const oJson = await oRes.json();
      const dJson = await dRes.json();
      if (oJson.ok) setOverrides(oJson.rows as Override[]);
      if (dJson.ok) setDisabled(dJson.rows as Disabled[]);
      if (!oJson.ok && oJson.error) setErr(oJson.error);
      if (!dJson.ok && dJson.error) setErr(dJson.error);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function expiresAtIso(hoursStr: string): string | null {
    const n = Number(hoursStr);
    if (!Number.isFinite(n) || n <= 0) return null;
    return new Date(Date.now() + n * 3600 * 1000).toISOString();
  }

  async function addPin() {
    if (!pinTicker.trim()) return;
    try {
      const r = await fetch("/api/expert/overrides", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: pinTicker,
          strategy: pinStrategy,
          reason: pinReason || null,
          expires_at: expiresAtIso(pinExpiresHours)
        })
      });
      const j = await r.json();
      if (!j.ok) {
        setErr(j.error ?? "Could not save pin.");
        return;
      }
      setPinTicker("");
      setPinReason("");
      setPinExpiresHours("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    }
  }

  async function removePin(ticker: string) {
    try {
      await fetch(`/api/expert/overrides?ticker=${encodeURIComponent(ticker)}`, {
        method: "DELETE"
      });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    }
  }

  async function addDisable() {
    if (!disTicker.trim()) return;
    try {
      const r = await fetch("/api/expert/disabled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: disTicker,
          reason: disReason || null,
          expires_at: expiresAtIso(disExpiresHours)
        })
      });
      const j = await r.json();
      if (!j.ok) {
        setErr(j.error ?? "Could not save disable.");
        return;
      }
      setDisTicker("");
      setDisReason("");
      setDisExpiresHours("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    }
  }

  async function removeDisable(ticker: string) {
    try {
      await fetch(`/api/expert/disabled?ticker=${encodeURIComponent(ticker)}`, {
        method: "DELETE"
      });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <h2 className="font-medium text-weave-800 mb-1">Expert overrides</h2>
        <p className="text-sm text-weave-500 leading-relaxed">
          Manual control over per-stock decisions. Pins force the bot
          to use a specific strategy on a ticker; disables block the
          ticker from auto-trading entirely. Both accept TTLs — leave
          blank for &ldquo;until I remove it.&rdquo;
        </p>
      </div>

      {err && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          {err}
        </div>
      )}

      {/* Pins */}
      <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-4">
        <div>
          <h3 className="font-medium text-weave-800 text-sm">
            Strategy pins
          </h3>
          <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
            When a ticker is pinned, the per-stock selector is bypassed
            and the bot uses your chosen strategy.
          </p>
        </div>

        <div className="grid sm:grid-cols-5 gap-2 items-end">
          <Field label="Ticker">
            <input
              type="text"
              value={pinTicker}
              onChange={(e) => setPinTicker(e.target.value.toUpperCase())}
              placeholder="AAPL"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Strategy">
            <select
              value={pinStrategy}
              onChange={(e) => setPinStrategy(e.target.value)}
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm"
            >
              {STRATEGIES.map((s) => (
                <option key={s.v} value={s.v}>
                  {s.l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Expires in (hours)">
            <input
              type="number"
              min={0}
              step={1}
              value={pinExpiresHours}
              onChange={(e) => setPinExpiresHours(e.target.value)}
              placeholder="blank = forever"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Reason (optional)">
            <input
              type="text"
              value={pinReason}
              onChange={(e) => setPinReason(e.target.value)}
              placeholder="why this pin"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm"
            />
          </Field>
          <button
            type="button"
            onClick={addPin}
            className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700"
          >
            Add pin
          </button>
        </div>

        {loading ? (
          <p className="text-xs text-weave-400">Loading...</p>
        ) : overrides.length === 0 ? (
          <p className="text-xs text-weave-400 italic">No active strategy pins.</p>
        ) : (
          <ul className="divide-y divide-weave-50 -mt-1">
            {overrides.map((o) => (
              <li
                key={o.id}
                className="py-2 flex items-baseline justify-between gap-3 flex-wrap"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-mono text-sm">
                    <span className="font-medium text-weave-800">{o.ticker}</span>
                    {" → "}
                    <span className="text-weave-600">{prettyStrategy(o.strategy)}</span>
                  </p>
                  <p className="text-[11px] text-weave-500 leading-relaxed">
                    {o.reason ?? "—"} ·{" "}
                    {o.expires_at
                      ? `expires ${new Date(o.expires_at).toLocaleString()}`
                      : "no expiration"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => removePin(o.ticker)}
                  className="text-[11px] text-red-700 hover:underline"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Disabled list */}
      <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-4">
        <div>
          <h3 className="font-medium text-weave-800 text-sm">Disabled tickers</h3>
          <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
            Risk Manager vetoes every signal on a ticker in this list,
            with your reason in the veto note.
          </p>
        </div>

        <div className="grid sm:grid-cols-4 gap-2 items-end">
          <Field label="Ticker">
            <input
              type="text"
              value={disTicker}
              onChange={(e) => setDisTicker(e.target.value.toUpperCase())}
              placeholder="NVDA"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Expires in (hours)">
            <input
              type="number"
              min={0}
              step={1}
              value={disExpiresHours}
              onChange={(e) => setDisExpiresHours(e.target.value)}
              placeholder="blank = forever"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Reason (optional)">
            <input
              type="text"
              value={disReason}
              onChange={(e) => setDisReason(e.target.value)}
              placeholder="why disabled"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm"
            />
          </Field>
          <button
            type="button"
            onClick={addDisable}
            className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700"
          >
            Disable ticker
          </button>
        </div>

        {loading ? (
          <p className="text-xs text-weave-400">Loading...</p>
        ) : disabled.length === 0 ? (
          <p className="text-xs text-weave-400 italic">No disabled tickers.</p>
        ) : (
          <ul className="divide-y divide-weave-50 -mt-1">
            {disabled.map((d) => (
              <li
                key={d.id}
                className="py-2 flex items-baseline justify-between gap-3 flex-wrap"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-mono text-sm font-medium text-weave-800">
                    {d.ticker}
                  </p>
                  <p className="text-[11px] text-weave-500 leading-relaxed">
                    {d.reason ?? "—"} ·{" "}
                    {d.expires_at
                      ? `expires ${new Date(d.expires_at).toLocaleString()}`
                      : "no expiration"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => removeDisable(d.ticker)}
                  className={cn("text-[11px] text-red-700 hover:underline")}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-[11px] uppercase tracking-widest text-weave-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function prettyStrategy(s: string): string {
  const known = STRATEGIES.find((x) => x.v === s);
  return known ? known.l : s;
}
