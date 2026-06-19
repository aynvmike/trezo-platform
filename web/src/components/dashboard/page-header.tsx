"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

/**
 * PageHeader — the Neo-Obsidian "update 2" shared page header: a gold
 * small-caps eyebrow, a serif title, a plain-English subtitle, and an
 * optional collapsible "quick primer" (keeps explainer copy off-screen
 * until asked for). Trezo-tokened, no framer-motion.
 */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  explainer,
  action,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  explainer?: string;
  action?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="flex-1">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-treasure-600">{eyebrow}</p>
        <h1 className="font-serif text-[32px] font-medium leading-[1.1] tracking-tight text-weave-800">{title}</h1>
        <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-weave-600">{subtitle}</p>
        {explainer ? (
          <div className="mt-3">
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="flex items-center gap-1.5 text-[11px] text-weave-500 transition-colors hover:text-weave-700"
            >
              <ChevronDown size={11} className={"transition-transform duration-200 " + (open ? "" : "-rotate-90")} />
              <span>{open ? "Hide" : "New here? Quick primer"}</span>
            </button>
            {open ? (
              <p className="mt-2 max-w-2xl rounded-md border border-dashed border-weave-200 bg-weave-50/50 px-3 py-2 text-[12px] leading-relaxed text-weave-600">
                {explainer}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
