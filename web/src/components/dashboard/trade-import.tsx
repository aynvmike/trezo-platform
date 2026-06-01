"use client";

import { useState } from "react";

type ImportResult = {
  ok: boolean;
  inserted?: number;
  skipped?: number;
  errors?: { index: number; reason: string }[];
  error?: string;
};

/**
 * TradeImport — lets Mike feed his own real trading history into the
 * learning ledger. Two flows in one card:
 *
 *   1) CSV paste — comma-separated, first row is the header. Required
 *      columns: ticker, entry_price, exit_price. Optional: side,
 *      strategy, quantity, opened_at, closed_at, realized_pnl_usd,
 *      exit_reason, notes, tcs_at_entry.
 *   2) Single trade form — pick a few fields, hit Add, log the trade.
 *
 * Both write to /api/learning/import which inserts into trade_outcomes
 * with source_table='manual_import'. The Learning Insights panel
 * above already includes manual rows automatically — same query, no
 * special-casing.
 */
type ExtractedRow = Record<string, unknown>;

export function TradeImport() {
  const [csvText, setCsvText] = useState("");
  // File upload + extraction state
  const [extracting, setExtracting] = useState(false);
  const [extracted, setExtracted] = useState<ExtractedRow[] | null>(null);
  const [extractNote, setExtractNote] = useState<string | null>(null);
  const [extractConfidence, setExtractConfidence] = useState<string | null>(null);
  const [extractError, setExtractError] = useState<string | null>(null);

  async function uploadFile(file: File) {
    setExtracting(true);
    setExtracted(null);
    setExtractError(null);
    setExtractNote(null);
    setExtractConfidence(null);
    try {
      const fd = new FormData();
      fd.set("file", file);
      const r = await fetch("/api/learning/extract", {
        method: "POST",
        body: fd,
      });
      const j = await r.json();
      if (!j.ok) {
        setExtractError(j.error || "Extraction failed.");
        return;
      }
      setExtracted((j.rows as ExtractedRow[]) ?? []);
      setExtractConfidence(j.confidence ?? null);
      setExtractNote(j.notes ?? null);
    } catch (e) {
      setExtractError(e instanceof Error ? e.message : "Network error.");
    } finally {
      setExtracting(false);
    }
  }

  async function importExtracted() {
    if (!extracted || extracted.length === 0) return;
    await postRows(extracted);
    setExtracted(null);
  }

  const [singleTicker, setSingleTicker] = useState("");
  const [singleSide, setSingleSide] = useState<"long" | "short">("long");
  const [singleStrategy, setSingleStrategy] = useState("manual");
  const [singleEntry, setSingleEntry] = useState("");
  const [singleExit, setSingleExit] = useState("");
  const [singleQty, setSingleQty] = useState("");
  const [singleOpened, setSingleOpened] = useState("");
  const [singleClosed, setSingleClosed] = useState("");
  const [singleNotes, setSingleNotes] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function postRows(rows: Record<string, unknown>[]) {
    setBusy(true);
    setResult(null);
    try {
      const r = await fetch("/api/learning/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows }),
      });
      const j = (await r.json()) as ImportResult;
      setResult(j);
    } catch (e) {
      setResult({
        ok: false,
        error: e instanceof Error ? e.message : "Network error",
      });
    } finally {
      setBusy(false);
    }
  }

  function parseCsv(text: string): Record<string, string>[] {
    const lines = text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length < 2) return [];
    const headers = lines[0].split(",").map((h) => h.trim());
    return lines.slice(1).map((line) => {
      // Naive CSV: doesn't handle quoted commas. For the import case
      // (ticker, prices, ISO dates) this is fine; if Mike needs full
      // CSV we can swap in PapaParse later.
      const cells = line.split(",").map((c) => c.trim());
      const row: Record<string, string> = {};
      headers.forEach((h, i) => {
        if (cells[i] !== undefined) row[h] = cells[i];
      });
      return row;
    });
  }

  async function importCsv() {
    const rows = parseCsv(csvText);
    if (rows.length === 0) {
      setResult({ ok: false, error: "No data rows parsed from the CSV." });
      return;
    }
    await postRows(rows);
  }

  async function addSingle() {
    if (!singleTicker.trim() || !singleEntry || !singleExit) {
      setResult({
        ok: false,
        error: "Ticker, entry price, and exit price are required.",
      });
      return;
    }
    await postRows([
      {
        ticker: singleTicker,
        side: singleSide,
        strategy: singleStrategy || "manual",
        entry_price: singleEntry,
        exit_price: singleExit,
        quantity: singleQty || 1,
        opened_at: singleOpened || undefined,
        closed_at: singleClosed || undefined,
        notes: singleNotes || undefined,
      },
    ]);
    if (result?.ok || true) {
      setSingleTicker("");
      setSingleEntry("");
      setSingleExit("");
      setSingleQty("");
      setSingleOpened("");
      setSingleClosed("");
      setSingleNotes("");
    }
  }

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-4">
      <div>
        <h2 className="font-medium text-weave-800">
          Import your own trade history
        </h2>
        <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
          The bot can learn from trades you placed outside of Trezo too.
          Drop a CSV of your past trades or log a single one — both
          land in the same learning ledger as the bot&apos;s paper
          trades, so the Learning Insights panel above grows richer
          immediately.
        </p>
      </div>

      {/* File upload — PDF / image / Excel / Word */}
      <div className="rounded-lg border border-weave-100 bg-weave-50/50 p-3 space-y-2">
        <div>
          <p className="text-xs font-medium text-weave-800">
            No CSV? Upload your file
          </p>
          <p className="text-[11px] text-weave-500 leading-relaxed">
            Drop a broker statement, screenshot, Excel sheet, or Word
            doc. Claude reads the document and proposes rows you can
            review before they hit the ledger. Max 10MB.
          </p>
        </div>
        <input
          type="file"
          accept="application/pdf,image/*,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void uploadFile(f);
          }}
          className="block text-xs"
        />
        {extracting ? (
          <p className="text-[11px] text-weave-500">
            Extracting — this can take 10–30 seconds for a long PDF...
          </p>
        ) : null}
        {extractError ? (
          <p className="text-[11px] text-red-700">{extractError}</p>
        ) : null}
        {extracted && extracted.length > 0 ? (
          <div className="space-y-2">
            <p className="text-[11px] text-weave-700">
              Extracted {extracted.length} row
              {extracted.length === 1 ? "" : "s"}
              {extractConfidence
                ? ` · confidence: ${extractConfidence}`
                : ""}
              . {extractNote ?? ""}
            </p>
            <div className="overflow-x-auto rounded border border-weave-100 bg-white">
              <table className="w-full text-[11px] min-w-[520px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                    <th className="px-2 py-1.5">Ticker</th>
                    <th className="px-2 py-1.5">Side</th>
                    <th className="px-2 py-1.5 text-right">Entry</th>
                    <th className="px-2 py-1.5 text-right">Exit</th>
                    <th className="px-2 py-1.5 text-right">Qty</th>
                    <th className="px-2 py-1.5">Opened</th>
                    <th className="px-2 py-1.5">Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {extracted.slice(0, 10).map((r, i) => (
                    <tr
                      key={i}
                      className="border-b border-weave-50 last:border-0 font-mono"
                    >
                      <td className="px-2 py-1.5 font-medium text-weave-800">
                        {String(r.ticker ?? "")}
                      </td>
                      <td className="px-2 py-1.5">
                        {String(r.side ?? "long")}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {String(r.entry_price ?? "")}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {String(r.exit_price ?? "")}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {String(r.quantity ?? "")}
                      </td>
                      <td className="px-2 py-1.5">
                        {String(r.opened_at ?? "")}
                      </td>
                      <td className="px-2 py-1.5">
                        {String(r.closed_at ?? "")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {extracted.length > 10 ? (
                <p className="px-2 py-1.5 text-[10px] text-weave-500">
                  …showing first 10 of {extracted.length}.
                </p>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={importExtracted}
                disabled={busy}
                className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-50"
              >
                {busy ? "Saving..." : `Import ${extracted.length} rows`}
              </button>
              <button
                type="button"
                onClick={() => setExtracted(null)}
                className="text-[11px] text-weave-500 hover:text-weave-700"
              >
                Discard
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {/* CSV paste */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-weave-700">
          Or paste a CSV
        </label>
        <textarea
          value={csvText}
          onChange={(e) => setCsvText(e.target.value)}
          rows={6}
          placeholder={`ticker,side,strategy,entry_price,exit_price,quantity,opened_at,closed_at,notes
AAPL,long,swing,180.25,192.10,50,2026-04-15,2026-04-22,channel breakout
TSLA,short,scalp,265.00,261.40,20,2026-04-18,2026-04-18,opening drop`}
          className="w-full rounded border border-weave-200 px-2 py-1.5 text-xs font-mono"
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={importCsv}
            disabled={busy || !csvText.trim()}
            className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-50"
          >
            {busy ? "Importing..." : "Import CSV"}
          </button>
          <span className="text-[11px] text-weave-500">
            Required: ticker, entry_price, exit_price. Max 500 rows per
            import.
          </span>
        </div>
      </div>

      {/* Single trade */}
      <details className="text-xs">
        <summary className="cursor-pointer text-weave-600 hover:text-weave-800">
          Or log a single trade
        </summary>
        <div className="grid sm:grid-cols-3 gap-2 mt-2">
          <Field label="Ticker">
            <input
              type="text"
              value={singleTicker}
              onChange={(e) => setSingleTicker(e.target.value.toUpperCase())}
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Side">
            <select
              value={singleSide}
              onChange={(e) =>
                setSingleSide(e.target.value as "long" | "short")
              }
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm"
            >
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </Field>
          <Field label="Strategy">
            <input
              type="text"
              value={singleStrategy}
              onChange={(e) => setSingleStrategy(e.target.value)}
              placeholder="swing, scalp, earnings..."
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="Entry">
            <input
              type="number"
              step="0.01"
              value={singleEntry}
              onChange={(e) => setSingleEntry(e.target.value)}
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Exit">
            <input
              type="number"
              step="0.01"
              value={singleExit}
              onChange={(e) => setSingleExit(e.target.value)}
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Qty">
            <input
              type="number"
              step="1"
              value={singleQty}
              onChange={(e) => setSingleQty(e.target.value)}
              placeholder="1"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Opened">
            <input
              type="date"
              value={singleOpened}
              onChange={(e) => setSingleOpened(e.target.value)}
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Closed">
            <input
              type="date"
              value={singleClosed}
              onChange={(e) => setSingleClosed(e.target.value)}
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm font-mono"
            />
          </Field>
          <Field label="Notes">
            <input
              type="text"
              value={singleNotes}
              onChange={(e) => setSingleNotes(e.target.value)}
              placeholder="optional"
              className="w-full rounded border border-weave-200 px-2 py-1.5 text-sm"
            />
          </Field>
        </div>
        <button
          type="button"
          onClick={addSingle}
          disabled={busy}
          className="mt-3 rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-50"
        >
          {busy ? "Saving..." : "Log this trade"}
        </button>
      </details>

      {result && (
        <div
          className={
            "rounded-lg border px-3 py-2 text-xs leading-relaxed " +
            (result.ok
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-red-200 bg-red-50 text-red-900")
          }
        >
          {result.ok
            ? `Saved ${result.inserted} row${
                result.inserted === 1 ? "" : "s"
              }${
                result.skipped
                  ? `, skipped ${result.skipped} with errors`
                  : ""
              }. Reload the page to see the Learning Insights panel update.`
            : result.error ?? "Import failed."}
          {result.errors && result.errors.length > 0 ? (
            <ul className="mt-1 list-disc list-inside">
              {result.errors.slice(0, 5).map((e, i) => (
                <li key={i}>
                  Row {e.index + 1}: {e.reason}
                </li>
              ))}
              {result.errors.length > 5 ? (
                <li>… and {result.errors.length - 5} more</li>
              ) : null}
            </ul>
          ) : null}
        </div>
      )}
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="block text-[10px] uppercase tracking-widest text-weave-500">
        {label}
      </span>
      {children}
    </label>
  );
}
