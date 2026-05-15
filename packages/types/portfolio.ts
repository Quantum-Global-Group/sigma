export type TradeRecommendation = {
  ticker: string;
  action: "BUY" | "SELL";
  amount: number;
};

export type RebalanceMethod = "mvo" | "quantum_qaoa" | "equal_weight";

export type RebalanceResponse = {
  method: string;
  fallback: boolean;
  target_allocation: Record<string, number>;
  recommended_trades: TradeRecommendation[];
  sharpe_ratio: number | null;
  timestamp: string;
};
