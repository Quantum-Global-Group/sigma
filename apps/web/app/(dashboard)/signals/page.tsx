"use client";

import { useState } from "react";
import { SignalForm } from "@/components/signals/SignalForm";
import { SignalCard } from "@/components/signals/SignalCard";
import { SignalChart } from "@/components/signals/SignalChart";
import { useSignal } from "@/hooks/useSignal";
import type { SignalResponse } from "@/lib/api";

export default function SignalsPage() {
  const { getSignal, signal, loading, error } = useSignal();
  const [history, setHistory] = useState<SignalResponse[]>([]);

  async function handleSubmit(ticker: string, timeframe: "daily" | "4h" | "hourly", apiKey: string) {
    const result = await getSignal(ticker, timeframe, apiKey);
    if (result) {
      setHistory((prev) => [result, ...prev].slice(0, 20));
    }
  }

  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Signal explorer</h1>

      <div className="rounded-lg border border-gray-200 bg-white p-6 mb-6">
        <SignalForm onSubmit={handleSubmit} loading={loading} />
        {error && <p className="mt-3 text-sm text-red-500">{error}</p>}
      </div>

      {signal && (
        <div className="mb-6">
          <SignalCard signal={signal} />
        </div>
      )}

      <SignalChart
        data={history.map((s, i) => ({
          date: new Date(s.timestamp).toLocaleDateString("en-US", { month: "short", day: "numeric" }) + (i === 0 ? " (now)" : ""),
          confidence: s.confidence,
          signal: s.signal,
        }))}
      />
    </div>
  );
}
