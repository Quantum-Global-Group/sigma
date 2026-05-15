import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export default async function BillingPage() {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  // The Stripe billing portal URL is generated server-side when the user has
  // a stripe_customer_id. For Week 2 we show the plan cards and a placeholder
  // "Manage billing" button; full portal redirect wired in Week 3 once
  // customer IDs are set via the Clerk webhook flow.
  const portalUrl: string | null = null;

  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Billing</h1>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        {[
          { name: "Free", price: "$0/mo", features: ["100 calls/day", "Daily signals"] },
          { name: "Pro", price: "$49/mo", features: ["10,000 calls/day", "All timeframes", "Portfolio optimizer"], highlight: true },
          { name: "Enterprise", price: "Custom", features: ["Unlimited calls", "Quantum QAOA", "SLA support"] },
        ].map((plan) => (
          <div
            key={plan.name}
            className={`rounded-lg border p-5 ${
              plan.highlight ? "border-indigo-400 bg-indigo-50" : "border-gray-200 bg-white"
            }`}
          >
            <h3 className="font-bold text-gray-900 mb-1">{plan.name}</h3>
            <p className="text-xl font-semibold text-gray-700 mb-3">{plan.price}</p>
            <ul className="space-y-1">
              {plan.features.map((f) => (
                <li key={f} className="text-sm text-gray-600 flex gap-2">
                  <span className="text-green-500">✓</span>
                  {f}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="font-semibold text-gray-800 mb-2">Manage subscription</h2>
        <p className="text-sm text-gray-500 mb-4">
          Upgrade, downgrade, or update payment info via the Stripe customer portal.
        </p>
        {portalUrl ? (
          <a
            href={portalUrl}
            className="inline-block px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-500"
          >
            Open billing portal
          </a>
        ) : (
          <p className="text-sm text-gray-400">
            Billing portal available once your account is linked. Contact{" "}
            <a href="mailto:hello@sigma.dev" className="text-indigo-600 underline">
              hello@sigma.dev
            </a>{" "}
            to upgrade.
          </p>
        )}
      </div>
    </div>
  );
}
