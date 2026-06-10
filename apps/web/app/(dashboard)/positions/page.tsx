"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchPositions, type AssetClass, type Position } from "@/lib/api";

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

function formatPnl(n: number | null) {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pnlClass(n: number | null) {
  if (n === null || n === 0) return "text-gray-500";
  return n > 0 ? "text-green-600" : "text-red-600";
}

export default function PositionsPage() {
  const [activeKey, setActiveKey] = useState("");
  const [assetClass, setAssetClass] = useState<AssetClass | "all">("all");
  const [openOnly, setOpenOnly] = useState(true);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!activeKey) return;
    setLoading(true);
    setError("");
    try {
      const data = await fetchPositions(activeKey, {
        asset_class: assetClass === "all" ? undefined : assetClass,
        open_only: openOnly,
      });
      setPositions(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, [activeKey, assetClass, openOnly]);

  useEffect(() => {
    if (activeKey) {
      const id = setInterval(load, 30_000); // poll every 30s
      return () => clearInterval(id);
    }
  }, [activeKey, load]);

  const totalUnrealized = positions.reduce((acc, p) => acc + (p.unrealized_pnl ?? 0), 0);
  const totalRealized = positions.reduce((acc, p) => acc + p.realized_pnl, 0);

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Positions</h1>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-500">Unrealized</span>
          <span className={pnlClass(totalUnrealized)}>{formatPnl(totalUnrealized)}</span>
          <span className="text-gray-300">·</span>
          <span className="text-gray-500">Realized</span>
          <span className={pnlClass(totalRealized)}>{formatPnl(totalRealized)}</span>
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
        <label className="flex items-center gap-2 text-sm text-gray-700 px-2 py-2">
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
          Open only
        </label>
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
              <th className="text-left px-4 py-3 font-medium text-gray-600">Symbol</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Class</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Qty</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Entry</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Current</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Unreal PnL</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Real PnL</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Opened</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {positions.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-gray-400">
                  {activeKey ? "No positions match the current filters." : "Enter an API key to load positions."}
                </td>
              </tr>
            )}
            {positions.map((p) => (
              <tr key={p.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-mono font-medium text-gray-800">{p.symbol}</td>
                <td className="px-4 py-3 text-gray-500">{p.asset_class}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-800">{formatNum(p.qty, 6)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{formatNum(p.entry_px, 4)}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-600">{formatNum(p.current_px, 4)}</td>
                <td className={`px-4 py-3 text-right font-mono ${pnlClass(p.unrealized_pnl)}`}>
                  {formatPnl(p.unrealized_pnl)}
                </td>
                <td className={`px-4 py-3 text-right font-mono ${pnlClass(p.realized_pnl)}`}>
                  {formatPnl(p.realized_pnl)}
                </td>
                <td className="px-4 py-3 text-gray-500">
                  {new Date(p.entry_ts).toLocaleString("en-US", { dateStyle: "short", timeStyle: "short" })}
                </td>
                <td className="px-4 py-3">
                  {p.closed ? (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">closed</span>
                  ) : (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-green-50 text-green-700">open</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-gray-400">
        Auto-refreshes every 30 seconds when an API key is set.
      </p>
    </div>
  );
}
