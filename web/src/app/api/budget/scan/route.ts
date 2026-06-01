import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const MODEL = "claude-haiku-4-5-20251001";
const MAX_BYTES = 8 * 1024 * 1024; // 8 MB cap

/**
 * POST /api/budget/scan  (multipart form, field "file")
 * Sends a receipt / statement image or PDF to Claude, which extracts the
 * transactions. The file is used for this one read and not stored. CSV
 * and manual entry never reach this route — they stay in the browser.
 */
export async function POST(request: Request) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }

  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) {
    return NextResponse.json(
      {
        error:
          "Receipt reading needs an Anthropic API key in web/.env.local (ANTHROPIC_API_KEY). CSV and manual entry still work without it."
      },
      { status: 200 }
    );
  }

  let file: File | null = null;
  try {
    const form = await request.formData();
    const f = form.get("file");
    if (f instanceof File) file = f;
  } catch {
    file = null;
  }
  if (!file) {
    return NextResponse.json({ error: "No file received." }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json(
      { error: "That file is too large — keep it under 8 MB." },
      { status: 200 }
    );
  }

  const mime = file.type || "image/jpeg";
  const isPdf = mime.includes("pdf");
  const b64 = Buffer.from(await file.arrayBuffer()).toString("base64");

  const instruction =
    "You are reading a financial document — a receipt, an order confirmation, " +
    "or a statement. Extract every individual purchase or transaction you can " +
    'see. Reply with ONLY a JSON array, no other text: ' +
    '[{"date":"YYYY-MM-DD or empty string","merchant":"name","amount":number}]. ' +
    "Amount is the dollar total of that line as a positive number. If there is " +
    "a single overall total and no line items, return one object for it.";

  const source = isPdf
    ? { type: "base64", media_type: "application/pdf", data: b64 }
    : { type: "base64", media_type: mime, data: b64 };
  const block = isPdf
    ? { type: "document", source }
    : { type: "image", source };

  let transactions: { date: string; merchant: string; amount: number }[] = [];
  try {
    const r = await fetch(ANTHROPIC_URL, {
      method: "POST",
      headers: {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 2000,
        messages: [
          { role: "user", content: [block, { type: "text", text: instruction }] }
        ]
      }),
      signal: AbortSignal.timeout(45_000)
    });
    if (!r.ok) {
      return NextResponse.json(
        { error: `The reader could not process that file (${r.status}).` },
        { status: 200 }
      );
    }
    const data = await r.json();
    const text = (data.content ?? [])
      .filter((b: { type?: string }) => b?.type === "text")
      .map((b: { text?: string }) => b.text ?? "")
      .join("");
    const start = text.indexOf("[");
    const end = text.lastIndexOf("]");
    if (start >= 0 && end > start) {
      const parsed = JSON.parse(text.slice(start, end + 1));
      if (Array.isArray(parsed)) {
        transactions = parsed
          .filter((t) => t && Number(t.amount) > 0)
          .map((t) => ({
            date: String(t.date ?? "").slice(0, 10),
            merchant: String(t.merchant ?? "Unknown").slice(0, 80),
            amount: Math.abs(Number(t.amount) || 0)
          }));
      }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Reader unavailable";
    return NextResponse.json({ error: msg }, { status: 200 });
  }

  if (transactions.length === 0) {
    return NextResponse.json(
      { error: "No transactions could be read from that file.", transactions: [] },
      { status: 200 }
    );
  }
  return NextResponse.json({ transactions, error: null });
}
