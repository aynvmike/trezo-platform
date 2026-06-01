// Budget Mirror — CSV parsing + spending analysis.
//
// Phase 11a. Pure, client-side functions: parse an uploaded transaction
// CSV, detect its columns, categorise each merchant, and aggregate the
// spending. Nothing here stores or transmits the data — the uploaded
// file is read in the browser and lives only for the page session.

export type Txn = {
  date: string; // ISO yyyy-mm-dd
  amount: number; // dollars, positive = money spent
  merchant: string;
  category: string;
};

export type MerchantStat = { merchant: string; total: number; count: number };
export type CategoryStat = { category: string; total: number; count: number };
export type MonthStat = { month: string; total: number; count: number };

export type BudgetAnalysis = {
  txnCount: number;
  total: number;
  average: number;
  thisMonth: number;
  thisQuarter: number;
  ytd: number;
  perMonthAvg: number;
  monthsCovered: number;
  byCategory: CategoryStat[];
  byMonth: MonthStat[];
  topMerchants: MerchantStat[];
  firstDate: string | null;
  lastDate: string | null;
};

// --- CSV parsing -----------------------------------------------------------

function parseCSVLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      out.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out;
}

export function parseCSV(text: string): Record<string, string>[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) return [];
  const headers = parseCSVLine(lines[0]).map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const cells = parseCSVLine(line);
    const row: Record<string, string> = {};
    headers.forEach((h, i) => {
      row[h] = (cells[i] ?? "").trim();
    });
    return row;
  });
}

// --- Column detection ------------------------------------------------------

const DATE_HINTS = ["date", "time", "day", "when", "timestamp", "created"];
const AMOUNT_HINTS = [
  "amount", "total", "price", "fare", "cost", "charge", "value", "spent",
  "debit", "transaction amount"
];
const MERCHANT_HINTS = [
  "merchant", "description", "name", "restaurant", "store", "vendor",
  "payee", "details", "memo", "item"
];

function pickColumn(headers: string[], hints: string[]): string | null {
  const lower = headers.map((h) => h.toLowerCase());
  for (const hint of hints) {
    const idx = lower.findIndex((h) => h.includes(hint));
    if (idx >= 0) return headers[idx];
  }
  return null;
}

export function detectColumns(headers: string[]): {
  date: string | null;
  amount: string | null;
  merchant: string | null;
} {
  return {
    date: pickColumn(headers, DATE_HINTS),
    amount: pickColumn(headers, AMOUNT_HINTS),
    merchant: pickColumn(headers, MERCHANT_HINTS)
  };
}

// --- Categorisation --------------------------------------------------------

const CATEGORY_RULES: { category: string; keywords: string[] }[] = [
  // Food delivery is checked before Rideshare so "uber eats" is not
  // mistaken for an Uber ride.
  {
    category: "Food delivery",
    keywords: [
      "uber eats", "ubereats", "doordash", "door dash", "grubhub",
      "postmates", "seamless", "caviar", "instacart", "gopuff", "delivery"
    ]
  },
  { category: "Rideshare", keywords: ["uber", "lyft"] },
  {
    category: "Groceries",
    keywords: [
      "kroger", "safeway", "whole foods", "aldi", "trader joe", "publix",
      "wegmans", "grocery", "supermarket"
    ]
  },
  {
    category: "Shopping",
    keywords: ["amazon", "ebay", "etsy", "walmart", "target", "best buy"]
  },
  {
    category: "Subscriptions",
    keywords: ["netflix", "spotify", "hulu", "disney", "prime", "apple.com"]
  },
  {
    category: "Dining",
    keywords: [
      "restaurant", "cafe", "coffee", "starbucks", "mcdonald", "chipotle",
      "pizza", "grill", "kitchen", "bar "
    ]
  }
];

export function categorize(merchant: string): string {
  const m = (merchant || "").toLowerCase();
  for (const rule of CATEGORY_RULES) {
    if (rule.keywords.some((k) => m.includes(k))) return rule.category;
  }
  return "Other";
}

// --- Value parsing ---------------------------------------------------------

function parseAmount(raw: string): number {
  if (!raw) return 0;
  let s = raw.trim();
  const negative = s.startsWith("(") && s.endsWith(")");
  s = s.replace(/[(),$\s]/g, "").replace(/[A-Za-z]/g, "");
  const n = parseFloat(s);
  if (!Number.isFinite(n)) return 0;
  // A spending analyzer counts money out — use the magnitude.
  return Math.abs(n) * (negative ? 1 : 1);
}

function parseDate(raw: string): string | null {
  if (!raw) return null;
  const d = new Date(raw.trim());
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString().slice(0, 10);
}

// --- Build transactions ----------------------------------------------------

export function toTransactions(
  rows: Record<string, string>[],
  cols: { date: string | null; amount: string | null; merchant: string | null }
): Txn[] {
  if (!cols.amount) return [];
  const out: Txn[] = [];
  for (const row of rows) {
    const amount = parseAmount(row[cols.amount] ?? "");
    if (amount <= 0) continue;
    const date = cols.date ? parseDate(row[cols.date] ?? "") : null;
    const merchant = (cols.merchant ? row[cols.merchant] : "") || "Unknown";
    out.push({
      date: date ?? "",
      amount,
      merchant: merchant.trim(),
      category: categorize(merchant)
    });
  }
  return out;
}

