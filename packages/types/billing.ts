export type UsageSummary = {
  user_id: string;
  plan: string;
  period_start: string;
  period_end: string;
  api_calls: number;
  limit: number;
  remaining: number;
};
