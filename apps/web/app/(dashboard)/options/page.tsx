"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchOptionCandidates,
  fetchOptionExposure,
  fetchOptionPositions,
  type OptionCandidate,
  type OptionExposure,
  type OptionPosition,
} from "@/lib/api";

const DEFAULT_UNDERLYING = "AAPL";
const UNDERLYINGS = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"];

// ── helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, d = 4): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function fmtPnl(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n >= 0 ? "+" : ""}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pnlClass(n: number | null | undefined): string {
  if (!n) return "text-gray-500";
  return n > 0 ? "text-green-600" : "text-red-600";
}

function regimeBadge(regime: string): React.ReactNode {
  const map: Record<string, string> = {
    trending_up: "bg-green-50 text-green-700",
    trending_down: "bg-red-50 text-red-700",
    high_vol: "bg-orange-50 text-orange-700",
    low_vol: "bg-blue-50 text-blue-700",
    range: "bg-gray-100 text-gray-600",
    unknown: "bg-gray-50 text-gray-400",
  };
  const cls = map[regime] ?? "bg-gray-50 text-gray-400";
  return (
    <span className={`px-2 py-0.5 text-xs rounded-full font-medium ${cls}`}>
      {regime.replace("_", " ")}
    </span>
  );
}

// ── component ────────────────────────────────────────────────────────────────

export default function OptionsPage() {
  const [apiKey, setApiKey] = useState("");
  const [underlying, setUnderlying] = useState(DEFAULT_UNDERLYING);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [candidates, setCandidates] = useState<OptionCandidate[]>([]);
  const [positions, setPositions] = useState<OptionPosition[]>([]);
  const [exposure, setExposure] = useState<OptionExposure | null>(null);

  const load = useCallback(async () => {
    if (!apiKey) return;
    setLoading(true);
    setError("");
    try {
      const [cands, pos, exp] = await Promise.all([
        fetchOptionCandidates(underlying, apiKey),
        fetchOptionPositions(apiKey),
        fetchOptionExposure(apiKey),
      ]);
      setCandidates(cands);
      setPositions(pos);
      setExposure(exp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load options data");
    } finally {
      setLoading(false);
    }
  }, [apiKey, underlying]);

  // Auto-refresh every 60 s when an API key is set.
  useEffect(() => {
    if (!apiKey) return;
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [apiKey, load]);

  return (
    <div className="p-8 max-w-6xl space-y-8">
      <h1 className="text-2xl font-bold">Options Lab</h1>

      {/* Controls */}
      <div className="p-4 rounded-lg border border-gray-200 bg-gray-50 flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[260px]">
          <label className="block text-sm font-medium text-gray-700 mb-1">API key</label>
          <input
            type="text"
            placeholder="sk_live_..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Underlying</label>
          <select
            value={underlying}
            onChange={(e) => setUnderlying(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            {UNDERLYINGS.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        </div>
        <button
          onClick={load}
          disabled={!apiKey || loading}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="text-red-500 text-sm">{error}</p>}

      {/* Greeks exposure card */}
      {exposure && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-gray-900">Portfolio Exposure</h2>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">{exposure.positions_count} open position{exposure.positions_count !== 1 ? "s" : ""}</span>
              {exposure.greek_limits_ok ? (
                <span className="px-2 py-0.5 text-xs rounded-full bg-green-50 text-green-700">within limits</span>
              ) : (
                <span className="px-2 py-0.5 text-xs rounded-full bg-red-50 text-red-700">limit breach</span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-4 gap-4 text-center">
            {(["delta", "gamma", "theta", "vega"] as const).map((g) => (
              <div key={g} className="bg-gray-50 rounded-lg p-3">
                <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Net {g}</p>
                <p className="text-lg font-mono font-semibold text-gray-900">
                  {fmt(exposure.net_greeks[g], 3)}
                </p>
              </div>
            ))}
          </div>
          {exposure.greek_breaches.length > 0 && (
            <ul className="mt-3 space-y-1">
              {exposure.greek_breaches.map((b: string, i: number) => (
                <li key={i} className="text-xs text-red-600">⚠ {b}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Candidate trades */}
      <div>
        <h2 className="text-base font-semibold text-gray-900 mb-3">
          Candidate Trades — {underlying}
        </h2>
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Strategy</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Regime</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">IV Rank</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Score</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Net Δ</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Max Loss</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Max Profit</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Breakevens</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {candidates.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                    {apiKey
                      ? "No candidates — chain may be unavailable (OpenD not running) or filters too strict."
                      : "Enter an API key to load candidates."}
                  </td>
                </tr>
              )}
              {candidates.map((c, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">
                    {c.strategy.replace(/_/g, " ")}
                  </td>
                  <td className="px-4 py-3">{regimeBadge(c.regime)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {(c.iv_rank * 100).toFixed(0)}%
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-semibold text-indigo-700">
                    {c.score.toFixed(3)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {fmt(c.net_delta, 3)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-red-600">
                    ${fmt(c.max_loss, 0)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-green-600">
                    {c.max_profit >= 9_999_000 ? "∞" : `$${fmt(c.max_profit, 0)}`}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-500 text-xs">
                    {c.breakevens.map((b: number) => b.toFixed(2)).join(" / ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Open option positions */}
      <div>
        <h2 className="text-base font-semibold text-gray-900 mb-3">Open Option Positions</h2>
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Symbol (OCC)</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Underlying</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Expiry</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Strike</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Right</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Qty</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Entry</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Unreal PnL</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Real PnL</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {positions.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-gray-400">
                    {apiKey ? "No open option positions." : "Enter an API key to load positions."}
                  </td>
                </tr>
              )}
              {positions.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-xs text-gray-800">{p.symbol}</td>
                  <td className="px-4 py-3 font-medium text-gray-700">{p.underlying ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-500">{p.expiry ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {p.strike ? `$${p.strike.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-4 py-3">
                    {p.right ? (
                      <span className={`px-2 py-0.5 text-xs rounded-full font-medium ${
                        p.right === "call" ? "bg-blue-50 text-blue-700" : "bg-purple-50 text-purple-700"
                      }`}>{p.right}</span>
                    ) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-800">{fmt(p.qty, 0)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-600">{fmt(p.entry_px, 4)}</td>
                  <td className={`px-4 py-3 text-right font-mono ${pnlClass(p.unrealized_pnl)}`}>
                    {fmtPnl(p.unrealized_pnl)}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono ${pnlClass(p.realized_pnl)}`}>
                    {fmtPnl(p.realized_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-gray-400">
        Candidates require OpenD (Moomoo gateway) to be running. Positions and exposure load from DB regardless.
        Auto-refreshes every 60 seconds when an API key is set.
      </p>
    </div>
  );
}
