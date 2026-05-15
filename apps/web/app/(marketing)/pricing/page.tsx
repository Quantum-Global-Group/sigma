import Link from "next/link";

const PLANS = [
  {
    name: "Free",
    price: "$0",
    description: "Explore the API",
    features: ["100 signals/day", "Daily timeframe only", "Community support"],
    cta: "Get started",
    href: "/sign-up",
    highlight: false,
  },
  {
    name: "Pro",
    price: "$49/mo",
    description: "For active traders",
    features: ["10,000 signals/day", "All timeframes", "Portfolio optimizer", "Email support"],
    cta: "Start free trial",
    href: "/sign-up",
    highlight: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    description: "For institutions",
    features: ["Unlimited signals", "Quantum QAOA optimizer", "SLA + dedicated support", "Custom model training"],
    cta: "Contact us",
    href: "mailto:hello@sigma.dev",
    highlight: false,
  },
];

export default function PricingPage() {
  return (
    <main className="px-8 py-24">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-5xl font-bold text-center mb-4">Simple pricing</h1>
        <p className="text-gray-400 text-center text-xl mb-16">Start free. Upgrade when you need more.</p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={`rounded-2xl border p-8 flex flex-col ${
                plan.highlight
                  ? "border-indigo-500 bg-indigo-600/10"
                  : "border-white/10 bg-white/5"
              }`}
            >
              <h2 className="text-xl font-bold mb-1">{plan.name}</h2>
              <p className="text-3xl font-bold mb-2">{plan.price}</p>
              <p className="text-gray-400 text-sm mb-6">{plan.description}</p>
              <ul className="space-y-2 mb-8 flex-1">
                {plan.features.map((f) => (
                  <li key={f} className="text-sm text-gray-300 flex gap-2">
                    <span className="text-green-400">✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              <Link
                href={plan.href}
                className={`block text-center py-3 rounded-lg font-medium transition-colors ${
                  plan.highlight
                    ? "bg-indigo-600 hover:bg-indigo-500"
                    : "border border-white/20 hover:bg-white/10"
                }`}
              >
                {plan.cta}
              </Link>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
