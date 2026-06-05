"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchOrders, fetchPositions, type Order, type Position } from "@/lib/api";

function num(n: number | null, d = 5) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function pnl(n: number | null) {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pnlClass(n: number | null) {
  if (n === null || n === 0) return "text-gray-500";
  return n > 0 ? "text-green-600" : "text-red-600";
}

export default function ForexPage() {
  const [activeKey, setActiveKey] = useState("");
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!activeKey) return;
    setLoading(true);
    setError("");
    try {
      const [pos, ords] = await Promise.all([
        fetchPositions(activeKey, { asset_class: "forex", open_only: true }),
        fetchOrders(activeKey, { asset_class: "forex", limit: 50 }),
      ]);
      setPositions(pos);
      setOrders(ords);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load forex data");
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

  const totalUnreal = positions.reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0);

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Forex</h1>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-500">Open unrealized</span>
          <span className={pnlClass(totalUnreal)}>{pnl(totalUnreal)}</span>
        </div>
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

      {/* Open FX positions */}
      <h2 className="text-sm font-semibold text-gray-700 mb-2">Open positions</h2>
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white mb-8">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Pair</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Units</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Entry</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Current</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Unreal PnL</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Opened</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {positions.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                  {activeKey ? "No open forex positions." : "Enter an API key to load."}
                </td>
              </tr>
            )}
            {positions.map((p) => (
              <tr key={p.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-mono font-medium text-gray-800">{p.symbol}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-800">{num(p.qty, 0)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{num(p.entry_px, 5)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{num(p.current_px, 5)}</td>
                <td className={`px-4 py-3 text-right font-mono ${pnlClass(p.unrealized_pnl)}`}>
                  {pnl(p.unrealized_pnl)}
                </td>
                <td className="px-4 py-3 text-gray-500">
                  {new Date(p.entry_ts).toLocaleString("en-US", { dateStyle: "short", timeStyle: "short" })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Recent FX fills */}
      <h2 className="text-sm font-semibold text-gray-700 mb-2">Recent fills</h2>
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Time</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Pair</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Side</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Units</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Price</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Executor</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {orders.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                  {activeKey ? "No forex fills yet." : "Enter an API key to load."}
                </td>
              </tr>
            )}
            {orders.map((o) => (
              <tr key={o.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                  {new Date(o.ts).toLocaleString("en-US", { dateStyle: "short", timeStyle: "short" })}
                </td>
                <td className="px-4 py-3 font-mono font-medium text-gray-800">{o.symbol}</td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 text-xs rounded-full uppercase font-medium ${
                      o.side === "buy" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                    }`}
                  >
                    {o.side}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-800">{num(o.qty, 0)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{num(o.px, 5)}</td>
                <td className="px-4 py-3 text-gray-500">{o.executor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-gray-400">Auto-refreshes every 30 seconds when an API key is set.</p>
    </div>
  );
}
