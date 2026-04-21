"use client";

import { useState } from "react";

export type HoldingRow = { ticker: string; amount: number };

type Props = {
  onSubmit: (holdings: Record<string, number>, method: "mvo" | "quantum_qaoa" | "equal_weight", apiKey: string) => void;
  loading: boolean;
};

export function HoldingsInput({ onSubmit, loading }: Props) {
  const [rows, setRows] = useState<HoldingRow[]>([
    { ticker: "AAPL", amount: 5000 },
    { ticker: "MSFT", amount: 5000 },
    { ticker: "GOOG", amount: 5000 },
  ]);
  const [method, setMethod] = useState<"mvo" | "quantum_qaoa" | "equal_weight">("mvo");
  const [apiKey, setApiKey] = useState("");

  function updateRow(i: number, patch: Partial<HoldingRow>) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, { ticker: "", amount: 0 }]);
  }

  function removeRow(i: number) {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const holdings: Record<string, number> = {};
    for (const r of rows) {
      const t = r.ticker.trim().toUpperCase();
      if (!t || r.amount <= 0) continue;
      holdings[t] = r.amount;
    }
    if (Object.keys(holdings).length === 0 || !apiKey) return;
    onSubmit(holdings, method, apiKey);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="flex gap-2 items-center">
            <input
              type="text"
              placeholder="TICKER"
              value={r.ticker}
              onChange={(e) => updateRow(i, { ticker: e.target.value })}
              className="w-32 px-3 py-2 border border-gray-300 rounded-md text-sm font-mono uppercase"
            />
            <input
              type="number"
              placeholder="USD value"
              value={r.amount || ""}
              onChange={(e) => updateRow(i, { amount: Number(e.target.value) || 0 })}
              min={0}
              step="100"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm"
            />
            <button
              type="button"
              onClick={() => removeRow(i)}
              className="px-2 text-gray-400 hover:text-red-500 text-lg"
              aria-label="Remove row"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addRow}
          className="text-sm text-indigo-600 hover:text-indigo-700"
        >
          + Add ticker
        </button>
      </div>

      <div className="flex gap-3 items-end">
        <div className="w-48">
          <label className="block text-xs font-medium text-gray-600 mb-1">Method</label>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as "mvo" | "quantum_qaoa" | "equal_weight")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            <option value="mvo">Mean-Variance (CVXPY)</option>
            <option value="quantum_qaoa">Quantum QAOA</option>
            <option value="equal_weight">Equal weight</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">API Key</label>
          <input
            type="text"
            placeholder="sk_live_..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono"
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={loading || !apiKey}
        className="self-start px-6 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
      >
        {loading ? "Optimizing..." : "Rebalance portfolio"}
      </button>
    </form>
  );
}
