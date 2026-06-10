"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

type StrategyStat = {
  strategy: string;
  contribution_frequency: number;
  avg_strength_when_present: number | null;
  win_rate_above_threshold: number | null;
  n_above_threshold: number;
};

type PerformanceResponse = {
  asset_class: string;
  period?: string | null;
  since?: string | null;
  n_signals: number;
  n_labeled: number;
  strength_threshold: number;
  strategies: StrategyStat[];
  summary?: string;
};

export default function StrategiesPage() {
  const [data, setData] = useState<PerformanceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assetClass, setAssetClass] = useState("equity");

  useEffect(() => {
    const key = typeof window !== "undefined" ? localStorage.getItem("sigma_api_key") : null;
    if (!key) {
      setError("Set an API key on the API Keys page first.");
      return;
    }
    setError(null);
    fetch(`${API_BASE}/strategies/performance/report?asset_class=${assetClass}&period=7d`, {
      headers: { Authorization: `Bearer ${key}` },
    })
      .then((r) => (r.ok ? r.json() : r.json().then((e) => Promise.reject(new Error(e.detail ?? r.statusText)))))
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [assetClass]);

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-bold mb-2">Strategy performance</h1>
      <p className="text-sm text-gray-500 mb-6">
        Per-strategy contribution and win rate when strength exceeds the threshold.
        Uses the last 7 days of equity signals by default (
        <code className="text-xs bg-gray-100 px-1 rounded">GET /strategies/performance/report?period=7d</code>
        ).
      </p>

      <div className="mb-4 flex gap-2">
        {(["equity", "crypto", "forex"] as const).map((ac) => (
          <button
            key={ac}
            type="button"
            onClick={() => setAssetClass(ac)}
            className={`px-3 py-1 rounded text-sm ${assetClass === ac ? "bg-indigo-600 text-white" : "bg-gray-100"}`}
          >
            {ac}
          </button>
        ))}
      </div>

      {error && <p className="text-sm text-red-500 mb-4">{error}</p>}

      {data && (
        <>
          <p className="text-sm text-gray-600 mb-4">
            {data.n_signals} signals ({data.n_labeled} labeled) · threshold {data.strength_threshold}
            {data.period ? ` · period ${data.period}` : ""}
          </p>
          {data.summary && (
            <pre className="text-xs bg-gray-50 border border-gray-200 rounded-lg p-4 mb-4 whitespace-pre-wrap font-mono overflow-x-auto">
              {data.summary}
            </pre>
          )}
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left">Strategy</th>
                  <th className="px-4 py-2 text-right">Contribution</th>
                  <th className="px-4 py-2 text-right">Avg strength</th>
                  <th className="px-4 py-2 text-right">Win rate (&gt; thr)</th>
                  <th className="px-4 py-2 text-right">N above thr</th>
                </tr>
              </thead>
              <tbody>
                {data.strategies.map((s) => (
                  <tr key={s.strategy} className="border-t border-gray-100">
                    <td className="px-4 py-2 font-medium">{s.strategy}</td>
                    <td className="px-4 py-2 text-right">{(s.contribution_frequency * 100).toFixed(1)}%</td>
                    <td className="px-4 py-2 text-right">
                      {s.avg_strength_when_present?.toFixed(3) ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {s.win_rate_above_threshold != null
                        ? `${(s.win_rate_above_threshold * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="px-4 py-2 text-right">{s.n_above_threshold}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
