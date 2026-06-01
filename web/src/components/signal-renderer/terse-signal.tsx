import type { TerseFields } from "./to-terse-fields";

/**
 * Pure renderer of the 8-line trader format. No state, no logic.
 * The wrapper (SignalCard) decides when to render this vs the
 * verbose body and how to recover when this throws.
 */
export function TerseSignal({ fields }: { fields: TerseFields }) {
  const Line = ({ k, v }: { k: string; v: React.ReactNode }) => (
    <div className="flex items-baseline gap-2 text-xs">
      <span className="text-weave-500 w-28 shrink-0">{k}</span>
      <span className="font-mono text-weave-800">{v}</span>
    </div>
  );

  return (
    <div className="space-y-0.5 font-mono">
      <Line k="Ticker" v={fields.ticker} />
      <Line k="Bias" v={fields.bias} />
      <Line k="Trade Type" v={fields.trade_type} />
      <Line k="Strike & Exp" v={fields.strike_expiration} />
      <Line k="Entry Range" v={fields.entry_range} />
      <Line k="Exit / Stop" v={fields.exit_target_stop} />
      <Line
        k="Confidence"
        v={fields.confidence !== null ? `${fields.confidence} / 10` : "—"}
      />
      {fields.reasoning ? (
        <div className="pt-1 text-[11px] text-weave-700 leading-relaxed font-sans">
          {fields.reasoning}
        </div>
      ) : null}
    </div>
  );
}
