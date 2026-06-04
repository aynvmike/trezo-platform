"use client";

import { useState } from "react";
import { useFormState, useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ExpertOverrides } from "@/components/dashboard/expert-overrides";
import { saveBotSettings, type BotFormState } from "./_actions";

type Settings = {
  tcs_threshold: number;
  max_open_positions: number;
  consecutive_loss_limit: number;
  risk_per_trade_pct: number;
  default_stop_pct: number;
  default_target_pct: number;
  pattern_enabled: boolean;
  stms_enabled: boolean;
  extended_enabled: boolean;
  crypto_enabled: boolean;
  autonomy_mode: string;
  account_posture: string;
  allocation_overrides: Record<string, number> | null;
  pattern_weights: Record<string, number> | null;
  risk_profile?: string;
  min_reward_risk?: number;
  switching_mode?: string;
  switching_advantage_pct?: number;
  wheel_auto_execute?: boolean;
  expert_mode_enabled?: boolean;
  terse_format_enabled?: boolean;
  auto_trade_enabled?: boolean;
  options_min_dte?: number;
  options_max_premium_delta?: number;
  options_min_iv_rank_scalp?: number;
  options_hopeful_allocation_cap_pct?: number;
} | null;

type RiskProfile = "conservative" | "balanced" | "aggressive" | "expert";

type ProfileSpec = {
  key: RiskProfile;
  label: string;
  blurb: string;
  stop: number;
  target: number;
  risk: number;
  rr: number;
};

const PROFILES: ProfileSpec[] = [
  { key: "conservative", label: "Conservative", blurb: "Tight stops, generous targets, 1% per trade. Strict 2:1 reward:risk floor.", stop: 0.02, target: 0.06, risk: 0.01, rr: 2.0 },
  { key: "balanced",     label: "Balanced",     blurb: "3% stop, 6% target, 2% per trade. 1.5:1 reward:risk floor - Trezo's default.", stop: 0.03, target: 0.06, risk: 0.02, rr: 1.5 },
  { key: "aggressive",   label: "Aggressive",   blurb: "5% stop, 5% target, 4% per trade. 1:1 floor - scalper-friendly setups allowed.", stop: 0.05, target: 0.05, risk: 0.04, rr: 1.0 },
  { key: "expert",       label: "Expert (raw)", blurb: "You set every slider yourself, including the R:R floor (down to 0.3). Audit-logged so the agent can't be blamed for your edits.", stop: 0.05, target: 0.10, risk: 0.02, rr: 1.5 }
];

const initialState: BotFormState = { ok: false };

function SaveButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending}>
      {pending ? "Saving..." : "Save settings"}
    </Button>
  );
}

function Slider({
  name, label, hint, min, max, step, defaultValue, format, onValueChange
}: {
  name: string; label: string; hint: string;
  min: number; max: number; step: number; defaultValue: number;
  format: (v: number) => string;
  onValueChange?: (v: number) => void;
}) {
  const [value, setValue] = useState(defaultValue);
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <label htmlFor={name} className="text-sm font-medium text-weave-700">{label}</label>
        <span className="font-mono text-sm text-weave-800">{format(value)}</span>
      </div>
      <input
        id={name} name={name} type="range"
        min={min} max={max} step={step} value={value}
        onChange={(e) => { const n = Number(e.target.value); setValue(n); onValueChange?.(n); }}
        className="w-full accent-weave-600"
      />
      <p className="text-xs text-weave-500 leading-relaxed">{hint}</p>
    </div>
  );
}

function FrictionMode({
  value, current, label, desc
}: {
  value: string; current: string; label: string; desc: string;
}) {
  const id = `friction_${value}`;
  const selected = current === value;
  return (
    <label
      htmlFor={id}
      className={cn(
        "block rounded-lg border p-3 cursor-pointer transition",
        selected ? "border-weave-500 bg-weave-50" : "border-weave-200 bg-white hover:bg-weave-50/40"
      )}
    >
      <input
        type="radio" id={id} name="switching_mode" value={value}
        defaultChecked={selected} className="sr-only"
      />
      <div className="flex items-baseline gap-2">
        <span className={cn("font-medium", selected ? "text-weave-900" : "text-weave-700")}>{label}</span>
        {selected && <span className="text-[10px] uppercase tracking-widest text-weave-500">selected</span>}
      </div>
      <p className="mt-1 text-xs text-weave-500 leading-relaxed">{desc}</p>
    </label>
  );
}

