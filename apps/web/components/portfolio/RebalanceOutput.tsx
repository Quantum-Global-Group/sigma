import type { RebalanceResponse } from "@/lib/api";

export function RebalanceOutput({ result }: { result: RebalanceResponse }) {
  const trades = result.recommended_trades;

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="p-5 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-800">Recommended trades</h3>
          <p className="text-xs text-gray-500 mt-1">
            Method: <span className="font-medium">{result.method}</span>
            {result.fallback && (
              <span className="ml-2 px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700 text-xs">
                fell back from quantum
              </span>
            )}
          </p>
        </div>
        {result.sharpe_ratio !== null && (
          <div className="text-right">
            <p className="text-xs text-gray-500">Sharpe ratio</p>
            <p className="font-bold text-gray-800">{result.sharpe_ratio.toFixed(2)}</p>
          </div>
        )}
      </div>

      {trades.length === 0 ? (
        <div className="p-6 text-center text-sm text-gray-400">
          Portfolio is already balanced — no trades recommended.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-left px-5 py-3 font-medium text-gray-600">Ticker</th>
              <th className="text-left px-5 py-3 font-medium text-gray-600">Action</th>
              <th className="text-right px-5 py-3 font-medium text-gray-600">Amount (USD)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {trades.map((t, i) => (
              <tr key={i}>
                <td className="px-5 py-3 font-mono text-gray-800">{t.ticker}</td>
                <td className="px-5 py-3">
                  <span
                    className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                      t.action === "BUY" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    }`}
                  >
                    {t.action}
                  </span>
                </td>
                <td className="px-5 py-3 text-right font-medium text-gray-800">
                  ${t.amount.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
