import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  LayoutDashboard, TrendingUp, Bot, Bitcoin, BarChart2, Layers, Calendar,
  RefreshCw, Leaf, Droplets, FlaskConical, Eye, Wallet, Shield, Calculator,
  Settings2, Cpu, Filter, Plug, Radio, User, HelpCircle, ChevronDown, ChevronRight,
  Sun, Moon, Sparkles,
} from "lucide-react";

type NavItem = {
  id: string;
  label: string;
  icon: React.ReactNode;
  chip?: number;
  status?: "active" | "idle" | "paused";
};

type NavSection = {
  id: string;
  title: string;
  items: NavItem[];
  collapsible?: boolean;
};

const sections: NavSection[] = [
  {
    id: "happening",
    title: "What's Happening",
    items: [
      { id: "overview", label: "Overview", icon: <LayoutDashboard size={15} /> },
      { id: "trading", label: "Trading", icon: <TrendingUp size={15} />, status: "active" },
      { id: "agents", label: "Agents", icon: <Bot size={15} /> },
    ],
  },
  {
    id: "layers",
    title: "Wealth Layers",
    items: [
      { id: "crypto", label: "Crypto", icon: <Bitcoin size={15} />, chip: 1, status: "active" },
      { id: "stock", label: "Stock", icon: <BarChart2 size={15} />, chip: 2, status: "active" },
      { id: "options", label: "Options", icon: <Layers size={15} />, chip: 3, status: "idle" },
      { id: "stock-weekly", label: "Stock Weekly", icon: <Calendar size={15} />, chip: 4, status: "idle" },
      { id: "wheel", label: "Wheel", icon: <RefreshCw size={15} />, chip: 5, status: "active" },
      { id: "dividends", label: "Dividends", icon: <Leaf size={15} />, chip: 6, status: "paused" },
      { id: "kindrip", label: "KINDRIP", icon: <Droplets size={15} />, chip: 7, status: "active" },
    ],
  },
  {
    id: "plan",
    title: "Plan & Research",
    items: [
      { id: "strategy-lab", label: "Strategy Lab", icon: <FlaskConical size={15} /> },
      { id: "watchlists", label: "Watchlists", icon: <Eye size={15} /> },
      { id: "grasping-wallet", label: "Grasping Wallet", icon: <Wallet size={15} /> },
      { id: "capital-sleeves", label: "Capital Sleeves", icon: <Shield size={15} /> },
      { id: "tax-optimizer", label: "Tax Optimizer", icon: <Calculator size={15} /> },
    ],
  },
  {
    id: "configure",
    title: "Configure",
    collapsible: true,
    items: [
      { id: "bot-tuning", label: "Bot Tuning", icon: <Settings2 size={15} /> },
      { id: "strategy-engine", label: "Strategy Engine", icon: <Cpu size={15} /> },
      { id: "ethical-filters", label: "Ethical Filters", icon: <Filter size={15} /> },
      { id: "connections", label: "Connections", icon: <Plug size={15} /> },
      { id: "live-trading", label: "Live Trading", icon: <Radio size={15} /> },
      { id: "profile", label: "Profile", icon: <User size={15} /> },
      { id: "help", label: "Help", icon: <HelpCircle size={15} /> },
    ],
  },
];

function PulseDot({ color }: { color: string }) {
  return (
    <span className="relative flex items-center justify-center w-2 h-2 shrink-0">
      <motion.span
        className="absolute inline-flex rounded-full"
        style={{ background: color, width: 6, height: 6 }}
        animate={{ scale: [1, 1.8, 1], opacity: [0.7, 0, 0.7] }}
        transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
      />
      <span className="relative inline-flex rounded-full w-1.5 h-1.5" style={{ background: color }} />
    </span>
  );
}

function IdleDot() {
  return <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: "var(--muted-foreground)", opacity: 0.4 }} />;
}

function PausedDot() {
  return (
    <motion.span
      className="w-1.5 h-1.5 rounded-full shrink-0"
      style={{ background: "var(--amber)" }}
      animate={{ opacity: [1, 0.3, 1] }}
      transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
    />
  );
}

type Props = {
  activeItem: string;
  onNavigate: (id: string) => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onOpenSetup?: () => void;
};

