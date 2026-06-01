"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchOrders, type AssetClass, type Order } from "@/lib/api";

const ASSET_CLASSES: { value: AssetClass | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "crypto", label: "Crypto" },
  { value: "equity", label: "Equity" },
  { value: "forex", label: "Forex" },
  { value: "option", label: "Options" },
];

function formatNum(n: number | null, fractionDigits = 4) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

function sideClass(side: string) {
  return side === "buy"
    ? "bg-green-50 text-green-700"
    : "bg-red-50 text-red-700";
}

export default function OrdersPage() {
  const [activeKey, setActiveKey] = useState("");
  const [assetClass, setAssetClass] = useState<AssetClass | "all">("all");
  const [symbol, setSymbol] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!activeKey) return;
    setLoading(true);
    setError("");
    try {
      const data = await fetchOrders(activeKey, {
        asset_class: assetClass === "all" ? undefined : assetClass,
        symbol: symbol.trim() ? symbol.trim().toUpperCase() : undefined,
        limit: 100,
      });
      setOrders(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load orders");
    } finally {
      setLoading(false);
    }
  }, [activeKey, assetClass, symbol]);

  useEffect(() => {
    if (activeKey) {
      const id = setInterval(load, 15_000); // poll every 15s — orders evolve faster than positions
      return () => clearInterval(id);
    }
  }, [activeKey, load]);

  const totalFees = orders.reduce((acc, o) => acc + o.fee, 0);

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Orders</h1>
        <div className="text-sm text-gray-500">
          <span>Showing {orders.length}</span>
          <span className="mx-2 text-gray-300">·</span>
          <span>Total fees: {formatNum(totalFees, 2)}</span>
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
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Asset class</label>
          <select
            value={assetClass}
            onChange={(e) => setAssetClass(e.target.value as AssetClass | "all")}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            {ASSET_CLASSES.map((a) => (
              <option key={a.value} value={a.value}>{a.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Symbol filter</label>
          <input
            type="text"
            placeholder="BTC-USD"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm font-mono w-40"
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

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Time</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Symbol</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Side</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Qty</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Price</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Fee</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Slip (bps)</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Executor</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">External ID</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {orders.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-gray-400">
                  {activeKey ? "No orders match the current filters." : "Enter an API key to load orders."}
                </td>
              </tr>
            )}
            {orders.map((o) => (
              <tr key={o.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                  {new Date(o.ts).toLocaleString("en-US", { dateStyle: "short", timeStyle: "medium" })}
                </td>
                <td className="px-4 py-3 font-mono font-medium text-gray-800">{o.symbol}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 text-xs rounded-full uppercase font-medium ${sideClass(o.side)}`}>
                    {o.side}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-800">{formatNum(o.qty, 6)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{formatNum(o.px, 4)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{formatNum(o.fee, 4)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-500">
                  {o.slippage_bps !== null ? formatNum(o.slippage_bps, 1) : "—"}
                </td>
                <td className="px-4 py-3 text-gray-500">{o.executor}</td>
                <td className="px-4 py-3 font-mono text-xs text-gray-400 truncate max-w-[160px]">
                  {o.external_id ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-gray-400">
        Auto-refreshes every 15 seconds when an API key is set.
      </p>
    </div>
  );
}
