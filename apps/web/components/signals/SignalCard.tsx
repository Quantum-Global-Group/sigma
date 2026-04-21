import { cn } from "@/lib/utils";
import type { SignalResponse } from "@/lib/api";

const SIGNAL_STYLES = {
  BUY: "bg-green-100 text-green-800 border-green-300",
  SELL: "bg-red-100 text-red-800 border-red-300",
  HOLD: "bg-yellow-100 text-yellow-800 border-yellow-300",
};

export function SignalCard({ signal }: { signal: SignalResponse }) {
  const pct = Math.round(signal.confidence * 100);
  const returnSign = signal.predicted_return >= 0 ? "+" : "";
  const returnPct = (signal.predicted_return * 100).toFixed(2);

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-xs text-gray-500 mb-1 uppercase tracking-wide font-medium">
            {signal.ticker} · {signal.timeframe}
          </p>
          <span
            className={cn(
              "inline-block px-4 py-1 rounded-full text-2xl font-bold border",
              SIGNAL_STYLES[signal.signal]
            )}
          >
            {signal.signal}
          </span>
        </div>
        {signal.cached && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 border border-gray-200">
            cached
          </span>
        )}
      </div>

      <div className="mb-4">
        <div className="flex justify-between text-sm mb-1">
          <span className="text-gray-500">Confidence</span>
          <span className="font-medium text-gray-800">{pct}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className={cn(
              "h-2 rounded-full",
              pct >= 70 ? "bg-green-500" : pct >= 50 ? "bg-yellow-500" : "bg-red-400"
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-gray-500">Predicted return</p>
          <p className={cn("font-semibold", signal.predicted_return >= 0 ? "text-green-700" : "text-red-700")}>
            {returnSign}{returnPct}%
          </p>
        </div>
        <div>
          <p className="text-gray-500">Model</p>
          <p className="font-medium text-gray-800">{signal.model_version}</p>
        </div>
      </div>

      <p className="text-xs text-gray-400 mt-4">
        {new Date(signal.timestamp).toLocaleString()}
      </p>
    </div>
  );
}
