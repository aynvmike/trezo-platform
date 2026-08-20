import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Sidebar } from "./components/Sidebar";
import { TradingView } from "./components/TradingView";
import { OverviewView } from "./components/OverviewView";
import { AgentsView } from "./components/AgentsView";
import { PlaceholderView } from "./components/PlaceholderView";
import { Onboarding, OnboardingConfig } from "./components/Onboarding";
import { AmbientBackground } from "./components/AmbientBackground";
import { LandingPage } from "./components/LandingPage";
import { LayerPage } from "./components/LayerPage";
import { layerData } from "./components/layerData";
import { CapitalSleevesView } from "./components/CapitalSleevesView";
import { StrategyLabView } from "./components/StrategyLabView";
import { WatchlistsView } from "./components/WatchlistsView";
import { GraspingWalletView } from "./components/GraspingWalletView";
import { TaxOptimizerView } from "./components/TaxOptimizerView";
import { ProfileView } from "./components/ProfileView";
import { EthicalFiltersView } from "./components/EthicalFiltersView";
import { ConnectionsView } from "./components/ConnectionsView";
import { LiveTradingView } from "./components/LiveTradingView";
import { HelpView } from "./components/HelpView";
import { StrategyEngineView } from "./components/StrategyEngineView";
import { BotTuningView } from "./components/BotTuningView";

const placeholders: Record<string, { title: string; description: string }> = {};

const viewVariants = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

const ONBOARDING_KEY = "trezo:onboarded";

export default function App() {
  const [view, setView] = useState<"landing" | "dashboard">("landing");
  const [activeItem, setActiveItem] = useState("overview");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  useEffect(() => {
    if (view !== "dashboard") return;
    try {
      if (!localStorage.getItem(ONBOARDING_KEY)) {
        const t = setTimeout(() => setOnboardingOpen(true), 400);
        return () => clearTimeout(t);
      }
    } catch {
      setOnboardingOpen(true);
    }
  }, [view]);

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
      case "capital-sleeves": return <CapitalSleevesView />;
      case "strategy-lab": return <StrategyLabView />;
      case "watchlists": return <WatchlistsView />;
      case "grasping-wallet": return <GraspingWalletView />;
      case "tax-optimizer": return <TaxOptimizerView />;
      case "profile": return <ProfileView />;
      case "ethical-filters": return <EthicalFiltersView />;
      case "connections": return <ConnectionsView />;
      case "live-trading": return <LiveTradingView />;
      case "help": return <HelpView />;
      case "strategy-engine": return <StrategyEngineView />;
      case "bot-tuning": return <BotTuningView />;
      default: {
        if (layerData[activeItem]) {
          return <LayerPage data={layerData[activeItem]} />;
        }
        const ph = placeholders[activeItem];
        return ph ? <PlaceholderView title={ph.title} description={ph.description} /> : null;
      }
    }
  };

  if (view === "landing") {
    return (
      <AnimatePresence mode="wait">
        <motion.div
          key="landing"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
        >
          <LandingPage onEnter={() => setView("dashboard")} />
        </motion.div>
      </AnimatePresence>
    );
  }

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
