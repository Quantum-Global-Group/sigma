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

export type SignalResponse = {
  ticker: string;
  timeframe: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  predicted_return: number;
  model_version: string;
  cached: boolean;
  timestamp: string;
};

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

export type APIKeyItem = {
  id: string;
  key_prefix: string;
  name: string | null;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked: boolean;
};

export type CreateKeyResponse = APIKeyItem & { raw_key: string };

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

export type UsageSummary = {
  user_id: string;
  plan: string;
  period_start: string;
  period_end: string;
  api_calls: number;
  limit: number;
  remaining: number;
};

export async function fetchUsage(apiKey: string): Promise<UsageSummary> {
  return apiFetch<UsageSummary>("/usage", apiKey);
}

// ─── Portfolio ───────────────────────────────────────────────────────────────

export type TradeRecommendation = {
  ticker: string;
  action: "BUY" | "SELL";
  amount: number;
};

export type RebalanceResponse = {
  method: string;
  fallback: boolean;
  target_allocation: Record<string, number>;
  recommended_trades: TradeRecommendation[];
  sharpe_ratio: number | null;
  timestamp: string;
};

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

export type BacktestRequest = {
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital?: number;
  rebalance_freq?: "daily" | "weekly" | "monthly";
};

export type BacktestResult = {
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_value: number;
  total_return: number;
  annualized_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  equity_curve: { date: string; value: number }[];
  trade_log: { date: string; ticker: string; action: string; weight: number }[];
  timestamp: string;
};

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
