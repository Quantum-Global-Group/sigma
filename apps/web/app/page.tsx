import Link from "next/link";
import { MarketingNav } from "@/components/marketing/MarketingNav";
import { FeatureGrid } from "@/components/marketing/FeatureGrid";
import { GumroadStrip } from "@/components/marketing/GumroadStrip";
import { Footer } from "@/components/layout/Footer";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 to-gray-900 text-white flex flex-col">
      <MarketingNav />

      <section className="flex flex-col items-center text-center px-8 py-32 max-w-4xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 text-indigo-300 text-sm mb-8 border border-indigo-500/30">
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
          Quantum-enhanced portfolio optimization
        </div>

        <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 leading-tight">
          AI trading signals
          <br />
          <span className="text-indigo-400">that actually work</span>
        </h1>

        <p className="text-xl text-gray-400 mb-10 max-w-2xl leading-relaxed">
          SIGMA combines machine learning signal generation with quantum portfolio
          optimization. Get a BUY/SELL/HOLD signal with confidence score on any ticker
          in milliseconds.
        </p>

        <div className="flex flex-col sm:flex-row gap-4">
          <Link
            href="/sign-up"
            className="px-8 py-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 transition-colors font-semibold text-lg"
          >
            Start free trial
          </Link>
          <Link
            href="/docs"
            className="px-8 py-4 rounded-lg border border-white/20 hover:bg-white/5 transition-colors font-semibold text-lg"
          >
            View API docs
          </Link>
        </div>
      </section>

      <section className="max-w-4xl mx-auto px-8 pb-20 w-full">
        <div className="rounded-xl border border-white/10 bg-white/5 p-8 font-mono text-sm">
          <p className="text-gray-500 mb-4"># Generate a signal with one API call</p>
          <p className="text-green-400">
            curl -X POST https://api.sigma.dev/signals \
          </p>
          <p className="text-green-400 pl-4">
            -H &quot;Authorization: Bearer sk_live_...&quot; \
          </p>
          <p className="text-green-400 pl-4">
            -d &apos;&#123;&quot;ticker&quot;: &quot;AAPL&quot;&#125;&apos;
          </p>
          <div className="mt-4 pt-4 border-t border-white/10 text-gray-300">
            <pre>{`{
  "signal": "BUY",
  "confidence": 0.7821,
  "predicted_return": 0.0234,
  "model_version": "v1.0"
}`}</pre>
          </div>
        </div>
      </section>

      <FeatureGrid />
      <GumroadStrip />
      <Footer />
    </div>
  );
}
