"use client";

import useSWRMutation from "swr/mutation";
import { fetchRebalance, type RebalanceResponse } from "@/lib/api";

type Args = {
  holdings: Record<string, number>;
  method: "mvo" | "quantum_qaoa" | "equal_weight";
  apiKey: string;
  riskAversion?: number;
};

async function fetcher(_key: string, { arg }: { arg: Args }): Promise<RebalanceResponse> {
  return fetchRebalance(arg.holdings, arg.method, arg.apiKey, arg.riskAversion ?? 1.0);
}

export function usePortfolio() {
  const { trigger, data, isMutating, error } = useSWRMutation("portfolio-rebalance", fetcher);

  return {
    rebalance: (args: Args) => trigger(args),
    result: data ?? null,
    loading: isMutating,
    error: error instanceof Error ? error.message : null,
  };
}
