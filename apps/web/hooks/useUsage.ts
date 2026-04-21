"use client";

import useSWR from "swr";
import { fetchUsage, type UsageSummary } from "@/lib/api";

export function useUsage(apiKey: string | null) {
  const { data, error, isLoading, mutate } = useSWR<UsageSummary>(
    apiKey ? ["usage", apiKey] : null,
    ([, key]: [string, string]) => fetchUsage(key),
    { refreshInterval: 30_000 }
  );

  return { usage: data ?? null, loading: isLoading, error, refresh: mutate };
}
