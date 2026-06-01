"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function NewWatchlistButton() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/watchlists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() })
      });
      if (!r.ok) {
        const j = await r.json();
        throw new Error(j.error ?? "Failed");
      }
      const { watchlist } = (await r.json()) as { watchlist: { id: string } };
      setOpen(false);
      setName("");
      router.push(`/dashboard/watchlists/${watchlist.id}`);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return <Button onClick={() => setOpen(true)}>New watchlist</Button>;
  }

  return (
    <form onSubmit={onSubmit} className="flex items-start gap-2">
      <div>
        <Input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Earnings Plays"
          maxLength={80}
        />
        {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      </div>
      <Button type="submit" disabled={saving}>
        {saving ? "Creating…" : "Create"}
      </Button>
      <Button
        type="button"
        variant="ghost"
        onClick={() => {
          setOpen(false);
          setName("");
          setError(null);
        }}
      >
        Cancel
      </Button>
    </form>
  );
}
