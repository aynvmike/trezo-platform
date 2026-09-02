"use client";

import { useMemo, useState } from "react";

type QA = { q: string; a: string };
type Topic = { topic: string; items: QA[] };

const FAQ: Topic[] = [
  {
    topic: "Getting started",
    items: [
      {
        q: "What is Trezo?",
        a: "Trezo is an automated wealth-building platform built on one idea — the Woven Basket. Your money sits inside seven layers, and each layer protects the ones beneath it. When one strategy has a rough day, the others carry the weight. Trezo does not promise riches; it promises protection, so wealth can build steadily over time."
      },
      {
        q: "Is this real money?",
        a: "No. Every trade today is paper — simulated with real market prices, but no real money is ever at risk. Real-money brokerage is a later phase and stays switched off until a full go-live checklist is complete. You will always see a PAPER or LIVE banner so there is no doubt which mode you are in."
      },
      {
        q: "How do I get started?",
        a: "Onboarding already set up your profile. From here: open Bot Tuning to set how cautious or aggressive the bot is, add a few tickers to a Watchlist, and watch the Overview page. The agents do the rest, and they explain every move they make."
      },
      {
        q: "What do the agents do?",
        a: "Trezo runs background agents — scanners that hunt for setups, a Risk Manager that approves or vetoes every trade, an executor, a position monitor, a tax tracker, and more. The Agents page lists them all. They talk to each other, and you can watch it happen live in the activity feed."
      }
    ]
  },
  {
    topic: "The seven layers",
    items: [
      {
        q: "What are the seven layers?",
        a: "From the most active to the most protected: 1) Crypto Bot, 2) Stock Bot (STMS), 3) Options Engine, 4) Extended Strategy — multi-day swing trades, 5) Dividend Wheel, 6) Dividends, 7) KINDRIP — your children's accounts. Each has its own page in the sidebar."
      },
      {
        q: "Why are they called layers?",
        a: "Picture protective rings. The outer rings — crypto, small-cap stocks — move fast and can be volatile. The inner rings — dividends, KINDRIP — are calm and protective. Gains flow inward, toward safety. That is the Woven Basket idea."
      },
      {
        q: "Do I have to use all of them?",
        a: "No. Every layer has an on/off switch in Bot Tuning. Turn off what you do not want and the rest keep running. Most people start with one or two layers and add more as they get comfortable."
      }
    ]
  },
  {
    topic: "How trading works & staying safe",
    items: [
      {
        q: "What is a Trade Confidence Score?",
        a: "Every potential trade gets a score from 0 to 100 — the TCS. It blends the chart pattern, the volume, the news backdrop, and the risk-to-reward. The higher the score, the stronger the setup. You set the minimum score the bot will act on in Bot Tuning."
      },
      {
        q: "How does the bot decide to trade?",
        a: "A scanner spots a setup and emits a signal. The Risk Manager checks it against your settings, the market backdrop, and the safety rules, then approves or vetoes it. Only approved signals reach the executor — nothing skips the Risk Manager."
      },
      {
        q: "What protects me from a losing streak?",
        a: "Several brakes. A daily loss limit pauses trading once you are down a set amount. A losing-streak limit pauses the bot after a set number of losing trades in a row. There are per-coin crypto limits and a daily profit lock too. You tune all of these in Bot Tuning."
      },
      {
        q: "What are the autonomy modes?",
        a: "They decide how much the bot may adjust on its own when news breaks. Suggest only — it recommends, you approve. Guarded — it makes risk-reducing changes within hard limits and logs them. Full — it acts more freely. Guarded is the default."
      }
    ]
  },
  {
    topic: "KINDRIP & family wealth",
    items: [
      {
        q: "What is KINDRIP?",
        a: "KINDRIP is Layer 7 — the innermost, most protected ring. It routes a contribution you set into an account for your child, which auto-invests into a steady index mix. The name comes from kindred plus dividend reinvestment. Wealth does not skip a generation."
      },
      {
        q: "What is a Future Index Account?",
        a: "It is the wrapper Trezo recommends for a child's KINDRIP account — a long-horizon, index-based account for a minor. Contributions auto-invest on an age-based glide path that grows more conservative as the child nears 18."
      },
      {
        q: "Do I need kids to use Trezo?",
        a: "Not at all. KINDRIP is optional. If you do not use it, the Dividends layer's DRIP feature still compounds your income by reinvesting distributions automatically."
      }
    ]
  },
  {
    topic: "Tax & budgeting",
    items: [
      {
        q: "What does the Tax Optimizer do?",
        a: "It tracks the tax impact of every trade in real time, estimates what to set aside, flags tax-loss-harvesting chances, and explains tax-advantaged accounts. It is educational — it shows you the math, it does not replace a tax professional."
      },
      {
        q: "What is Budget Mirror?",
        a: "Budget Mirror is a spending-analysis tool. Feed it a bank or card export, a receipt photo, a PDF, or type entries in by hand, and it categorizes your spending and shows where the money goes. It also has a savings simulator and a spend-vs-save comparison."
      },
      {
        q: "Is Budget Mirror private?",
        a: "Yes. The file you give it is read inside your browser to build the view — it is not uploaded to Trezo, stored, or sent anywhere. Receipt and PDF scanning uses AI to read the image, but the file itself is not kept."
      }
    ]
  },
  {
    topic: "Your account, data & settings",
    items: [
      {
        q: "Where do I change settings?",
        a: "Profile holds your personal details. Bot Tuning holds every trading dial — risk, thresholds, strategy on/off switches, autonomy. Ethical Filters lets you block sectors you do not want to trade. All three are in the sidebar under Settings."
      },
      {
        q: "Is my data private?",
        a: "Trezo uses row-level security — your data is yours, and the web app can only ever see your own rows. Uploaded budget files are processed in your browser and are not stored."
      },
      {
        q: "How do I turn a strategy off?",
        a: "Open Bot Tuning and use the on/off toggle in the Strategies section. The scanner keeps running but stops emitting signals. To stop a scanner entirely, use the Agents page."
      }
    ]
  }
];

