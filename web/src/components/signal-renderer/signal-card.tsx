"use client";

import { useEffect, useState } from "react";
import { toTerseFields, type TerseFields } from "./to-terse-fields";
import { TerseSignal } from "./terse-signal";
import { SignalErrorBoundary } from "./error-boundary";

/**
 * SignalCard - smart wrapper that owns the four-layer safety:
 *
 *   1. Try-catch fall-back. If toTerseFields() or TerseSignal throws,
 *      we silently render the verbose body (children). The user sees
 *      a working card, never a broken one.
 *
 *   2. Per-user toggle. `defaultTerse` is wired from
 *      bot_settings.terse_format_enabled by the page. When false,
 *      verbose is shown unless the user flips this card.
 *
 *   3. Platform kill switch. `killed` is set by the page from the
 *      TREZO_TERSE_MODE_DISABLED env var. When true, the toggle
 *      button is hidden and verbose is forced - the feature is gone
 *      from the platform until env is changed.
 *
 *   4. Per-card flip. The compact icon button in the corner flips
 *      THIS card only. Independent of user / platform settings.
 *
 * The verbose body is mounted as React children so existing card
 * rendering keeps working untouched - SignalCard wraps it.
 */
export function SignalCard({
  payload,
  children,
  defaultTerse = false,
  killed = false,
}: {
  payload: Record<string, unknown>;
  children: React.ReactNode;
  defaultTerse?: boolean;
  killed?: boolean;
}) {
  const [mobileCompact, setMobileCompact] = useState(false);
  const [cardTerse, setCardTerse] = useState<boolean | null>(null);
  const [renderFailed, setRenderFailed] = useState(false);

  // Mobile viewport auto-defaults to compact.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(max-width: 640px)");
    const handler = () => setMobileCompact(mq.matches);
    handler();
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Effective state precedence: kill switch > per-card > user default > mobile.
  const wantsTerse = killed
    ? false
    : cardTerse !== null
    ? cardTerse
    : defaultTerse || mobileCompact;

  // Build terse fields once, wrap in try-catch (layer 1).
  let fields: TerseFields | null = null;
  if (wantsTerse && !renderFailed) {
    try {
      fields = toTerseFields(payload);
    } catch (e) {
      if (process.env.NODE_ENV !== "production") {
        console.warn("[SignalCard] terse render failed, falling back:", e);
      }
      fields = null;
    }
  }

  const showTerse = wantsTerse && fields !== null && !renderFailed;

  return (
    <div className="relative">
      {!killed ? (
        <button
          type="button"
          onClick={() =>
            setCardTerse((v) => (v === null ? !wantsTerse : !v))
          }
          aria-label={
            showTerse ? "Switch to detailed view" : "Switch to compact view"
          }
          className="absolute top-2 right-2 text-[10px] uppercase tracking-widest text-weave-500 hover:text-weave-800 rounded border border-weave-100 px-1.5 py-0.5 bg-white/80"
        >
          {showTerse ? "Detailed" : "Compact"}
        </button>
      ) : null}

      {showTerse && fields ? (
        <SignalErrorBoundary onError={() => setRenderFailed(true)}>
          <TerseSignal fields={fields} />
        </SignalErrorBoundary>
      ) : (
        children
      )}
    </div>
  );
}
