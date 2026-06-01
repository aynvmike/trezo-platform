"use client";

import { ThemeToggle } from "@/components/dashboard/theme-toggle";
import { ExperienceToggle } from "@/components/dashboard/experience-toggle";

/**
 * Display Preferences — the same theme + experience toggles that live
 * in the header, surfaced again on the Profile page for users who
 * expect them to live in Settings.
 */
export function DisplayPreferences() {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-5">
      <div>
        <h2 className="font-serif text-xl text-weave-800">Display</h2>
        <p className="mt-1 text-sm text-weave-500">
          How Trezo looks and how much it explains. These settings live in
          your browser — they apply only to this device.
        </p>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-widest text-weave-500">
            Theme
          </p>
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <span className="text-sm text-weave-600">
              Light or dark — flips the whole site.
            </span>
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-xs uppercase tracking-widest text-weave-500">
            Detail level
          </p>
          <div className="flex items-center gap-3">
            <ExperienceToggle />
            <span className="text-sm text-weave-600">
              Beginner shows full explanations; Pro hides them for a leaner
              view.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
