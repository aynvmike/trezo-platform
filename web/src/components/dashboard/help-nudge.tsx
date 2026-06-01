"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const STORAGE_KEY = "trezo_help_nudge_dismissed_v1";

/**
 * A small, dismissible pop-up that points the user to the Help & FAQ.
 * Appears once shortly after the dashboard loads; once dismissed it
 * stays gone (remembered in localStorage). Phase 12a.
 */
export function HelpNudge() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(STORAGE_KEY) === "1") return;
    } catch {
      return; // localStorage unavailable — skip the nudge
    }
    const t = setTimeout(() => setShow(true), 1800);
    return () => clearTimeout(t);
  }, []);

  function dismiss() {
    setShow(false);
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      /* ignore */
    }
  }

  if (!show) return null;

  return (
    <div className="fixed bottom-24 right-4 z-40 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-weave-200 bg-white shadow-lg">
      <div className="flex items-start gap-3 p-4">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-weave-600 font-serif text-sm text-treasure-50">
          ?
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-weave-800">Looking for something?</p>
          <p className="mt-1 text-sm text-weave-600 leading-relaxed">
            The new Help &amp; FAQ has short, searchable answers — so you can
            skip the scrolling.
          </p>
          <div className="mt-3 flex items-center gap-3">
            <Link
              href="/dashboard/help"
              onClick={dismiss}
              className="rounded-md bg-weave-600 px-3 py-1.5 text-sm font-medium text-treasure-50 transition hover:bg-weave-700"
            >
              Open Help
            </Link>
            <button
              type="button"
              onClick={dismiss}
              className="text-sm text-weave-500 transition hover:text-weave-700"
            >
              Not now
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          className="shrink-0 text-weave-400 transition hover:text-weave-700"
        >
          <svg
            className="h-4 w-4"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