function Toggle({
  name, label, hint, defaultChecked, onCheckedChange
}: {
  name: string; label: string; hint: string; defaultChecked: boolean;
  onCheckedChange?: (v: boolean) => void;
}) {
  const [on, setOn] = useState(defaultChecked);
  return (
    <div className="flex items-start gap-4 py-3">
      <div className="flex-1">
        <p className="font-medium text-weave-800">{label}</p>
        <p className="text-sm text-weave-500 leading-relaxed">{hint}</p>
      </div>
      <input type="checkbox" name={name} checked={on} onChange={() => {}} className="sr-only" />
      <button
        type="button" role="switch" aria-checked={on}
        aria-label={`Toggle ${label}`}
        onClick={() => setOn((v) => { const next = !v; onCheckedChange?.(next); return next; })}
        className={cn("relative h-6 w-11 rounded-full transition shrink-0", on ? "bg-weave-600" : "bg-weave-200")}
      >
        <span className={cn(
          "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition",
          on ? "translate-x-5" : "translate-x-0"
        )} />
      </button>
    </div>
  );
}

function ModeSelect({
  name, value, options
}: {
  name: string; value: string; options: { value: string; label: string; hint: string }[];
}) {
  const [sel, setSel] = useState(value);
  const cols = options.length >= 4 ? "sm:grid-cols-4" : "sm:grid-cols-3";
  return (
    <div className={cn("grid grid-cols-1 gap-3", cols)}>
      {options.map((o) => (
        <label
          key={o.value}
          className={cn(
            "cursor-pointer rounded-xl border p-4 transition",
            sel === o.value ? "border-weave-400 bg-weave-50 ring-1 ring-weave-200" : "border-weave-100 bg-white hover:bg-weave-50"
          )}
        >
          <input type="radio" name={name} value={o.value} checked={sel === o.value} onChange={() => setSel(o.value)} className="sr-only" />
          <span className="block font-medium text-weave-800">{o.label}</span>
          <span className="mt-1 block text-xs text-weave-500 leading-relaxed">{o.hint}</span>
        </label>
      ))}
    </div>
  );
}

function WeightInput({ name, label, defaultValue }: { name: string; label: string; defaultValue: number }) {
  return (
    <label className="block space-y-1">
      <span className="block text-[11px] uppercase tracking-widest text-weave-500">{label}</span>
      <input
        type="number" name={name} min={0} max={30} step={1} defaultValue={defaultValue}
        className="w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm font-mono"
      />
    </label>
  );
}

function NumInput({
  name, label, hint, defaultValue, step = 1, min, max, suffix,
}: {
  name: string;
  label: string;
  hint?: string;
  defaultValue: number;
  step?: number;
  min?: number;
  max?: number;
  suffix?: string;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={name} className="text-xs font-medium text-weave-700">
        {label}
      </label>
      <div className="relative">
        <input
          id={name}
          name={name}
          type="number"
          step={step}
          min={min}
          max={max}
          defaultValue={defaultValue}
          className="w-full rounded-md border border-weave-200 bg-white px-3 py-1.5 text-sm font-mono"
        />
        {suffix ? (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-weave-400 text-[11px]">
            {suffix}
          </span>
        ) : null}
      </div>
      {hint ? (
        <p className="text-[11px] text-weave-500 leading-snug">{hint}</p>
      ) : null}
    </div>
  );
}

function AllocInput({ name, label, defaultValue }: { name: string; label: string; defaultValue?: number }) {
  return (
    <div className="space-y-1">
      <label htmlFor={name} className="text-sm font-medium text-weave-700">{label}</label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-weave-400 text-sm">$</span>
        <input
          id={name} name={name} type="number" min={0} step={100} defaultValue={defaultValue ?? ""}
          placeholder="AI decides"
          className="w-full rounded-md border border-weave-200 bg-white pl-7 pr-3 py-2 text-sm"
        />
      </div>
    </div>
  );
}

