export type AssetClass = "equity" | "crypto";

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
};
