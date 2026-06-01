import { createClient } from "@/lib/supabase/server";

type Row = {
  id: string;
  flow: string;
  status: string;
  amount_value: number;
  amount_currency: string;
  requested_execution_date: string;
  debtor_name: string;
  creditor_name: string;
  remittance_info_unstructured: string | null;
  end_to_end_id: string;
  uetr: string | null;
  local_instrument: string | null;
  service_level: string | null;
  created_at: string;
};

const FLOW_LABEL: Record<string, string> = {
  kindrip_contribution: "KINDRIP contribution",
  vault_deposit: "Vault deposit",
  vault_withdrawal: "Vault withdrawal",
  broker_funding: "Broker funding",
  profit_withdrawal: "Profit withdrawal",
  manual: "Manual",
};

const STATUS_TONE: Record<string, string> = {
  draft: "bg-weave-100 text-weave-700",
  queued: "bg-blue-100 text-blue-800",
  submitted: "bg-indigo-100 text-indigo-800",
  accepted: "bg-emerald-100 text-emerald-800",
  rejected: "bg-red-100 text-red-800",
  settled: "bg-emerald-200 text-emerald-900",
  returned: "bg-amber-100 text-amber-800",
  cancelled: "bg-weave-100 text-weave-500",
};

/**
 * PaymentInstructionsLedger — surfaces every ISO 20022-shaped money
 * movement Trezo has built. Today most rows sit in 'draft' state
 * because nothing actually wires yet; the ledger exists so the audit
 * trail builds before banking goes live.
 *
 * Renders nothing when empty.
 */
export async function PaymentInstructionsLedger() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const { data: rows } = await supabase
    .from("payment_instructions")
    .select(
      "id, flow, status, amount_value, amount_currency, requested_execution_date, debtor_name, creditor_name, remittance_info_unstructured, end_to_end_id, uetr, local_instrument, service_level, created_at"
    )
    .eq("user_id", user.id)
    .order("created_at", { ascending: false })
    .limit(25);

  const records = (rows ?? []) as Row[];
  if (records.length === 0) return null;

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
      <div>
        <h2 className="font-medium text-weave-800">
          Payment instructions ledger
        </h2>
        <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
          Every Trezo money movement is recorded as an ISO 20022
          pain.001 instruction. Today most rows sit in{" "}
          <span className="font-mono">draft</span> — the audit trail
          builds up before real banking goes live. Showing the last 25.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[760px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
              <th className="px-2 py-2">Flow</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2 text-right">Amount</th>
              <th className="px-2 py-2">Debtor → Creditor</th>
              <th className="px-2 py-2">Rail</th>
              <th className="px-2 py-2">Remittance</th>
              <th className="px-2 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.id} className="border-b border-weave-50 last:border-0">
                <td className="px-2 py-2 text-weave-700">
                  {FLOW_LABEL[r.flow] ?? r.flow}
                </td>
                <td className="px-2 py-2">
                  <span
                    className={`text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5 ${
                      STATUS_TONE[r.status] ?? "bg-weave-100 text-weave-700"
                    }`}
                  >
                    {r.status}
                  </span>
                </td>
                <td className="px-2 py-2 text-right font-mono">
                  {r.amount_value.toLocaleString(undefined, {
                    style: "currency",
                    currency: r.amount_currency || "USD",
                  })}
                </td>
                <td className="px-2 py-2 font-mono text-[11px]">
                  <span className="text-weave-700">{r.debtor_name}</span>
                  {" → "}
                  <span className="text-weave-800">{r.creditor_name}</span>
                </td>
                <td className="px-2 py-2 font-mono text-[11px] text-weave-600">
                  {[r.local_instrument, r.service_level]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </td>
                <td className="px-2 py-2 text-weave-600 truncate max-w-[220px]">
                  {r.remittance_info_unstructured ?? "—"}
                </td>
                <td className="px-2 py-2 text-[11px] text-weave-500 whitespace-nowrap">
                  {new Date(r.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-weave-500 italic">
        Each row carries a UETR (Unique End-to-end Transaction Reference)
        and pain.001 XML rendered on save. Future banking integration
        ships the XML to the bank and updates the status field.
      </p>
    </section>
  );
}
