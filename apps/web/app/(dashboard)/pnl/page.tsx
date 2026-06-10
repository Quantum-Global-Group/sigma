"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  fetchEquityCurve,
  fetchPortfolioPnl,
  type EquityPoint,
  type PnlSummary,
} from "@/lib/api";

function money(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function plain(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pnlClass(n: number | null | undefined) {
  if (n === null || n === undefined || n === 0) return "text-gray-500";
  return n > 0 ? "text-green-600" : "text-red-600";
}

export default function PnlPage() {
  const [activeKey, setActiveKey] = useState("");
  const [pnl, setPnl] = useState<PnlSummary | null>(null);
  const [curve, setCurve] = useState<EquityPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!activeKey) return;
    setLoading(true);
    setError("");
    try {
      const [summary, points] = await Promise.all([
        fetchPortfolioPnl(activeKey),
        fetchEquityCurve(activeKey, 30),
      ]);
      setPnl(summary);
      setCurve(points);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load P&L");
    } finally {
      setLoading(false);
    }
  }, [activeKey]);

  useEffect(() => {
    if (activeKey) {
      const id = setInterval(load, 30_000);
      return () => clearInterval(id);
    }
  }, [activeKey, load]);

  const chartData = curve.map((p) => ({
    date: new Date(p.ts).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    value: p.total_value,
  }));

  const byClass = pnl ? Object.entries(pnl.by_asset_class) : [];

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Profit &amp; Loss</h1>
        {pnl && (
          <div className="text-sm text-gray-500">
            Account value{" "}
            <span className="font-semibold text-gray-800">${plain(pnl.total_value)}</span>
          </div>
        )}
      </div>

      <div className="mb-6 p-4 rounded-lg border border-gray-200 bg-gray-50 flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[260px]">
          <label className="block text-sm font-medium text-gray-700 mb-1">API key</label>
          <input
            type="text"
            placeholder="sk_live_..."
            value={activeKey}
            onChange={(e) => setActiveKey(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono"
          />
        </div>
        <button
          onClick={load}
          disabled={!activeKey || loading}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Total P&amp;L</div>
          <div className={`text-2xl font-semibold ${pnlClass(pnl?.total_pnl)}`}>
            {money(pnl?.total_pnl)}
          </div>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Realized</div>
          <div className={`text-2xl font-semibold ${pnlClass(pnl?.total_realized)}`}>
            {money(pnl?.total_realized)}
          </div>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Unrealized (open)</div>
          <div className={`text-2xl font-semibold ${pnlClass(pnl?.total_unrealized)}`}>
            {money(pnl?.total_unrealized)}
          </div>
        </div>
      </div>

      {/* Equity curve */}
      <div className="rounded-lg border border-gray-200 bg-white p-5 mb-6">
        <h3 className="text-sm font-medium text-gray-700 mb-4">Account value (last 30 days)</h3>
        {chartData.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">
            No equity snapshots yet — the daily snapshot job records the curve over time.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} tickFormatter={(v) => `$${Math.round(v)}`} />
              <Tooltip formatter={(v: number) => `$${plain(v)}`} />
              <Line type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Per-asset-class breakdown */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Asset class</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Realized</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Unrealized</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Total</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Open</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {byClass.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-400">
                  {activeKey ? "No positions yet." : "Enter an API key to load P&L."}
                </td>
              </tr>
            )}
            {byClass.map(([ac, v]) => (
              <tr key={ac} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-800 capitalize">{ac}</td>
                <td className={`px-4 py-3 text-right font-mono ${pnlClass(v.realized)}`}>{money(v.realized)}</td>
                <td className={`px-4 py-3 text-right font-mono ${pnlClass(v.unrealized)}`}>{money(v.unrealized)}</td>
                <td className={`px-4 py-3 text-right font-mono ${pnlClass(v.total)}`}>{money(v.total)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{v.open_positions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-gray-400">
        Open positions are marked-to-market each worker tick; the equity curve is recorded daily.
      </p>
    </div>
  );
}
