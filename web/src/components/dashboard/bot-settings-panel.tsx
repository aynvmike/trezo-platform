import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

// Shape of the bot_settings row matching the .select() below. Used to
// cast the Supabase response (its type inference returns a union that
// includes GenericStringError otherwise). 2026-06-03 cleanup.
type BotSettingsRow = {
  tcs_threshold: number | null;
  max_open_positions: number | null;
  consecutive_loss_limit: number | null;
  risk_per_trade_pct: number | null;
  default_stop_pct: number | null;
  default_target_pct: number | null;
  pattern_enabled: boolean | null;
  stms_enabled: boolean | null;
  extended_enabled: boolean | null;
  crypto_enabled: boolean | null;
  autonomy_mode: string | null;
  account_posture: string | null;
  pattern_weights: Record<string, number> | null;
  updated_at: string | null;
};

/**
 * Bot settings · in force panel.
 *
 * Mike's friction: "I changed settings but the bot does not seem to
 * use them." Two possible causes — (1) the save failed; (2) the
 * agents settings cache is stale (TTL 30s). This widget makes the
 * first one impossible to misdiagnose: it shows the values currently
 * persisted in the DB for this user. If the page shows what you set,
 * the save worked; the agent picks them up within ~30 seconds.
 */
export async function BotSettingsPanel({ userId }: { userId: string }) {
  const supabase = createClient();
  const { data: sRaw } = await supabase
    .from("bot_settings")
    .select(
      "tcs_threshold, max_open_positions, consecutive_loss_limit, " +
        "risk_per_trade_pct, default_stop_pct, default_target_pct, " +
        "pattern_enabled, stms_enabled, extended_enabled, crypto_enabled, " +
        "autonomy_mode, account_posture, pattern_weights, updated_at"
    )
    .eq("user_id", userId)
    .maybeSingle();
  const s = sRaw as BotSettingsRow | null;

  if (!s) {
    return (
      <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-600">
        No bot settings row yet — open <span className="font-medium">Bot Tuning</span> and save once to seed it.
      </div>
    );
  }

  const updated = s.updated_at
    ? new Date(s.updated_at as string).toLocaleString()
    : "never";
  const pwTilted =
    !!s.pattern_weights &&
    Object.keys((s.pattern_weights as Record<string, number>) ?? {}).length > 0;

  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Bot settings · in force
          </h2>
          <p className="text-xs text-weave-500">
            Saved values the agents are using. Updated {updated}.
            Changes apply within ~30 seconds of saving in Bot Tuning.
          </p>
        </div>
        <a
          href="/dashboard/settings/bot"
          className="text-xs text-weave-600 hover:underline"
        >
          Edit in Bot Tuning →
        </a>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Tile label="Signal TCS" value={String(s.tcs_threshold ?? 700)} />
        <Tile
          label="Risk / trade"
          value={`${((Number(s.risk_per_trade_pct ?? 0.05)) * 100).toFixed(2)}%`}
        />
        <Tile
          label="Stop %"
          value={`${(Number(s.default_stop_pct ?? 0.05) * 100).toFixed(1)}%`}
        />
        <Tile
          label="Target %"
          value={`${(Number(s.default_target_pct ?? 0.10) * 100).toFixed(1)}%`}
        />
        <Tile label="Max open positions" value={String(s.max_open_positions ?? 3)} />
        <Tile
          label="Streak loss limit"
          value={String(s.consecutive_loss_limit ?? 3)}
        />
        <Tile label="Autonomy" value={String(s.autonomy_mode ?? "guarded")} />
        <Tile label="Posture" value={String(s.account_posture ?? "auto")} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Pill label="Pattern" on={!!s.pattern_enabled} />
        <Pill label="Stock Bot" on={!!s.stms_enabled} />
        <Pill label="Extended" on={!!s.extended_enabled} />
        <Pill label="Crypto" on={!!s.crypto_enabled} />
      </div>

      <p className="beginner-only text-xs text-weave-500 leading-relaxed">
        If a value here does not match what you set on Bot Tuning, the
        save failed — try again. If it matches but the bot does not seem
        to act on it, wait one tick (the scanner reads settings every 30s)
        and check the Scanner pulse above.{" "}
        {pwTilted ? "Pattern factor weights are tilted from defaults." : "Pattern factor weights are at defaults."}
      </p>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-weave-100 bg-weave-50/40 p-3">
      <p className="text-[10px] uppercase tracking-widest text-weave-500">
        {label}
      </p>
      <p className="mt-1 font-mono text-sm font-medium text-weave-800">
        {value}
      </p>
    </div>
  );
}

function Pill({ label, on }: { label: string; on: boolean }) {
  return (
    <span
      className={cn(
        "rounded-full px-3 py-1 text-[11px] font-medium flex items-center justify-between gap-2",
        on
          ? "bg-emerald-100 text-emerald-800"
          : "bg-weave-100 text-weave-500"
      )}
    >
      <span>{label}</span>
      <span className="font-mono text-[10px]">{on ? "ON" : "OFF"}</span>
    </span>
  );
}
