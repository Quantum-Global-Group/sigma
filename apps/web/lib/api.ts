import type {
  APIKeyItem,
  AssetClass,
  BacktestRequest,
  BacktestResult,
  CreateKeyResponse,
  ExecutionStatus,
  OptionCandidate,
  OptionExposure,
  OptionPosition,
  Order,
  Position,
  RebalanceResponse,
  SignalResponse,
  UsageSummary,
} from "@sigma/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(
  path: string,
  apiKey: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ─── Signals ─────────────────────────────────────────────────────────────────

export type { SignalResponse } from "@sigma/types";

export async function fetchSignal(
  ticker: string,
  timeframe: "daily" | "4h" | "hourly" = "daily",
  apiKey: string
): Promise<SignalResponse> {
  return apiFetch<SignalResponse>("/signals", apiKey, {
    method: "POST",
    body: JSON.stringify({ ticker, timeframe }),
  });
}

// ─── API Keys ─────────────────────────────────────────────────────────────────

export type { APIKeyItem, CreateKeyResponse } from "@sigma/types";

export async function fetchKeys(apiKey: string): Promise<APIKeyItem[]> {
  return apiFetch<APIKeyItem[]>("/keys", apiKey);
}

export async function createKey(apiKey: string, name?: string): Promise<CreateKeyResponse> {
  return apiFetch<CreateKeyResponse>("/keys", apiKey, {
    method: "POST",
    body: JSON.stringify({ name: name ?? null }),
  });
}

export async function revokeKey(apiKey: string, keyId: string): Promise<void> {
  return apiFetch<void>(`/keys/${keyId}`, apiKey, { method: "DELETE" });
}

// ─── Usage ───────────────────────────────────────────────────────────────────

export type { UsageSummary } from "@sigma/types";

export async function fetchUsage(apiKey: string): Promise<UsageSummary> {
  return apiFetch<UsageSummary>("/usage", apiKey);
}

// ─── Portfolio ───────────────────────────────────────────────────────────────

export type { TradeRecommendation, RebalanceResponse } from "@sigma/types";

export async function fetchRebalance(
  holdings: Record<string, number>,
  method: "mvo" | "quantum_qaoa" | "equal_weight",
  apiKey: string,
  riskAversion: number = 1.0
): Promise<RebalanceResponse> {
  return apiFetch<RebalanceResponse>("/portfolio/rebalance", apiKey, {
    method: "POST",
    body: JSON.stringify({ holdings, method, risk_aversion: riskAversion }),
  });
}

// ─── Backtest ────────────────────────────────────────────────────────────────

export type { BacktestRequest, BacktestResult } from "@sigma/types";

export async function fetchBacktest(req: BacktestRequest, apiKey: string): Promise<BacktestResult> {
  return apiFetch<BacktestResult>("/backtest/run", apiKey, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

// ─── Signal history ──────────────────────────────────────────────────────────

export async function fetchSignalHistory(
  ticker: string,
  apiKey: string,
  timeframe: "daily" | "4h" | "hourly" = "daily",
  limit: number = 30
): Promise<SignalResponse[]> {
  return apiFetch<SignalResponse[]>(
    `/signals/${encodeURIComponent(ticker)}/history?timeframe=${timeframe}&limit=${limit}`,
    apiKey
  );
}

// ─── Trading: positions, orders, execution ───────────────────────────────────

export type { AssetClass, Position, Order, ExecutionStatus } from "@sigma/types";

export async function fetchPositions(
  apiKey: string,
  opts: { asset_class?: AssetClass; open_only?: boolean; limit?: number } = {}
): Promise<Position[]> {
  const params = new URLSearchParams();
  if (opts.asset_class) params.set("asset_class", opts.asset_class);
  params.set("open_only", String(opts.open_only ?? true));
  params.set("limit", String(opts.limit ?? 50));
  return apiFetch<Position[]>(`/positions?${params.toString()}`, apiKey);
}

export async function fetchOrders(
  apiKey: string,
  opts: { asset_class?: AssetClass; symbol?: string; limit?: number } = {}
): Promise<Order[]> {
  const params = new URLSearchParams();
  if (opts.asset_class) params.set("asset_class", opts.asset_class);
  if (opts.symbol) params.set("symbol", opts.symbol);
  params.set("limit", String(opts.limit ?? 50));
  return apiFetch<Order[]>(`/orders?${params.toString()}`, apiKey);
}

export async function fetchExecutionStatus(apiKey: string): Promise<ExecutionStatus> {
  return apiFetch<ExecutionStatus>("/execution/status", apiKey);
}

// ─── Options ─────────────────────────────────────────────────────────────────

export type { OptionCandidate, OptionExposure, OptionPosition } from "@sigma/types";

export async function fetchOptionCandidates(
  underlying: string,
  apiKey: string,
  expiry?: string,
): Promise<OptionCandidate[]> {
  const params = new URLSearchParams({ underlying });
  if (expiry) params.set("expiry", expiry);
  return apiFetch<OptionCandidate[]>(`/options/candidates?${params.toString()}`, apiKey);
}

export async function fetchOptionPositions(
  apiKey: string,
  openOnly: boolean = true,
): Promise<OptionPosition[]> {
  const params = new URLSearchParams({ open_only: String(openOnly) });
  return apiFetch<OptionPosition[]>(`/options/positions?${params.toString()}`, apiKey);
}

export async function fetchOptionExposure(apiKey: string): Promise<OptionExposure> {
  return apiFetch<OptionExposure>("/options/exposure", apiKey);
}

/**
 * Trigger a single worker tick on demand. Requires the X-Internal-Secret header
 * (the API rejects customer keys for this endpoint with 403). The secret is
 * passed as the second argument and never bundled with apiKey.
 */
export async function triggerRunCycle(
  internalSecret: string,
  asset_class: AssetClass
): Promise<{ asset_class: AssetClass; triggered: boolean }> {
  const res = await fetch(`${API_BASE}/execution/run_cycle`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Secret": internalSecret,
    },
    body: JSON.stringify({ asset_class }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `Request failed: ${res.status}`);
  }
  return res.json();
}
