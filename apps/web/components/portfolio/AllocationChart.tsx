"use client";

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const COLORS = ["#6366f1", "#22c55e", "#eab308", "#ef4444", "#06b6d4", "#a855f7", "#f97316", "#10b981"];

type Slice = { name: string; value: number };

function _toSlices(allocation: Record<string, number>): Slice[] {
  return Object.entries(allocation).map(([name, value]) => ({ name, value: Math.round(value * 10000) / 100 }));
}

export function AllocationChart({
  current,
  target,
}: {
  current: Record<string, number>;
  target: Record<string, number>;
}) {
  const currentSlices = _toSlices(current);
  const targetSlices = _toSlices(target);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <ChartCard title="Current allocation" data={currentSlices} />
      <ChartCard title="Target allocation" data={targetSlices} />
    </div>
  );
}

function ChartCard({ title, data }: { title: string; data: Slice[] }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <h3 className="text-sm font-medium text-gray-700 mb-3">{title}</h3>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            outerRadius={70}
            label={(entry) => `${entry.name} ${entry.value}%`}
          >
            {data.map((_, i) => (
              <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number) => `${v}%`} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
