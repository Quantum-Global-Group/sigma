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
