"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

type Msg = { role: "user" | "assistant"; content: string };

const GREETING =
  "Hi — I'm the Trezo assistant. Ask me anything about how Trezo works: the layers, your settings, staying safe, or where to find something.";

/**
 * Help chat — a floating assistant. Phase 12f, the "then chat" follow-up
 * to the FAQ. Calls /api/help/chat (Claude, with Trezo context). Fully
 * graceful: if the assistant is unavailable it points back to the FAQ.
 */
export function HelpChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    const next: Msg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const r = await fetch("/api/help/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: next })
      });
      const j = await r.json();
      const reply: string =
        j.reply ||
        j.error ||
        "Sorry — something went wrong. The Help & FAQ has the answers in the meantime.";
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch {
      setMessages([
        ...next,
        {
          role: "assistant",
          content:
            "I could not be reached just now — please try the Help & FAQ page."
        }
      ]);
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open the Trezo assistant"
        className="fixed bottom-4 right-4 z-40 grid h-14 w-14 place-items-center rounded-full bg-weave-600 text-treasure-50 shadow-lg transition hover:bg-weave-700"
      >
        <svg
          className="h-6 w-6"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path
            d="M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3 20l1.1-5.4A8.5 8.5 0 1 1 21 11.5z"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-40 flex h-[32rem] max-h-[calc(100vh-6rem)] w-[22rem] max-w-[calc(100vw-2rem)] flex-col rounded-xl border border-weave-200 bg-white shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-weave-100 px-4 py-3">
        <div>
          <p className="font-medium text-weave-800">Ask Trezo</p>
          <p className="text-[11px] text-weave-500">
            The help assistant · plain answers
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close the assistant"
          className="text-weave-400 transition hover:text-weave-700"
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

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        <Bubble role="assistant" content={GREETING} />
        {messages.map((m, i) => (
          <Bubble key={i} role={m.role} content={m.content} />
        ))}
        {loading && (
          <div className="max-w-[85%] rounded-xl rounded-bl-sm bg-weave-50 px-3 py-2 text-sm text-weave-500">
            Thinking…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="border-t border-weave-100 p-3">
        <div className="flex items-end gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="Ask a question…"
            maxLength={1000}
            className="flex-1 rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 outline-none focus:border-weave-400 focus:ring-1 focus:ring-weave-200"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={loading || input.trim().length === 0}
            className="rounded-md bg-weave-600 px-3 py-2 text-sm font-medium text-treasure-50 transition hover:bg-weave-700 disabled:opacity-50"
          >
            Send
          </button>
        </div>
        <p className="mt-2 text-[10px] text-weave-400">
          Prefer to browse?{" "}
          <Link href="/dashboard/help" className="underline hover:text-weave-600">
            Open the Help &amp; FAQ
          </Link>
        </p>
      </div>
    </div>
  );
}

function Bubble({ role, content }: { role: "user" | "assistant"; content: string }) {
  const isUser = role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          isUser
            ? "max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm bg-weave-600 px-3 py-2 text-sm text-treasure-50"
            : "max-w-[85%] whitespace-pre-wrap rounded-xl rounded-bl-sm bg-weave-50 px-3 py-2 text-sm text-weave-700"
        }
      >
        {content}
      </div>
    </div>
  );
}
