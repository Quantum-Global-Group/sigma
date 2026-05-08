"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchExecutionStatus,
  triggerRunCycle,
  type AssetClass,
  type ExecutionStatus,
} from "@/lib/api";

function modeBadgeClass(mode: string) {
  if (mode === "paper") return "bg-blue-50 text-blue-700";
  if (mode === "coinbase") return "bg-amber-50 text-amber-700";
  return "bg-gray-100 text-gray-600";
}

export default function ExecutionPage() {
  const [activeKey, setActiveKey] = useState("");
  const [internalSecret, setInternalSecret] = useState("");
  const [status, setStatus] = useState<ExecutionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [triggering, setTriggering] = useState<AssetClass | null>(null);
  const [lastTriggered, setLastTriggered] = useState<{ asset_class: AssetClass; ts: string } | null>(null);

  const load = useCallback(async () => {
    if (!activeKey) return;
    setLoading(true);
    setError("");
    try {
      setStatus(await fetchExecutionStatus(activeKey));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load status");
    } finally {
      setLoading(false);
    }
  }, [activeKey]);

  useEffect(() => {
    if (activeKey) load();
  }, [activeKey, load]);

  async function handleRunCycle(assetClass: AssetClass) {
    if (!internalSecret) {
      setError("Internal secret required to trigger run_cycle");
      return;
    }
    setTriggering(assetClass);
    setError("");
    try {
      await triggerRunCycle(internalSecret, assetClass);
      setLastTriggered({ asset_class: assetClass, ts: new Date().toISOString() });
    } catch (e) {
      setError(e instanceof Error ? e.message : "run_cycle failed");
    } finally {
      setTriggering(null);
    }
  }

  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Execution</h1>

      <div className="mb-6 p-4 rounded-lg border border-gray-200 bg-gray-50">
        <label className="block text-sm font-medium text-gray-700 mb-1">API key</label>
        <input
          type="text"
          placeholder="sk_live_..."
          value={activeKey}
          onChange={(e) => setActiveKey(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono"
        />
      </div>

      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

      {status && (
        <div className="mb-6 p-6 rounded-lg border border-gray-200 bg-white">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Worker status</h2>
          <dl className="grid grid-cols-2 gap-y-3 gap-x-6 text-sm">
            <dt className="text-gray-500">Executor mode</dt>
            <dd>
              <span className={`px-2 py-0.5 text-xs rounded-full font-medium uppercase ${modeBadgeClass(status.executor_mode)}`}>
                {status.executor_mode}
              </span>
              {status.executor_mode === "coinbase" && (
                <span className="ml-3 text-xs text-gray-500">
                  {status.coinbase_sandbox ? "(sandbox)" : "(LIVE)"}
                </span>
              )}
            </dd>

            <dt className="text-gray-500">Crypto cadence</dt>
            <dd className="font-mono text-gray-800">
              {status.worker_asset_classes_default_crypto_seconds}s
              <span className="ml-2 text-xs text-gray-400">
                (~{Math.round(status.worker_asset_classes_default_crypto_seconds / 60)} min)
              </span>
            </dd>

            <dt className="text-gray-500">Equity cadence</dt>
            <dd className="font-mono text-gray-800">
              {status.worker_asset_classes_default_equity_seconds}s
              <span className="ml-2 text-xs text-gray-400">
                (~{Math.round(status.worker_asset_classes_default_equity_seconds / 60)} min)
              </span>
            </dd>
          </dl>
          <button
            onClick={load}
            disabled={loading}
            className="mt-4 text-xs text-indigo-600 hover:underline disabled:opacity-50"
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      )}

      <div className="p-6 rounded-lg border border-amber-200 bg-amber-50">
        <h2 className="text-sm font-semibold text-amber-900 uppercase tracking-wide mb-2">
          Manual cycle trigger
        </h2>
        <p className="text-xs text-amber-800 mb-4">
          Runs one full worker tick on demand. Requires the worker&apos;s INTERNAL_SECRET — customer
          API keys are rejected with 403. Useful for ops debugging without waiting for the next
          scheduled cycle.
        </p>

        <label className="block text-xs font-medium text-amber-900 mb-1">Internal secret</label>
        <input
          type="password"
          placeholder="(value of INTERNAL_SECRET env var)"
          value={internalSecret}
          onChange={(e) => setInternalSecret(e.target.value)}
          className="w-full mb-4 px-3 py-2 border border-amber-300 rounded-md text-sm font-mono bg-white"
        />

        <div className="flex gap-2">
          {(["crypto", "equity"] as AssetClass[]).map((ac) => (
            <button
              key={ac}
              onClick={() => handleRunCycle(ac)}
              disabled={!internalSecret || triggering !== null}
              className="px-4 py-2 bg-amber-600 text-white rounded-md text-sm hover:bg-amber-500 disabled:opacity-50"
            >
              {triggering === ac ? `Running ${ac}...` : `Run ${ac} cycle`}
            </button>
          ))}
        </div>

        {lastTriggered && (
          <p className="mt-3 text-xs text-amber-800">
            ✓ Triggered <span className="font-mono">{lastTriggered.asset_class}</span> at{" "}
            {new Date(lastTriggered.ts).toLocaleTimeString()}. Check{" "}
            <a href="/orders" className="underline">orders</a> for new fills.
          </p>
        )}
      </div>
    </div>
  );
}
