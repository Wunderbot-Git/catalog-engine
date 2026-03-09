"use client";

interface StatsCardProps {
  label: string;
  value: number;
  className?: string;
}

export default function StatsCard({ label, value, className = "" }: StatsCardProps) {
  return (
    <div className={`rounded-lg border bg-white p-4 shadow-sm ${className}`}>
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold">{value}</p>
    </div>
  );
}