export function HelpContent() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [asked, setAsked] = useState("");
  const [loading, setLoading] = useState(false);
  const q = query.trim().toLowerCase();

  const filtered = useMemo(() => {
    if (!q) return FAQ;
    return FAQ.map((t) => ({
      topic: t.topic,
      items: t.items.filter(
        (it) => it.q.toLowerCase().includes(q) || it.a.toLowerCase().includes(q)
      )
    })).filter((t) => t.items.length > 0);
  }, [q]);

  const total = FAQ.reduce((n, t) => n + t.items.length, 0);
  const shown = filtered.reduce((n, t) => n + t.items.length, 0);

  async function ask() {
    const text = query.trim();
    if (!text || loading) return;
    setLoading(true);
    setAsked(text);
    setAnswer(null);
    try {
      const r = await fetch("/api/help/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: [{ role: "user", content: text }] })
      });
      const j = await r.json();
      setAnswer(
        j.reply ||
          j.error ||
          "Sorry — I could not answer that just now. The topics below may help."
      );
    } catch {
      setAnswer(
        "I could not be reached just now — please browse the topics below."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <div className="flex gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void ask();
              }
            }}
            placeholder="Ask a question in your own words, or filter the topics…"
            className="w-full rounded-lg border border-weave-200 bg-white px-4 py-2.5 text-sm text-weave-800 outline-none focus:border-weave-400 focus:ring-1 focus:ring-weave-200"
          />
          <button
            type="button"
            onClick={() => void ask()}
            disabled={loading || query.trim().length === 0}
            className="shrink-0 rounded-lg bg-weave-600 px-4 py-2.5 text-sm font-medium text-treasure-50 transition hover:bg-weave-700 disabled:opacity-50"
          >
            {loading ? "Asking…" : "Ask Trezo"}
          </button>
        </div>
        <p className="mt-2 text-xs text-weave-500">
          {q
            ? `${shown} of ${total} topics match — or press Ask Trezo for a direct answer.`
            : "Type a question and press Ask Trezo for a direct answer, or browse the topics below."}
        </p>
      </div>

      {/* AI answer to the typed question */}
      {(loading || answer) && (
        <div className="rounded-xl border border-weave-200 bg-white p-5">
          <div className="flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-md bg-weave-600 text-treasure-50 font-serif text-xs">
              T
            </span>
            <p className="text-sm font-medium text-weave-800">
              {asked ? `Trezo on: “${asked}”` : "Trezo"}
            </p>
          </div>
          <div className="mt-3 whitespace-pre-wrap text-sm text-weave-700 leading-relaxed">
            {loading ? "Thinking it through…" : answer}
          </div>
          {!loading && answer && (
            <p className="mt-3 text-[11px] text-weave-400">
              Answered by the Trezo assistant. The topics below cover the same
              ground if you would rather read.
            </p>
          )}
        </div>
      )}

      {filtered.length === 0 && !loading && !answer && (
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
          No topic matches that wording. Press{" "}
          <span className="font-medium">Ask Trezo</span> above and the
          assistant will answer in your own words.
        </div>
      )}

      {filtered.map((t) => (
        <section key={t.topic} className="space-y-2">
          <h2 className="font-serif text-xl text-weave-800">{t.topic}</h2>
          <div className="space-y-2">
            {t.items.map((it) => (
              <details
                key={`${it.q}::${q}`}
                open={q.length > 0}
                className="group rounded-xl border border-weave-100 bg-white"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3.5 select-none">
                  <span className="font-medium text-weave-800">{it.q}</span>
                  <svg
                    className="h-4 w-4 shrink-0 text-weave-400 transition-transform group-open:rotate-180"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    aria-hidden="true"
                  >
                    <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </summary>
                <div className="border-t border-weave-50 px-5 py-3.5 text-sm text-weave-600 leading-relaxed">
                  {it.a}
                </div>
              </details>
            ))}
          </div>
        </section>
      ))}

      <div className="beginner-only rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-600 leading-relaxed">
        Still stuck? Use <span className="font-medium">Ask Trezo</span> above —
        or the chat bubble in the corner — and both will answer in plain words.
      </div>
    </div>
  );
}