export function BotTuningForm({ initial, liveEquity }: { initial: Settings; liveEquity?: number | null }) {
  const [state, formAction] = useFormState(saveBotSettings, initialState);

  const s: NonNullable<Settings> = initial ?? {
    tcs_threshold: 700, max_open_positions: 3, consecutive_loss_limit: 3,
    risk_per_trade_pct: 0.05, default_stop_pct: 0.05, default_target_pct: 0.1,
    pattern_enabled: true, stms_enabled: true, extended_enabled: true, crypto_enabled: true,
    autonomy_mode: "guarded", account_posture: "auto",
    allocation_overrides: null, pattern_weights: null,
    risk_profile: "balanced", min_reward_risk: 1.5,
    switching_mode: "adaptive", switching_advantage_pct: 10
  };

  const initialProfile = (s.risk_profile as RiskProfile) ?? "balanced";
  const [profile, setProfile] = useState<RiskProfile>(initialProfile);
  const [stopPct, setStopPct] = useState<number>(s.default_stop_pct);
  const [targetPct, setTargetPct] = useState<number>(s.default_target_pct);
  const [riskPct, setRiskPct] = useState<number>(s.risk_per_trade_pct);
  const [minRR, setMinRR] = useState<number>(s.min_reward_risk ?? 1.5);
  const [presetVersion, setPresetVersion] = useState<number>(0);
  // Local mirror of the Expert Mode toggle so the per-stock pin +
  // disable panel appears immediately when flipped on, without
  // needing to save and reload first.
  const [expertVisible, setExpertVisible] = useState<boolean>(
    s.expert_mode_enabled ?? false
  );

  function applyPreset(p: RiskProfile) {
    const spec = PROFILES.find((x) => x.key === p)!;
    setProfile(p);
    if (p !== "expert") {
      setStopPct(spec.stop); setTargetPct(spec.target);
      setRiskPct(spec.risk); setMinRR(spec.rr);
    }
    setPresetVersion((v) => v + 1);
  }

  const isExpert = profile === "expert";
  const liveRR = stopPct > 0 ? Number((targetPct / stopPct).toFixed(2)) : 0;
  const rrPasses = liveRR >= minRR;

  return (
    <form action={formAction} className="space-y-10">
      <input type="hidden" name="risk_profile" value={profile} />
      <input type="hidden" name="min_reward_risk" value={String(minRR)} />

      {/* Auto-trade toggle - Mike 2026-06-01. The user-facing kill
          switch. Sits at the top because it's the single most
          important question: do you want the bot to actually act, or
          just watch and learn? */}
      <section>
        <h2 className="font-medium text-weave-800 mb-1">Auto-trade</h2>
        <p className="text-sm text-weave-500 mb-3 leading-relaxed">
          The bot&apos;s execution kill switch. When ON, approved
          signals route to the paper or live engine and trades happen.
          When OFF, signals still score, the Risk Manager still
          approves, and the learning loop still records what the bot
          would have done. Nothing actually trades. Flip OFF if you
          want pure learn-only mode.
        </p>
        <div className="rounded-xl border border-weave-100 bg-white px-4 divide-y divide-weave-50">
          <Toggle
            name="auto_trade_enabled"
            label="Let the bot place trades"
            hint="Default ON for paper. Flip OFF to watch the bot's signals + suggestions without any trades being placed. The post-mortem ledger still records would-have-done events so the learning loop keeps working."
            defaultChecked={s.auto_trade_enabled ?? true}
          />
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="font-medium text-weave-800">Risk profile</h2>
          <p className="text-xs text-weave-500 leading-relaxed mt-1">
            Pick a preset and the position-sizing sliders snap to sensible
            values for that style. Expert unlocks raw control - every
            change is audit-logged so the agent can&apos;t be blamed for
            edits you made yourself.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {PROFILES.map((p) => (
            <button
              key={p.key} type="button" onClick={() => applyPreset(p.key)}
              className={cn(
                "text-left rounded-lg border p-3 transition",
                profile === p.key ? "border-weave-500 bg-weave-50/60 ring-1 ring-weave-300" : "border-weave-200 bg-white hover:bg-weave-50"
              )}
            >
              <p className="font-medium text-weave-800 text-sm">{p.label}</p>
              <p className="text-[11px] text-weave-500 leading-relaxed mt-1">{p.blurb}</p>
              {p.key !== "expert" && (
                <p className="text-[10px] font-mono text-weave-400 mt-2">
                  stop {(p.stop * 100).toFixed(1)}% · target {(p.target * 100).toFixed(1)}% · risk {(p.risk * 100).toFixed(1)}% · R:R &ge; {p.rr}
                </p>
              )}
            </button>
          ))}
        </div>
        <div
          className={cn(
            "rounded-lg border px-3 py-2 text-xs flex items-baseline justify-between gap-3 flex-wrap",
            rrPasses ? "border-emerald-200 bg-emerald-50/60 text-emerald-900" : "border-red-200 bg-red-50/60 text-red-800"
          )}
        >
          <span>
            Current sliders: stop <span className="font-mono">{(stopPct * 100).toFixed(1)}%</span> · target <span className="font-mono">{(targetPct * 100).toFixed(1)}%</span> = <span className="font-mono">R:R {liveRR}</span>
          </span>
          <span className="font-medium">
            {rrPasses
              ? `Clears your ${minRR} floor - trades will reach sizing.`
              : `Below your ${minRR} floor - every signal will be rejected. Raise target, tighten stop, or pick a looser preset.`}
          </span>
        </div>
      </section>

      <section className="space-y-6">
        <h2 className="font-medium text-weave-800">Risk Manager</h2>
        <Slider name="tcs_threshold" label="Signal confidence threshold (TCS)" hint="The minimum Trade Confidence Score (0-1000) a signal needs before Risk Manager will approve it. Higher = fewer, stronger trades." min={300} max={1000} step={10} defaultValue={s.tcs_threshold} format={(v) => String(v)} />
        <Slider name="max_open_positions" label="Maximum open positions" hint="How many positions the bot may hold at once. Caps your exposure across all strategies." min={1} max={20} step={1} defaultValue={s.max_open_positions} format={(v) => String(v)} />
        <Slider name="consecutive_loss_limit" label="Losing-streak limit" hint="How many losing trades in a row before the bot pauses for the day. Conservative is around 3, aggressive around 7." min={2} max={10} step={1} defaultValue={s.consecutive_loss_limit} format={(v) => String(v)} />
      </section>

      <section className="space-y-6">
        <h2 className="font-medium text-weave-800">
          Position sizing
          {!isExpert && <span className="ml-2 text-[10px] font-normal uppercase tracking-widest text-weave-500">· driven by {profile} preset</span>}
        </h2>
        <Slider key={`risk-${presetVersion}`} name="risk_per_trade_pct" label="Risk per trade" hint="Share of buying power put at risk on each trade. If the stop is hit, this is roughly what you lose." min={0.005} max={0.25} step={0.005} defaultValue={riskPct} format={(v) => `${(v * 100).toFixed(1)}%`} onValueChange={setRiskPct} />
        <Slider key={`stop-${presetVersion}`} name="default_stop_pct" label="Default stop distance" hint="How far below entry the stop sits. Crypto modes override this with per-coin stops." min={0.01} max={0.5} step={0.005} defaultValue={stopPct} format={(v) => `${(v * 100).toFixed(1)}%`} onValueChange={setStopPct} />
        <Slider key={`target-${presetVersion}`} name="default_target_pct" label="Default profit target" hint="How far above entry the profit target sits. Must clear your R:R floor or sizing will reject every trade." min={0.01} max={1.0} step={0.01} defaultValue={targetPct} format={(v) => `${(v * 100).toFixed(0)}%`} onValueChange={setTargetPct} />

        {isExpert ? (
          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <label htmlFor="min_reward_risk_visible" className="text-sm font-medium text-weave-700">Reward-to-risk floor (Expert)</label>
              <span className="font-mono text-sm text-weave-800">{minRR.toFixed(1)} : 1</span>
            </div>
            <input
              id="min_reward_risk_visible" type="range"
              min={0.3} max={3.0} step={0.1} value={minRR}
              onChange={(e) => setMinRR(Number(e.target.value))}
              className="w-full accent-weave-600"
            />
            <p className="text-xs text-weave-500 leading-relaxed">
              Sizing rejects any trade whose target/stop ratio is below this floor. 0.3 = very loose. 3.0 = very strict.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-weave-100 bg-weave-50/40 p-3 text-xs text-weave-600">
            <span className="font-medium">Reward-to-risk floor:</span>{" "}
            <span className="font-mono">{minRR.toFixed(1)} : 1</span> - set by the{" "}
            <span className="capitalize">{profile}</span> preset. Switch to <span className="font-medium">Expert</span> above to override.
          </div>
        )}

        <SizingPreview stopPct={stopPct} targetPct={targetPct} riskPct={riskPct} minRR={minRR} liveEquity={liveEquity ?? null} />
      </section>

      {/* Switching friction (anti-whipsaw on per-stock strategy picks).
          Mike feedback 2026-05-29: when the TCS threshold is lowered to
          let more trades through, the Strategy Engine was flipping
          per-stock strategy picks on tiny score wiggles. Friction
          requires the challenger to beat the current pick by a
          configurable advantage before the bot will flip. */}
      <section>
        <h2 className="font-medium text-weave-800 mb-1">Strategy switching friction</h2>
        <p className="text-sm text-weave-500 mb-3 leading-relaxed">
          Anti-whipsaw control. When the Pattern Engine&apos;s per-stock
          best-fit changes, the new strategy has to beat the current one
          by a meaningful margin before the bot actually flips. Without
          this, a 5-point TCS bump can flip your pick every tick.
        </p>
        <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-4">
          <div>
            <label className="text-xs uppercase tracking-widest text-weave-500">Mode</label>
            <div className="mt-2 grid sm:grid-cols-2 gap-2">
              <FrictionMode value="off"      current={s.switching_mode ?? "adaptive"} label="Off"                    desc="Every tick can flip. Debug / backtest only." />
              <FrictionMode value="fixed"    current={s.switching_mode ?? "adaptive"} label="Fixed"                  desc="Challenger must beat current by the % below." />
              <FrictionMode value="adaptive" current={s.switching_mode ?? "adaptive"} label="Adaptive (Recommended)" desc="Threshold scales inversely with your TCS dial - lower TCS = bigger gap required. Math: base x (800 / current TCS)." />
              <FrictionMode value="tiered"   current={s.switching_mode ?? "adaptive"} label="Tiered"                 desc="Three bands keyed on the new pick's TCS: 700+ needs 5%, 500-699 needs 10%, under 500 needs 20%." />
            </div>
          </div>
          <div className="flex items-center gap-4">
            <label htmlFor="switching_advantage_pct" className="text-xs uppercase tracking-widest text-weave-500 shrink-0">Base advantage</label>
            <input
              id="switching_advantage_pct" type="number" name="switching_advantage_pct"
              min={0} max={50} step={1} defaultValue={s.switching_advantage_pct ?? 10}
              className="w-24 rounded border border-weave-200 px-2 py-1 text-sm font-mono"
            />
            <span className="text-sm text-weave-600">% - applies to Fixed and Adaptive modes. Tiered ignores it.</span>
          </div>
          <div className="text-[11px] text-weave-500 leading-relaxed border-t border-weave-50 pt-3">
            <p className="font-medium text-weave-700">How adaptive scales:</p>
            <p className="mt-1">base 10% x (800 / TCS) - at TCS 800 needs 10%, at TCS 700 needs 11.4%, at TCS 500 needs 16%, at TCS 400 needs 20%.</p>
            <p className="mt-1">
              Suppressed flips emit a &quot;strategy_held&quot; activity-feed event so you can see the friction working.
              The pick that&apos;s held keeps its TCS as the baseline for the next comparison.
            </p>
          </div>
        </div>
      </section>

      {/* Wheel automation — Mike 2026-05-30. When ON and Alpaca
          options approval >= 1, the Options Scanner auto-fires Wheel
          CSPs and CCs through the same path the manual Place button
          uses. Default OFF; only flip on after paper has proven the
          chain end-to-end. Kill-switch tie-in is automatic. */}
      <section>
        <h2 className="font-medium text-weave-800 mb-1">Wheel automation</h2>
        <p className="text-sm text-weave-500 mb-3 leading-relaxed">
          When on, the Options Scanner auto-fires Wheel cash-secured
          puts and covered calls instead of waiting for you to click
          Place on the Wheel page. Routes through the same Alpaca path
          as the manual button. Kill-switches (daily loss, consecutive
          losses, halted account) block auto-fires automatically.
        </p>
        <div className="rounded-xl border border-weave-100 bg-white px-4 divide-y divide-weave-50">
          <Toggle
            name="wheel_auto_execute"
            label="Auto-execute Wheel orders"
            hint="Bot fires CSPs and CCs through Alpaca on its own. Requires Alpaca options approval level 1+ — Mike has Level 3 paper. Off by default; flip on once paper has proven the chain."
            defaultChecked={s.wheel_auto_execute ?? false}
          />
        </div>
      </section>

      {/* Expert overrides - Mike Phase 13a follow-up (2026-05-30).
          The toggle below gates the per-stock pin + disable panel. The
          underlying overrides apply whether the toggle is on or off;
          the toggle just hides the advanced surface so casual users
          don't trip on it. */}
      <section>
        <h2 className="font-medium text-weave-800 mb-1">Expert mode</h2>
        <p className="text-sm text-weave-500 mb-3 leading-relaxed">
          Unlock the per-stock pin and disable list. Use this when you
          know better than the strategy selector — e.g. &ldquo;run STMS
          on AAPL no matter what&rdquo; or &ldquo;don&apos;t touch NVDA until earnings.&rdquo;
        </p>
        <div className="rounded-xl border border-weave-100 bg-white px-4 divide-y divide-weave-50">
          <Toggle
            name="expert_mode_enabled"
            label="Show Expert Overrides panel"
            hint="Reveals per-stock strategy pin + disable list below. The bot honors these whether the panel is visible or not."
            defaultChecked={s.expert_mode_enabled ?? false}
            onCheckedChange={setExpertVisible}
          />
          <Toggle
            name="terse_format_enabled"
            label="Terse trader format (compact view)"
            hint="Signal cards default to the 8-line trader format. Verbose body stays one tap away on every card. Mobile auto-defaults to compact regardless. Safe to flip on or off at any time."
            defaultChecked={s.terse_format_enabled ?? false}
          />
        </div>

        {/* Phase C+D follow-up: options Greek filters. These let Mike
            tune the Options Scanner's emit gates from the UI instead of
            editing agents/.env. Only visible in Expert mode. */}
        {expertVisible ? (
          <div className="mt-4 rounded-xl border border-weave-100 bg-white p-4 space-y-3">
            <div>
              <h3 className="text-sm font-medium text-weave-800">
                Options filters (Greek &amp; bucket caps)
              </h3>
              <p className="mt-1 text-xs text-weave-500 leading-relaxed">
                Per Mike&apos;s options-trading rules. DTE protects against theta
                burn. Delta cap keeps premium-sell setups from becoming stock
                proxies. IV minimum requires juicy premium for scalp plays. Hopeful
                cap limits non-Wheel directional bets to a small share of capital.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <NumInput
                name="options_min_dte"
                label="Minimum DTE"
                hint="Skip any options play within this many days of expiration. Mike's rule: avoid long calls inside 7 DTE unless setup explicitly accounts for theta. Default 7."
                step={1}
                min={0}
                max={90}
                defaultValue={s.options_min_dte ?? 7}
                suffix="days"
              />
              <NumInput
                name="options_max_premium_delta"
                label="Max |delta| for premium-sell"
                hint="Premium-sell setups (CSPs, spreads) whose absolute delta is above this are skipped — they're too close to short-stock proxies. Default 0.45."
                step={0.05}
                min={0}
                max={1}
                defaultValue={s.options_max_premium_delta ?? 0.45}
              />
              <NumInput
                name="options_min_iv_rank_scalp"
                label="Min IV rank for scalp"
                hint="Scalp/short-DTE setups require IV percentile above this to be worth the theta burn. Default 30%."
                step={1}
                min={0}
                max={100}
                defaultValue={s.options_min_iv_rank_scalp ?? 30}
                suffix="%"
              />
              <NumInput
                name="options_hopeful_allocation_cap_pct"
                label="Hopeful-holds allocation cap"
                hint="Cap on directional long calls / debit spreads outside the Wheel, as a fraction of total options capital. Mike's rule: 3%."
                step={0.01}
                min={0}
                max={1}
                defaultValue={s.options_hopeful_allocation_cap_pct ?? 0.03}
              />
            </div>
          </div>
        ) : null}

        {expertVisible ? (
          <div className="mt-4">
            <ExpertOverrides />
          </div>
        ) : null}
      </section>

      <section>
        <h2 className="font-medium text-weave-800 mb-1">Strategies</h2>
        <p className="text-sm text-weave-500 mb-2">
          Turn a whole strategy off and its scanner keeps running but emits no signals.
        </p>
        <div className="rounded-xl border border-weave-100 bg-white px-4 divide-y divide-weave-50">
          <Toggle name="pattern_enabled"  label="Pattern Detection"            hint="Candlestick-pattern scanning of your default watchlist." defaultChecked={s.pattern_enabled} />
          <Toggle name="stms_enabled"     label="STMS - Small Trades Momentum" hint="Small-cap momentum scanner, 7-11 AM ET." defaultChecked={s.stms_enabled} />
          <Toggle name="extended_enabled" label="Extended Strategy - Swing layer" hint="Multi-day swing scanner (Layer 4): EMA50 pullbacks, breakout holds, gap continuations, stair-steppers." defaultChecked={s.extended_enabled} />
          <Toggle name="crypto_enabled"   label="Crypto Bot"                   hint="24/7 SCALP / SWING / DCA scanning of XRP, ETH, SOL." defaultChecked={s.crypto_enabled} />
        </div>
      </section>

      <section>
        <h2 className="font-medium text-weave-800 mb-1">Capital allocation</h2>
        <p className="text-sm text-weave-500 mb-3">
          The posture sets how your account is split across market types. Leave it on Auto
          and the bot picks from your account size.
        </p>
        <ModeSelect
          name="account_posture" value={s.account_posture}
          options={[
            { value: "auto",     label: "Auto",     hint: "The AI picks the posture from your account size. Recommended." },
            { value: "growth",   label: "Growth",   hint: "Tilt capital to crypto and stocks; build the account up." },
            { value: "balanced", label: "Balanced", hint: "Spread capital evenly across growth and income layers." },
            { value: "income",   label: "Income",   hint: "Tilt to the Wheel and Dividends layers; preserve capital." }
          ]}
        />
        <p className="mt-4 text-sm text-weave-500 mb-2">
          Optional - pin a dollar budget for any market type. Leave a box blank to let the posture decide.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <AllocInput name="alloc_crypto"  label="Crypto"  defaultValue={s.allocation_overrides?.crypto} />
          <AllocInput name="alloc_stocks"  label="Stocks"  defaultValue={s.allocation_overrides?.stocks} />
          <AllocInput name="alloc_options" label="Options" defaultValue={s.allocation_overrides?.options} />
          <AllocInput name="alloc_income"  label="Income"  defaultValue={s.allocation_overrides?.income} />
        </div>
      </section>

      <section>
        <h2 className="font-medium text-weave-800 mb-1">Pattern factor weights</h2>
        <p className="text-sm text-weave-500 mb-3">
          The Pattern Engine score blends 10 factors. By default each factor is worth 8-12 points (sum 100).
          Tilt these to lean into what you trust - set a factor to 0 to ignore it.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <WeightInput name="pw_trend"            label="Trend"          defaultValue={s.pattern_weights?.trend            ?? 12} />
          <WeightInput name="pw_momentum"         label="Momentum"       defaultValue={s.pattern_weights?.momentum         ?? 10} />
          <WeightInput name="pw_macd"             label="MACD"           defaultValue={s.pattern_weights?.macd             ?? 12} />
          <WeightInput name="pw_volume"           label="Volume"         defaultValue={s.pattern_weights?.volume           ?? 10} />
          <WeightInput name="pw_breakout"         label="Breakout"       defaultValue={s.pattern_weights?.breakout         ?? 12} />
          <WeightInput name="pw_candle_pattern"   label="Candle pattern" defaultValue={s.pattern_weights?.candle_pattern   ?? 10} />
          <WeightInput name="pw_bb_position"      label="Bollinger"      defaultValue={s.pattern_weights?.bb_position      ??  8} />
          <WeightInput name="pw_vwap_alignment"   label="VWAP"           defaultValue={s.pattern_weights?.vwap_alignment   ??  8} />
          <WeightInput name="pw_market_alignment" label="Market (SPY)"   defaultValue={s.pattern_weights?.market_alignment ??  8} />
          <WeightInput name="pw_iv_environment"   label="IV environment" defaultValue={s.pattern_weights?.iv_environment   ?? 10} />
        </div>
        <p className="mt-3 text-xs text-weave-500">
          Leaving these at default keeps the fair-weighted score - that is the recommendation.
        </p>
      </section>

      <section>
        <h2 className="font-medium text-weave-800 mb-1">Adaptive Scope autonomy</h2>
        <p className="text-sm text-weave-500 mb-3">
          When breaking news or a market-regime shift hits, how much may the bot adjust strategy scope on its own?
        </p>
        <ModeSelect
          name="autonomy_mode" value={s.autonomy_mode}
          options={[
            { value: "suggest", label: "Suggest only", hint: "The bot recommends changes; nothing takes effect until you approve it." },
            { value: "guarded", label: "Guarded auto", hint: "The bot applies risk-reducing changes on its own, within hard limits." },
            { value: "full",    label: "Full auto",    hint: "The bot also acts on smaller signals and adjusts more freely." }
          ]}
        />
      </section>

      {state.message && (
        <p className={state.ok ? "text-sm text-emerald-700" : "text-sm text-red-600"}>{state.message}</p>
      )}

      <div className="flex justify-end">
        <SaveButton />
      </div>
    </form>
  );
}

