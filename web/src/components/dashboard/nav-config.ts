export type NavSection = "monitor" | "layers" | "plan" | "configure";

export type NavItem = {
  href: string | null;     // null = disabled / not yet live
  label: string;
  layer?: number;          // 1..7 — which Trezo layer this is
  phase?: number;          // phase number where it goes live
  disabled?: boolean;
  section: NavSection;
};

/**
 * Sidebar navigation — four intent-based groups (Mike 2026-06-01).
 *
 * WHAT'S HAPPENING   real-time monitoring (Overview, Trading, Agents)
 * WEALTH LAYERS      the Woven Basket, outer→inner ring 1→7
 * PLAN & RESEARCH    analytical surfaces (Strategy Lab, Watchlists,
 *                    Grasping Wallet, Tax Optimizer)
 * CONFIGURE          actual settings + Help (Bot Tuning, Strategy
 *                    Engine, Ethical Filters, Connections, Live
 *                    Trading, Profile, Help & FAQ)
 *
 * Previous grouping (core / layers / settings) was a dumping ground -
 * Settings had Profile (truly a setting) next to Agents (real-time
 * monitoring) next to Tax Optimizer (domain feature). The intent-
 * based grouping puts daily destinations up top, planning surfaces
 * in the middle, and knobs at the bottom.
 */
export const NAV: NavItem[] = [
  // WHAT'S HAPPENING — daily real-time destinations
  { href: "/dashboard",                    label: "Overview",          section: "monitor" },
  // Paper + Live merged into single "Trading" tab on 2026-05-30.
  // /dashboard/live still redirects here.
  { href: "/dashboard/paper",              label: "Trading",           section: "monitor" },
  { href: "/dashboard/agents",             label: "Agents",            section: "monitor" },

  // WEALTH LAYERS — outer ring (most volatile) → inner ring (most protected)
  { href: "/dashboard/crypto",             label: "Crypto Bot",          layer: 1, phase: 2,  section: "layers" },
  { href: "/dashboard/stms",               label: "Stock Bot",           layer: 2, phase: 2,  section: "layers" },
  { href: "/dashboard/options",            label: "Options Engine",      layer: 3, phase: 6,  section: "layers" },
  { href: "/dashboard/extended",           label: "Stock Weekly",        layer: 4, phase: 10, section: "layers" },
  { href: "/dashboard/wheel",              label: "Wheel (Options)",     layer: 5, phase: 6,  section: "layers" },
  { href: "/dashboard/yieldmax",           label: "Dividends",           layer: 6, phase: 2,  section: "layers" },
  { href: "/dashboard/kindrip",            label: "KINDRIP",             layer: 7, phase: 9,  section: "layers" },

  // PLAN & RESEARCH — analytical surfaces (build, test, learn)
  { href: "/dashboard/strategy-lab",       label: "Strategy Lab",      section: "plan" },
  { href: "/dashboard/watchlists",         label: "Watchlists",        section: "plan" },
  // Budget Mirror + Future Projections merged into "Grasping Wallet"
  // on 2026-05-30. /dashboard/projections still redirects here.
  { href: "/dashboard/budget",             label: "Grasping Wallet",   section: "plan" },
  { href: "/dashboard/sleeves",            label: "Capital Sleeves",   section: "plan" },
  { href: "/dashboard/tax",                label: "Tax Optimizer",     section: "plan" },

  // CONFIGURE — knobs + reference
  { href: "/dashboard/settings/bot",       label: "Bot Tuning",        section: "configure" },
  { href: "/dashboard/strategy",           label: "Strategy Engine",   section: "configure" },
  { href: "/dashboard/settings/filters",   label: "Ethical Filters",   section: "configure" },
  { href: "/dashboard/settings/connections", label: "Connections",     section: "configure" },
  { href: "/dashboard/settings/live",      label: "Live Trading",      section: "configure" },
  { href: "/dashboard/settings/profile",   label: "Profile",           section: "configure" },
  { href: "/onboarding/tour",              label: "Setup Wizard",      section: "configure" },
  { href: "/dashboard/help",               label: "Help & FAQ",        section: "configure" },
];
