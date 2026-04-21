"use client";

import { useState } from "react";

type Props = {
  onSubmit: (ticker: string, timeframe: "daily" | "4h" | "hourly", apiKey: string) => void;
  loading: boolean;
};

export function SignalForm({ onSubmit, loading }: Props) {
  const [ticker, setTicker] = useState("AAPL");
  const [timeframe, setTimeframe] = useState<"daily" | "4h" | "hourly">("daily");
  const [apiKey, setApiKey] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!ticker || !apiKey) return;
    onSubmit(ticker.toUpperCase(), timeframe, apiKey);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex gap-3 flex-wrap">
        <div className="flex-1 min-w-[140px]">
          <label className="block text-xs font-medium text-gray-600 mb-1">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            maxLength={20}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm uppercase font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div className="w-36">
          <label className="block text-xs font-medium text-gray-600 mb-1">Timeframe</label>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value as "daily" | "4h" | "hourly")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="daily">Daily</option>
            <option value="4h">4-Hour</option>
            <option value="hourly">Hourly</option>
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">API Key</label>
        <input
          type="text"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk_live_..."
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>

      <button
        type="submit"
        disabled={loading || !ticker || !apiKey}
        className="self-start px-6 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
      >
        {loading ? "Fetching signal..." : "Get signal"}
      </button>
    </form>
  );
}
