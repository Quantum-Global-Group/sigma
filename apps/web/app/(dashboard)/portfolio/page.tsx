"use client";

import { useState } from "react";
import { HoldingsInput } from "@/components/portfolio/HoldingsInput";
import { AllocationChart } from "@/components/portfolio/AllocationChart";
import { RebalanceOutput } from "@/components/portfolio/RebalanceOutput";
import { usePortfolio } from "@/hooks/usePortfolio";

export default function PortfolioPage() {
  const { rebalance, result, loading, error } = usePortfolio();
  const [currentAllocation, setCurrentAllocation] = useState<Record<string, number>>({});

  async function handleSubmit(
    holdings: Record<string, number>,
    method: "mvo" | "quantum_qaoa" | "equal_weight",
    apiKey: string
  ) {
    const total = Object.values(holdings).reduce((a, b) => a + b, 0);
    const current: Record<string, number> = {};
    for (const [ticker, amount] of Object.entries(holdings)) {
      current[ticker] = amount / total;
    }
    setCurrentAllocation(current);

    await rebalance({ holdings, method, apiKey });
  }

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-bold mb-6">Portfolio optimizer</h1>

      <div className="rounded-lg border border-gray-200 bg-white p-6 mb-6">
        <HoldingsInput onSubmit={handleSubmit} loading={loading} />
        {error && <p className="mt-3 text-sm text-red-500">{error}</p>}
      </div>

      {result && (
        <>
          <div className="mb-6">
            <AllocationChart current={currentAllocation} target={result.target_allocation} />
          </div>
          <RebalanceOutput result={result} />
        </>
      )}
    </div>
  );
}
