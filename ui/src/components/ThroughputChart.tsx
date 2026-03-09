"use client";

interface ThroughputChartProps {
  data: { date: string; count: number }[];
}

export default function ThroughputChart({ data }: ThroughputChartProps) {
  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <p className="mb-2 text-sm text-gray-500">Approved / Last 7 Days</p>
      <div className="flex items-end gap-1 h-20">
        {data.map((d, i) => (
          <div
            key={i}
            className="flex-1 bg-blue-500 rounded-t"
            style={{ height: `${(d.count / max) * 100}%`, minHeight: d.count > 0 ? "4px" : "0" }}
            title={`${d.date?.slice(0, 10)}: ${d.count}`}
          />
        ))}
        {data.length === 0 && <p className="text-gray-400 text-xs">No data</p>}
      </div>
    </div>
  );
}
