"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

type Level = "beginner" | "pro";

/**
 * Site-wide Beginner / Pro switch. Beginner (the default) shows the full
 * explanations; Pro hides teaching copy for a leaner view. The choice is
 * the `data-experience` attribute on <html> — an inline script in the
 * root layout applies the saved value before paint, so there is no
 * flash. This control just flips it and remembers the choice. CSS in
 * globals.css does the showing/hiding via `.beginner-only` / `.pro-only`.
 */
export function ExperienceToggle() {
  const [level, setLevel] = useState<Level>("beginner");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const attr = document.documentElement.getAttribute("data-experience");
    setLevel(attr === "pro" ? "pro" : "beginner");
    setReady(true);
  }, []);

  function pick(next: Level) {
    setLevel(next);
    document.documentElement.setAttribute("data-experience", next);
    try {
      localStorage.setItem("trezo_experience", next);
    } catch {
      /* localStorage unavailable — the attribute still flips this session */
    }
    // Let any interested client component react without a reload.
    window.dispatchEvent(new CustomEvent("trezo-experience", { detail: next }));
  }

  return (
    <div
      role="group"
      aria-label="Detail level"
      title="How much explanation Trezo shows you"
      className="hidden sm:flex items-center rounded-md border border-weave-200 p-0.5"
    >
      {(["beginner", "pro"] as Level[]).map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => pick(l)}
          aria-pressed={ready && level === l}
          title={
            l === "beginner"
              ? "Beginner — full explanations on every page"
              : "Pro — explanations hidden, just the essentials"
          }
          className={cn(
            "rounded px-2 py-1 text-xs capitalize transition",
            ready && level === l
              ? "bg-weave-100 text-weave-800"
              : "text-weave-500 hover:text-weave-700"
          )}
        >
          {l}
        </button>
      ))}
    </div>
  );
}
