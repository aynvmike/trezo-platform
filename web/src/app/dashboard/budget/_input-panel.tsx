"use client";

import { useState } from "react";
import { csvToTransactions, makeTxn, type Txn } from "@/lib/budget";

const INPUT =
  "flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500";
const FILE_BTN =
  "inline-flex cursor-pointer items-center gap-2 rounded-md bg-weave-600 px-4 py-2 text-sm font-medium text-treasure-50 hover:bg-weave-700";
const FILE_BTN_ALT =
  "inline-flex cursor-pointer items-center gap-2 rounded-md border border-weave-300 px-4 py-2 text-sm font-medium text-weave-700 hover:bg-weave-50";

export function InputPanel({
  onAdd,
  onClear,
  count
}: {
  onAdd: (txns: Txn[]) => void;
  onClear: () => void;
  count: number;
}) {
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [mDate, setMDate] = useState("");
  const [mMerchant, setMMerchant] = useState("");
  const [mAmount, setMAmount] = useState("");

  async function onCsv(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setError(null);
    try {
      const { txns, error: err } = csvToTransactions(await f.text());
      if (err) setError(err);
      else onAdd(txns);
    } catch {
      setError("That file could not be read. Choose a .csv export.");
    }
  }

  async function onScan(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setError(null);
    setScanning(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await fetch("/api/budget/scan", { method: "POST", body: fd });
      const j = (await r.json()) as {
        transactions?: { date: string; merchant: string; amount: number }[];
        error?: string;
      };
      if (j.transactions && j.transactions.length > 0) {
        onAdd(j.transactions.map((t) => makeTxn(t.date, t.merchant, t.amount)));
        if (j.error) setError(j.error);
      } else {
        setError(j.error ?? "No transactions could be read from that file.");
      }
    } catch {
      setError("The receipt could not be read. Please try again.");
    } finally {
      setScanning(false);
    }
  }

  function addManual() {
    const amt = Number(mAmount);
    if (!mMerchant.trim() || !(amt > 0)) {
      setError("Enter a merchant and a positive amount.");
      return;
    }
    setError(null);
    onAdd([makeTxn(mDate, mMerchant, amt)]);
    setMDate("");
    setMMerchant("");
    setMAmount("");
  }

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-5">
      {/* CSV */}
      <div>
        <p className="text-sm font-medium text-weave-800">Upload a CSV export</p>
        <p className="mt-0.5 text-xs text-weave-500">
          Rideshare, delivery, or a card statement — read in your browser,
          never uploaded.
        </p>
        <label className={`${FILE_BTN} mt-2`}>
          Choose a CSV
          <input
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={onCsv}
          />
        </label>
      </div>

      {/* Receipt / PDF scan */}
      <div className="border-t border-weave-50 pt-4">
        <p className="text-sm font-medium text-weave-800">
          Scan a receipt or statement
        </p>
        <p className="mt-0.5 text-xs text-weave-500">
          A photo or PDF is read by Trezo&apos;s AI to pull out the
          transactions, then discarded — it is not stored.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <label className={scanning ? `${FILE_BTN_ALT} opacity-50` : FILE_BTN_ALT}>
            {scanning ? "Reading…" : "Upload image or PDF"}
            <input
              type="file"
              accept="image/*,application/pdf"
              className="sr-only"
              disabled={scanning}
              onChange={onScan}
            />
          </label>
          <label className={scanning ? `${FILE_BTN_ALT} opacity-50` : FILE_BTN_ALT}>
            Take a photo
            <input
              type="file"
              accept="image/*"
              capture="environment"
              className="sr-only"
              disabled={scanning}
              onChange={onScan}
            />
          </label>
        </div>
      </div>

      {/* Manual entry */}
      <div className="border-t border-weave-50 pt-4">
        <p className="text-sm font-medium text-weave-800">Add one by hand</p>
        <div className="mt-2 grid sm:grid-cols-4 gap-2">
          <input
            type="date"
            value={mDate}
            onChange={(e) => setMDate(e.target.value)}
            className={INPUT}
            aria-label="Date"
          />
          <input
            type="text"
            value={mMerchant}
            onChange={(e) => setMMerchant(e.target.value)}
            placeholder="Merchant"
            maxLength={60}
            className={`${INPUT} sm:col-span-2`}
          />
          <input
            type="number"
            value={mAmount}
            onChange={(e) => setMAmount(e.target.value)}
            placeholder="Amount"
            min={0}
            step="0.01"
            className={INPUT}
          />
        </div>
        <button
          type="button"
          onClick={addManual}
          className="mt-2 rounded-md border border-weave-300 px-4 py-2 text-sm font-medium text-weave-700 hover:bg-weave-50"
        >
          Add transaction
        </button>
      </div>

      {error && <p className="text-sm text-amber-700">{error}</p>}

      {count > 0 && (
        <div className="border-t border-weave-50 pt-3 flex items-center justify-between">
          <span className="text-sm text-weave-600">
            {count} transaction{count === 1 ? "" : "s"} loaded.
          </span>
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-weave-400 hover:text-red-600"
          >
            Clear all
          </button>
        </div>
      )}
    </section>
  );
}
