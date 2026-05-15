export type SignalAction = "BUY" | "SELL" | "HOLD";

export type SignalTimeframe = "daily" | "4h" | "hourly";

export type SignalRequest = {
  ticker: string;
  timeframe?: SignalTimeframe;
};

export type SignalResponse = {
  ticker: string;
  timeframe: string;
  signal: SignalAction;
  confidence: number;
  predicted_return: number;
  model_version: string;
  cached: boolean;
  timestamp: string;
};
