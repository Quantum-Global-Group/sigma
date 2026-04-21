"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

type DataPoint = {
  date: string;
  confidence: number;
  signal: "BUY" | "SELL" | "HOLD";
};

const SIGNAL_COLORS = { BUY: "#22c55e", SELL: "#ef4444", HOLD: "#eab308" };

// Static stub data for Week 2 — replaced with real history in Week 3
const STUB_DATA: DataPoint[] = [
  { date: "Apr 15", confidence: 0.62, signal: "HOLD" },
  { date: "Apr 16", confidence: 0.71, signal: "BUY" },
  { date: "Apr 17", confidence: 0.68, signal: "BUY" },
  { date: "Apr 18", confidence: 0.55, signal: "HOLD" },
  { date: "Apr 19", confidence: 0.78, signal: "BUY" },
  { date: "Apr 20", confidence: 0.81, signal: "BUY" },
  { date: "Apr 21", confidence: 0.59, signal: "HOLD" },
];

export function SignalChart({ data = STUB_DATA }: { data?: DataPoint[] }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <h3 className="text-sm font-medium text-gray-700 mb-4">Signal confidence (last 7 days)</h3>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
          <Tooltip formatter={(v: number) => `${Math.round(v * 100)}%`} />
          <Line
            type="monotone"
            dataKey="confidence"
            stroke="#6366f1"
            strokeWidth={2}
            dot={(props) => {
              const { cx, cy, payload } = props as { cx: number; cy: number; payload: DataPoint };
              return (
                <circle
                  key={`dot-${payload.date}`}
                  cx={cx}
                  cy={cy}
                  r={4}
                  fill={SIGNAL_COLORS[payload.signal]}
                  stroke="white"
                  strokeWidth={1.5}
                />
              );
            }}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-xs text-gray-400 mt-2">Dot colour: green=BUY, red=SELL, yellow=HOLD</p>
    </div>
  );
}