function SizingPreview({
  stopPct, targetPct, riskPct, minRR, liveEquity
}: {
  stopPct: number; targetPct: number; riskPct: number; minRR: number;
  liveEquity?: number | null;
}) {
  const SAMPLES: { ticker: string; price: number; name: string }[] = [
    { ticker: "AAPL", price: 222, name: "Apple - mega cap" },
    { ticker: "MSFT", price: 415, name: "Microsoft - high price" },
    { ticker: "SPY",  price: 568, name: "S&P 500 ETF" },
    { ticker: "INTC", price: 118, name: "Intel - mid price" },
    { ticker: "F",    price: 16,  name: "Ford - low price" }
  ];
  const EQUITIES: number[] = liveEquity && liveEquity > 0
    ? [Math.round(liveEquity), 25_000, 100_000]
    : [5_000, 25_000, 100_000];
  const EQUITY_LABELS: string[] = liveEquity && liveEquity > 0
    ? [`Your $${(liveEquity / 1000).toFixed(1)}k (live)`, "$25k account", "$100k account"]
    : ["$5k account", "$25k account", "$100k account"];
  const liveRR = stopPct > 0 ? Number((targetPct / stopPct).toFixed(2)) : 0;
  const rrPasses = liveRR >= minRR;

  return (
    <div className="rounded-lg border border-weave-200 bg-white p-3 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="text-sm font-medium text-weave-800">Sizing preview · what these sliders actually trade</h3>
        <span className={cn(
          "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
          rrPasses ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-700"
        )}>
          R:R {liveRR} (floor {minRR})
        </span>
      </div>
      <p className="text-[11px] text-weave-500 leading-relaxed">
        For each sample ticker at three account sizes, here&apos;s exactly what a trade would size to with your current sliders.
        If R:R is below your floor, EVERY trade gets rejected at sizing regardless of these numbers.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
              <th className="px-2 py-1.5">Ticker</th>
              <th className="px-2 py-1.5 text-right">Stop $</th>
              {EQUITIES.map((e, i) => (
                <th key={e} className="px-2 py-1.5 text-right">{EQUITY_LABELS[i]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SAMPLES.map((s) => {
              const stopDistance = s.price * stopPct;
              return (
                <tr key={s.ticker}>
                  <td className="px-2 py-1.5 font-mono text-weave-700">{s.ticker}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-weave-700">${(stopDistance).toFixed(2)}</td>
                  {EQUITIES.map((e) => {
                    const riskUsd = e * riskPct;
                    const qty = Math.floor(riskUsd / stopDistance);
                    const notional = qty * s.price;
                    const passes = qty >= 1 && rrPasses;
                    return (
                      <td key={e} className={cn(
                        "px-2 py-1.5 text-right font-mono",
                        passes ? "text-weave-700" : "text-red-700"
                      )}>
                        {qty >= 1 ? (
                          <>
                            {qty} sh · ${notional.toFixed(0)}
                            <span className="text-weave-400 ml-1">(${riskUsd.toFixed(0)} risk)</span>
                          </>
                        ) : (
                          <span className="italic">0 shares - too small</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-weave-500 leading-relaxed">
        Math: risk_$ = equity x risk%. shares = risk_$ / (price x stop%).
        A red row means the math wants under 1 share at that equity OR your R:R floor blocks it.
      </p>
    </div>
  );
}
