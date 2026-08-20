import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Sidebar } from "./components/Sidebar";
import { TradingView } from "./components/TradingView";
import { OverviewView } from "./components/OverviewView";
import { AgentsView } from "./components/AgentsView";
import { PlaceholderView } from "./components/PlaceholderView";
import { Onboarding, OnboardingConfig } from "./components/Onboarding";
import { AmbientBackground } from "./components/AmbientBackground";

const placeholders: Record<string, { title: string; description: string }> = {
  "crypto": { title: "Crypto Layer", description: "Layer 1 — BTC, ETH, and altcoin momentum strategies." },
  "stock": { title: "Stock Layer", description: "Layer 2 — Equity breakout and pullback strategies." },
  "options": { title: "Options Layer", description: "Layer 3 — Directional debit spreads and debit strategies." },
  "stock-weekly": { title: "Stock Weekly Layer", description: "Layer 4 — Weekly-chart-only stock patterns." },
  "wheel": { title: "Wheel Layer", description: "Layer 5 — Cash-secured puts and covered call cycles." },
  "dividends": { title: "Dividends Layer", description: "Layer 6 — High-yield dividend capture strategies." },
  "kindrip": { title: "KINDRIP Layer", description: "Layer 7 — Kind and responsible investing, long-only ETFs." },
  "strategy-lab": { title: "Strategy Lab", description: "Backtest and refine strategies before deploying them." },
  "watchlists": { title: "Watchlists", description: "Curated tickers your agents are watching for entries." },
  "grasping-wallet": { title: "Grasping Wallet", description: "Capital allocation and liquidity overview." },
  "capital-sleeves": { title: "Capital Sleeves", description: "Per-strategy budget, used, free, and velocity rules." },
  "tax-optimizer": { title: "Tax Optimizer", description: "Harvest losses and manage short-vs-long-term exposure." },
  "bot-tuning": { title: "Bot Tuning", description: "Fine-tune risk parameters, sizing rules, and entry filters." },
  "strategy-engine": { title: "Strategy Engine", description: "The core logic powering each layer's bot." },
  "ethical-filters": { title: "Ethical Filters", description: "Block specific sectors, companies, or trade types." },
  "connections": { title: "Connections", description: "Broker integrations, API keys, and webhooks." },
  "live-trading": { title: "Live Trading", description: "Switch from paper to live mode — requires confirmation." },
  "profile": { title: "Profile", description: "Your account, preferences, and notification settings." },
  "help": { title: "Help", description: "Guides, FAQs, and support for the Trezo platform." },
};

const viewVariants = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

const ONBOARDING_KEY = "trezo:onboarded";

export default function App() {
  const [activeItem, setActiveItem] = useState("trading");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(ONBOARDING_KEY)) {
        const t = setTimeout(() => setOnboardingOpen(true), 400);
        return () => clearTimeout(t);
      }
    } catch {
      setOnboardingOpen(true);
    }
  }, []);

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  const handleOnboardingComplete = (config: OnboardingConfig) => {
    try {
      localStorage.setItem(ONBOARDING_KEY, JSON.stringify(config));
    } catch {}
    setOnboardingOpen(false);
  };

  const handleNavigate = (id: string) => {
    if (id === "setup") {
      setOnboardingOpen(true);
      return;
    }
    setActiveItem(id);
  };

  const renderContent = () => {
    switch (activeItem) {
      case "trading": return <TradingView />;
      case "overview": return <OverviewView />;
      case "agents": return <AgentsView />;
      default: {
        const ph = placeholders[activeItem];
        return ph ? <PlaceholderView title={ph.title} description={ph.description} /> : null;
      }
    }
  };

  return (
    <div className={theme} style={{ height: "100dvh", display: "flex", overflow: "hidden", background: "var(--background)" }}>
      <Sidebar
        activeItem={activeItem}
        onNavigate={handleNavigate}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenSetup={() => setOnboardingOpen(true)}
      />
      <main className="relative flex-1 flex flex-col overflow-hidden" style={{ background: "var(--background)" }}>
        <AmbientBackground />
        <AnimatePresence mode="wait">
          <motion.div
            key={activeItem}
            variants={viewVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="relative flex-1 flex flex-col overflow-hidden"
            style={{ zIndex: 1 }}
          >
            {renderContent()}
          </motion.div>
        </AnimatePresence>
      </main>

      <Onboarding
        open={onboardingOpen}
        onClose={() => setOnboardingOpen(false)}
        onComplete={handleOnboardingComplete}
      />
    </div>
  );
}
