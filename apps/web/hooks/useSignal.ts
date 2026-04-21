"use client";

import useSWRMutation from "swr/mutation";
import { fetchSignal, type SignalResponse } from "@/lib/api";

async function fetcher(
  _key: string,
  { arg }: { arg: { ticker: string; timeframe: "daily" | "4h" | "hourly"; apiKey: string } }
): Promise<SignalResponse> {
  return fetchSignal(arg.ticker, arg.timeframe, arg.apiKey);
}

export function useSignal() {
  const { trigger, data, isMutating, error } = useSWRMutation("signal", fetcher);

  return {
    getSignal: (ticker: string, timeframe: "daily" | "4h" | "hourly", apiKey: string) =>
      trigger({ ticker, timeframe, apiKey }),
    signal: data ?? null,
    loading: isMutating,
    error: error instanceof Error ? error.message : null,
  };
}
