type Feature = {
  title: string;
  body: string;
};

const FEATURES: Feature[] = [
  {
    title: "Signals in milliseconds",
    body: "BUY / SELL / HOLD with confidence and predicted return. Cached responses don't count against your plan.",
  },
  {
    title: "Quantum portfolio optimizer",
    body: "Mean-variance optimization with an optional QAOA path. Falls back to MVO automatically if the quantum solver times out.",
  },
  {
    title: "Backtests on real history",
    body: "Run vectorized backtests across any ticker set with monthly, weekly, or daily rebalancing.",
  },
  {
    title: "First-class API keys",
    body: "Create, revoke, and rotate keys from the dashboard. Hashed at rest, cached in Redis for fast auth.",
  },
  {
    title: "Usage-based billing",
    body: "Stripe meters every paid call. Free tier for prototyping, Pro for production, Enterprise for scale.",
  },
  {
    title: "Built for production",
    body: "Sentry traces, structured JSON logs, sliding-window rate limits, and Postgres + TimescaleDB under the hood.",
  },
];

export function FeatureGrid() {
  return (
    <section className="max-w-6xl mx-auto px-8 py-20 border-t border-white/10">
      <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-3 text-center">
        Everything you need to ship a trading product
      </h2>
      <p className="text-gray-400 text-center max-w-2xl mx-auto mb-12">
        SIGMA is the boring infrastructure plus the interesting math. Use as much or as little as you need.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {FEATURES.map((f) => (
          <div
            key={f.title}
            className="rounded-xl border border-white/10 bg-white/5 p-6 hover:bg-white/[0.07] transition-colors"
          >
            <h3 className="text-lg font-semibold mb-2">{f.title}</h3>
            <p className="text-gray-400 text-sm leading-relaxed">{f.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
