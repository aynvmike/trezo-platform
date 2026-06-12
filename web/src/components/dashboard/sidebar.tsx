"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { NAV, type NavItem } from "./nav-config";

/**
 * Sidebar - 4 intent-based groups:
 *   WHAT'S HAPPENING  daily real-time monitoring
 *   WEALTH LAYERS     the Woven Basket, 1..7
 *   PLAN & RESEARCH   analytical surfaces
 *   CONFIGURE         knobs + reference (collapsed by default)
 *
 * Visual upgrades per Mike's Neo Obsidian direction:
 *   - section headers small-caps + treasure, with hairline rule
 *   - 2px treasure left-border for active item (calmer than bg fill)
 *   - Wealth Layers keeps the numbered pip + vertical connector
 *   - Configure collapses with a chevron toggle so the daily layout
 *     isn't cluttered by knobs you only touch occasionally
 */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();

  const monitor   = NAV.filter((n) => n.section === "monitor");
  const layers    = NAV.filter((n) => n.section === "layers");
  const plan      = NAV.filter((n) => n.section === "plan");
  const configure = NAV.filter((n) => n.section === "configure");

  const [configureOpen, setConfigureOpen] = useState<boolean>(false);

  return (
    <nav className="p-3 space-y-6">
      <SectionHeader>What&apos;s happening</SectionHeader>
      <NavGroup items={monitor} path={path} onNavigate={onNavigate} />

      {/* Task #73 (2026-06-05): Wealth Layers compacted - dropped the
          2-line description and tightened the connector line padding.
          Same 7 layers, less vertical footprint. The description was
          useful onboarding but every returning user knows what they
          are now. */}
      <div>
        <SectionHeader>Wealth layers</SectionHeader>
        <p className="px-3 mb-1 text-[9px] text-weave-400/80 leading-tight italic">
          Outer = volatile - Inner = protected
        </p>
        <ol className="relative">
          <span
            aria-hidden="true"
            className="absolute left-[22px] top-2 bottom-2 w-px bg-gradient-to-b from-weave-200 via-weave-300 to-treasure-300"
          />
          {layers.map((item) => (
            <LayerRow key={item.label} item={item} path={path} onNavigate={onNavigate} />
          ))}
        </ol>
      </div>

      <div>
        <SectionHeader>Plan &amp; research</SectionHeader>
        <NavGroup items={plan} path={path} onNavigate={onNavigate} />
      </div>

      <div>
        <button
          type="button"
          onClick={() => setConfigureOpen((v) => !v)}
          className="w-full flex items-baseline justify-between px-3 mb-2 group"
          aria-expanded={configureOpen}
        >
          <span className="text-[10px] uppercase tracking-widest text-treasure-600 group-hover:text-treasure-700">
            Configure
          </span>
          <span className="text-[10px] text-weave-400 group-hover:text-weave-600">
            {configureOpen ? "−" : "+"}
          </span>
        </button>
        <div
          aria-hidden="true"
          className="mx-3 mb-2 h-px bg-gradient-to-r from-treasure-200/60 via-weave-100 to-transparent"
        />
        {configureOpen ? (
          <NavGroup items={configure} path={path} onNavigate={onNavigate} />
        ) : (
          <p className="px-3 text-[10px] text-weave-400 italic">
            Tap + to reveal settings, connections, filters.
          </p>
        )}
      </div>
    </nav>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <p className="px-3 mb-2 text-[10px] uppercase tracking-widest text-treasure-600">
        {children}
      </p>
      <div
        aria-hidden="true"
        className="mx-3 mb-2 h-px bg-gradient-to-r from-treasure-200/60 via-weave-100 to-transparent"
      />
    </div>
  );
}

function NavGroup({
  items,
  path,
  onNavigate,
}: {
  items: NavItem[];
  path: string;
  onNavigate?: () => void;
}) {
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        if (item.disabled) {
          return (
            <li
              key={item.label}
              className="pl-3 pr-3 py-2 rounded-md text-sm text-weave-400 cursor-not-allowed flex items-center justify-between border-l-2 border-transparent"
              title={item.phase ? `Coming in Phase ${item.phase}` : "Coming soon"}
            >
              <span className="truncate">{item.label}</span>
              {item.phase && (
                <span className="shrink-0 text-[10px] rounded-full px-2 py-0.5 bg-weave-50 text-weave-400">
                  Phase {item.phase}
                </span>
              )}
            </li>
          );
        }
        const isActive = item.href === path;
        return (
          <li key={item.label}>
            <Link
              href={item.href!}
              onClick={onNavigate}
              className={cn(
                "block pl-3 pr-3 py-2 rounded-r-md text-sm transition border-l-2",
                isActive
                  ? "border-treasure-500 bg-weave-50 text-weave-900 font-medium"
                  : "border-transparent text-weave-600 hover:bg-weave-50 hover:border-weave-200"
              )}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function LayerRow({
  item,
  path,
  onNavigate,
}: {
  item: NavItem;
  path: string;
  onNavigate?: () => void;
}) {
  const isActive = item.href === path;
  const layerNum = item.layer ?? 0;

  const Pip = (
    <span
      className={cn(
        "relative z-10 grid h-6 w-6 place-items-center rounded-full text-[10px] font-medium shrink-0 ring-2 ring-treasure-50",
        item.disabled
          ? "bg-weave-100 text-weave-400"
          : isActive
          ? "bg-weave-700 text-treasure-50"
          : "bg-treasure-200 text-treasure-700"
      )}
    >
      {layerNum}
    </span>
  );

  if (item.disabled) {
    return (
      <li
        className="relative flex items-center gap-3 px-3 py-2 rounded-md cursor-not-allowed text-sm text-weave-400"
        title={item.phase ? `Coming in Phase ${item.phase}` : "Coming soon"}
      >
        {Pip}
        <span className="flex-1 truncate">{item.label}</span>
        {item.phase && (
          <span className="text-[10px] rounded-full px-2 py-0.5 bg-weave-50 text-weave-400">
            Phase {item.phase}
          </span>
        )}
      </li>
    );
  }

  return (
    <li className="relative">
      <Link
        href={item.href!}
        onClick={onNavigate}
        className={cn(
          "flex items-center gap-3 pl-3 pr-3 py-2 rounded-r-md text-sm transition border-l-2",
          isActive
            ? "border-treasure-500 bg-weave-50 text-weave-900 font-medium"
            : "border-transparent text-weave-600 hover:bg-weave-50 hover:border-weave-200"
        )}
      >
        {Pip}
        <span className="flex-1 truncate">{item.label}</span>
      </Link>
    </li>
  );
}
