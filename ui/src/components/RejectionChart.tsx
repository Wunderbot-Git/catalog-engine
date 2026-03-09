"use client";

interface RejectionChartProps {
  data: { reason: string; count: number }[];
}

export default function RejectionChart({ data }: RejectionChartProps) {
  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <p className="mb-2 text-sm text-gray-500">Top Rejection Reasons</p>
      <div className="space-y-2">
        {data.map((d, i) => (
          <div key={i}>
            <div className="flex justify-between text-xs mb-0.5">
              <span className="truncate">{d.reason}</span>
              <span className="font-medium">{d.count}</span>
            </div>
            <div className="h-2 bg-gray-100 rounded">
              <div
                className="h-2 bg-red-400 rounded"
                style={{ width: `${(d.count / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
        {data.length === 0 && <p className="text-gray-400 text-xs">No rejections</p>}
      </div>
    </div>
  );
}
