import { redirect } from "next/navigation";

import { PlanBadge } from "@/components/billing/PlanBadge";
import { UsageMeter } from "@/components/billing/UsageMeter";
import { getAuthUserId } from "@/lib/clerk";

export default async function DashboardPage() {
  const userId = await getAuthUserId();
  if (!userId) redirect("/sign-in");

  // In a full implementation the user's active key would come from the DB.
  // For Week 2, we show the UI structure with a prompt to enter a key.
  const usage = null as null | {
    plan: string;
    api_calls: number;
    limit: number;
    remaining: number;
    period_start: string;
    period_end: string;
  };

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-bold mb-6">Overview</h1>

      {usage ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <p className="text-sm text-gray-500 mb-1">Current plan</p>
            <PlanBadge plan={usage.plan} />
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <p className="text-sm text-gray-500 mb-1">API calls this period</p>
            <p className="text-2xl font-bold text-gray-900">{usage.api_calls.toLocaleString()}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <p className="text-sm text-gray-500 mb-1">Remaining calls</p>
            <p className="text-2xl font-bold text-gray-900">{usage.remaining.toLocaleString()}</p>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 bg-white p-6 mb-8">
          <p className="text-gray-500 text-sm">
            Create an API key on the{" "}
            <a href="/dashboard/api-keys" className="text-indigo-600 underline">
              API Keys
            </a>{" "}
            page to see your usage here.
          </p>
        </div>
      )}

      {usage && (
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-700 mb-3">
            Billing period: {usage.period_start} → {usage.period_end}
          </p>
          <UsageMeter used={usage.api_calls} limit={usage.limit} />
        </div>
      )}

      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4">
        <a
          href="/dashboard/signals"
          className="rounded-lg border border-gray-200 bg-white p-5 hover:border-indigo-300 transition-colors"
        >
          <h3 className="font-semibold text-gray-800 mb-1">Signal explorer</h3>
          <p className="text-sm text-gray-500">Run a signal for any ticker and see BUY/SELL/HOLD.</p>
        </a>
        <a
          href="/dashboard/api-keys"
          className="rounded-lg border border-gray-200 bg-white p-5 hover:border-indigo-300 transition-colors"
        >
          <h3 className="font-semibold text-gray-800 mb-1">API Keys</h3>
          <p className="text-sm text-gray-500">Create and revoke API keys for programmatic access.</p>
        </a>
      </div>
    </div>
  );
}