// --- Aggregation -----------------------------------------------------------

export function analyze(txns: Txn[]): BudgetAnalysis {
  const dated = txns.filter((t) => t.date);
  const now = new Date();
  const thisMonthKey = now.toISOString().slice(0, 7);
  const thisYear = now.getFullYear();
  const thisQuarter = Math.floor(now.getMonth() / 3);

  let total = 0;
  let thisMonth = 0;
  let thisQuarterTotal = 0;
  let ytd = 0;
  const cat = new Map<string, { total: number; count: number }>();
  const mon = new Map<string, { total: number; count: number }>();
  const mer = new Map<string, { total: number; count: number }>();

  for (const t of txns) {
    total += t.amount;
    const c = cat.get(t.category) ?? { total: 0, count: 0 };
    c.total += t.amount;
    c.count += 1;
    cat.set(t.category, c);
    const key = t.merchant || "Unknown";
    const mm = mer.get(key) ?? { total: 0, count: 0 };
    mm.total += t.amount;
    mm.count += 1;
    mer.set(key, mm);

    if (t.date) {
      const monthKey = t.date.slice(0, 7);
      const m = mon.get(monthKey) ?? { total: 0, count: 0 };
      m.total += t.amount;
      m.count += 1;
      mon.set(monthKey, m);
      const d = new Date(t.date);
      if (monthKey === thisMonthKey) thisMonth += t.amount;
      if (d.getFullYear() === thisYear) {
        ytd += t.amount;
        if (Math.floor(d.getMonth() / 3) === thisQuarter) {
          thisQuarterTotal += t.amount;
        }
      }
    }
  }

  const byMonth: MonthStat[] = [...mon.entries()]
    .map(([month, v]) => ({ month, total: round2(v.total), count: v.count }))
    .sort((a, b) => a.month.localeCompare(b.month));
  const byCategory: CategoryStat[] = [...cat.entries()]
    .map(([category, v]) => ({ category, total: round2(v.total), count: v.count }))
    .sort((a, b) => b.total - a.total);
  const topMerchants: MerchantStat[] = [...mer.entries()]
    .map(([merchant, v]) => ({ merchant, total: round2(v.total), count: v.count }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 12);

  const dates = dated.map((t) => t.date).sort();
  const monthsCovered = Math.max(1, byMonth.length);

  return {
    txnCount: txns.length,
    total: round2(total),
    average: round2(txns.length ? total / txns.length : 0),
    thisMonth: round2(thisMonth),
    thisQuarter: round2(thisQuarterTotal),
    ytd: round2(ytd),
    perMonthAvg: round2(total / monthsCovered),
    monthsCovered,
    byCategory,
    byMonth,
    topMerchants,
    firstDate: dates[0] ?? null,
    lastDate: dates[dates.length - 1] ?? null
  };
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** One-call convenience: CSV text -> analysis (or an error message). */
export function analyzeCSV(text: string): {
  analysis: BudgetAnalysis | null;
  error: string | null;
  columns: { date: string | null; amount: string | null; merchant: string | null };
} {
  const rows = parseCSV(text);
  if (rows.length === 0) {
    return {
      analysis: null,
      error: "That file has no readable rows. Export it as a CSV with a header row.",
      columns: { date: null, amount: null, merchant: null }
    };
  }
  const cols = detectColumns(Object.keys(rows[0]));
  if (!cols.amount) {
    return {
      analysis: null,
      error:
        "Could not find an amount column. The CSV needs a column like Amount, Total, Price, or Fare.",
      columns: cols
    };
  }
  const txns = toTransactions(rows, cols);
  if (txns.length === 0) {
    return {
      analysis: null,
      error: "No spending rows could be read from that file.",
      columns: cols
    };
  }
  return { analysis: analyze(txns), error: null, columns: cols };
}


/** Build one transaction from raw fields — used by manual entry and the
 *  AI receipt reader. Categorisation is applied from the merchant. */
export function makeTxn(date: string, merchant: string, amount: number): Txn {
  const m = (merchant || "").trim() || "Unknown";
  return {
    date: (date || "").slice(0, 10),
    amount: Math.abs(Number(amount) || 0),
    merchant: m,
    category: categorize(m)
  };
}

/** Parse a CSV export into transactions (the analysis input). */
export function csvToTransactions(text: string): {
  txns: Txn[];
  error: string | null;
} {
  const rows = parseCSV(text);
  if (rows.length === 0) {
    return {
      txns: [],
      error: "That file has no readable rows. Export it as a CSV with a header row."
    };
  }
  const cols = detectColumns(Object.keys(rows[0]));
  if (!cols.amount) {
    return {
      txns: [],
      error:
        "Could not find an amount column. The CSV needs a column like Amount, Total, Price, or Fare."
    };
  }
  const txns = toTransactions(rows, cols);
  if (txns.length === 0) {
    return { txns: [], error: "No spending rows could be read from that file." };
  }
  return { txns, error: null };
}
