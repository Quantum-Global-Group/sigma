export type AssetClass = "equity" | "crypto" | "option";

export type Position = {
  id: string;
  asset_class: AssetClass;
  symbol: string;
  qty: number;
  entry_px: number;
  entry_ts: string;
  current_px: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
  closed: boolean;
  closed_at: string | null;
};

export type Order = {
  id: string;
  asset_class: AssetClass;
  symbol: string;
  ts: string;
  side: "buy" | "sell";
  qty: number;
  px: number;
  fee: number;
  slippage_bps: number | null;
  executor: string;
  external_id: string | null;
  status: string;
};

export type ExecutionStatus = {
  executor_mode: string;
  coinbase_sandbox: boolean;
  worker_asset_classes_default_crypto_seconds: number;
  worker_asset_classes_default_equity_seconds: number;
  worker_asset_classes_default_option_seconds: number;
};

export type OptionPosition = Position & {
  underlying: string | null;
  expiry: string | null;     // ISO date
  strike: number | null;
  right: "call" | "put" | null;
  multiplier: number | null;
  meta: Record<string, unknown> | null;
};

export type NetGreeks = {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
};

export type OptionCandidate = {
  underlying: string;
  strategy: string;
  score: number;
  liquidity: number;
  alignment: number;
  risk_reward: number;
  regime: string;
  iv_rank: number;
  net_delta: number;
  max_loss: number;
  max_profit: number;
  breakevens: number[];
  rationale: Record<string, unknown>;
};

export type OptionExposure = {
  net_greeks: NetGreeks;
  positions_count: number;
  greek_limits_ok: boolean;
  greek_breaches: string[];
};