export function Sidebar({ activeItem, onNavigate, theme, onToggleTheme, onOpenSetup }: Props) {
  const [configOpen, setConfigOpen] = useState(false);

  return (
    <motion.aside
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-col h-full w-60 shrink-0 border-r border-border"
      style={{ background: "var(--sidebar)" }}
    >
      {/* Logo */}
      <div className="px-5 py-5 border-b border-sidebar-border">
        <motion.div
          className="flex items-center gap-2.5"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15 }}
        >
          <motion.div
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: "var(--treasure)", opacity: 0.9 }}
            whileHover={{ scale: 1.08, opacity: 1 }}
            transition={{ duration: 0.15 }}
          >
            <span className="text-[11px] font-bold text-black/80" style={{ fontFamily: "var(--font-serif)" }}>
              T
            </span>
          </motion.div>
          <div>
            <div className="leading-none" style={{ fontFamily: "var(--font-serif)", fontWeight: 500, fontSize: "15px", color: "var(--sidebar-foreground)" }}>
              Trezo
            </div>
            <div className="text-[10px] mt-0.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              WOVEN BASKET
            </div>
          </div>
        </motion.div>
      </div>

      {/* Mode banner */}
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25 }}
        className="mx-3 mt-3 px-3 py-2 rounded-lg flex items-center gap-2 border border-dashed"
        style={{ borderColor: "rgba(245,158,11,0.35)", background: "rgba(245,158,11,0.06)" }}
      >
        <PausedDot />
        <span className="text-[11px]" style={{ color: "var(--amber)", fontFamily: "var(--font-mono)" }}>
          PAPER MODE · Auto-trade OFF
        </span>
      </motion.div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {sections.map((section, sectionIdx) => {
          const isCollapsible = section.collapsible;
          const isOpen = isCollapsible ? configOpen : true;

          return (
            <motion.div
              key={section.id}
              className="mb-2"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1 + sectionIdx * 0.06 }}
            >
              <button
                className="w-full flex items-center justify-between px-3 py-1.5 rounded-md"
                onClick={isCollapsible ? () => setConfigOpen((v) => !v) : undefined}
                style={{ cursor: isCollapsible ? "pointer" : "default" }}
              >
                <span
                  className="text-[10px] tracking-widest uppercase"
                  style={{ color: "var(--treasure)", fontFamily: "var(--font-sans)", fontWeight: 600, letterSpacing: "0.1em" }}
                >
                  {section.title}
                </span>
                {isCollapsible && (
                  <motion.span
                    style={{ color: "var(--muted-foreground)" }}
                    animate={{ rotate: isOpen ? 0 : -90 }}
                    transition={{ duration: 0.2 }}
                  >
                    <ChevronDown size={12} />
                  </motion.span>
                )}
              </button>

              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.22, ease: "easeInOut" }}
                    style={{ overflow: "hidden" }}
                  >
                    <div className="mt-0.5 space-y-0.5">
                      {section.items.map((item, itemIdx) => {
                        const isActive = activeItem === item.id;
                        return (
                          <motion.button
                            key={item.id}
                            onClick={() => onNavigate(item.id)}
                            className="w-full flex items-center gap-2.5 text-left relative"
                            style={{
                              padding: "8px 10px",
                              borderRadius: "6px",
                              color: isActive ? "var(--treasure)" : "var(--sidebar-foreground)",
                            }}
                            whileHover={{ x: 2 }}
                            transition={{ duration: 0.15 }}
                            initial={{ opacity: 0, x: -6 }}
                            animate={{ opacity: 1, x: 0 }}
                          >
                            {/* Active background */}
                            {isActive && (
                              <motion.span
                                layoutId="sidebar-active-bg"
                                className="absolute inset-0 rounded-md"
                                style={{ background: "var(--sidebar-accent)" }}
                                transition={{ type: "spring", stiffness: 380, damping: 30 }}
                              />
                            )}

                            {/* Active left border */}
                            {isActive && (
                              <motion.span
                                layoutId="sidebar-active-bar"
                                className="absolute left-0 top-1 bottom-1 w-0.5 rounded-full"
                                style={{ background: "var(--treasure)" }}
                                transition={{ type: "spring", stiffness: 380, damping: 30 }}
                              />
                            )}

                            <span className="relative z-10 flex items-center gap-2.5 w-full">
                              {item.chip !== undefined ? (
                                <motion.span
                                  className="w-4 h-4 rounded flex items-center justify-center shrink-0 text-[10px]"
                                  style={{
                                    background: isActive ? "var(--treasure)" : "var(--muted)",
                                    color: isActive ? "var(--background)" : "var(--muted-foreground)",
                                    fontFamily: "var(--font-mono)",
                                    fontWeight: 500,
                                  }}
                                  animate={{ scale: isActive ? 1.05 : 1 }}
                                >
                                  {item.chip}
                                </motion.span>
                              ) : (
                                <span
                                  className="shrink-0"
                                  style={{ color: isActive ? "var(--treasure)" : "var(--muted-foreground)", opacity: isActive ? 1 : 0.65 }}
                                >
                                  {item.icon}
                                </span>
                              )}

                              <span className="flex-1 text-[13px]" style={{ fontWeight: isActive ? 500 : 400 }}>
                                {item.label}
                              </span>

                              {item.status === "active" && <PulseDot color="var(--emerald)" />}
                              {item.status === "idle" && <IdleDot />}
                              {item.status === "paused" && <PausedDot />}
                            </span>
                          </motion.button>
                        );
                      })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </nav>

      {/* Bottom — setup + theme */}
      <div className="px-3 py-4 border-t border-sidebar-border space-y-2">
        {onOpenSetup && (
          <motion.button
            onClick={onOpenSetup}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md"
            style={{ background: "transparent", color: "var(--sidebar-foreground)", border: "1px dashed var(--sidebar-border)" }}
            whileHover={{ scale: 1.02, borderColor: "var(--treasure)" }}
            whileTap={{ scale: 0.97 }}
            transition={{ duration: 0.15 }}
          >
            <Sparkles size={14} style={{ color: "var(--treasure)" }} />
            <span className="text-[12px]">Run setup</span>
          </motion.button>
        )}
        <motion.button
          onClick={onToggleTheme}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-md"
          style={{ background: "var(--sidebar-accent)", color: "var(--sidebar-foreground)" }}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.97 }}
          transition={{ duration: 0.15 }}
        >
          <motion.span
            key={theme}
            initial={{ rotate: -30, opacity: 0 }}
            animate={{ rotate: 0, opacity: 1 }}
            transition={{ duration: 0.25 }}
          >
            {theme === "dark"
              ? <Sun size={14} style={{ color: "var(--treasure)" }} />
              : <Moon size={14} style={{ color: "var(--primary)" }} />
            }
          </motion.span>
          <span className="text-[12px]">{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
        </motion.button>
      </div>
    </motion.aside>
  );
}
