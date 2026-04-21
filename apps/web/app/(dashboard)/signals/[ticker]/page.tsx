"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { SignalCard } from "@/components/signals/SignalCard";
import { SignalChart } from "@/components/signals/SignalChart";
import { fetchSignal, fetchSignalHistory, type SignalResponse } from "@/lib/api";

export default function TickerDetailPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = (params?.ticker ?? "").toString().toUpperCase();

  const [apiKey, setApiKey] = useState("");
  const [history, setHistory] = useState<SignalResponse[]>([]);
  const [latest, setLatest] = useState<SignalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadAll() {
    if (!apiKey) return;
    setLoading(true);
    setError("");
    try {
      const [hist, fresh] = await Promise.all([
        fetchSignalHistory(ticker, apiKey, "daily", 30),
        fetchSignal(ticker, "daily", apiKey),
      ]);
      setHistory(hist);
      setLatest(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center gap-3 mb-6">
        <Link href="/dashboard/signals" className="text-sm text-gray-500 hover:text-gray-700">
          ← Signals
        </Link>
        <h1 className="text-2xl font-bold">{ticker}</h1>
      </div>

      <div className="mb-6 p-4 rounded-lg border border-gray-200 bg-gray-50 flex gap-2">
        <input
          type="text"
          placeholder="sk_live_..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm font-mono"
        />
        <button
          onClick={loadAll}
          disabled={loading || !apiKey}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Load history"}
        </button>
      </div>

      {error && <p className="text-sm text-red-500 mb-4">{error}</p>}

      {latest && (
        <div className="mb-6">
          <SignalCard signal={latest} />
        </div>
      )}

      {history.length > 0 && (
        <SignalChart
          data={history
            .slice()
            .reverse()
            .map((s) => ({
              date: new Date(s.timestamp).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
              confidence: s.confidence,
              signal: s.signal,
            }))}
        />
      )}

      {history.length === 0 && !loading && apiKey && (
        <p className="text-sm text-gray-400 mt-6">
          No history yet. Run signals from the explorer page or via the API to populate this view.
        </p>
      )}
    </div>
  );
}
