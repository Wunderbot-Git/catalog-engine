"use client";

import { useCallback, useEffect, useState } from "react";
import RejectionChart from "@/components/RejectionChart";
import SkuTable from "@/components/SkuTable";
import StatsCard from "@/components/StatsCard";
import ThroughputChart from "@/components/ThroughputChart";
import { fetchDashboardStats, fetchMe, fetchSkus, UserInfo } from "@/lib/api";
import { DashboardStats, SkuListResponse } from "@/types/api";

const STATUSES = ["PENDING_REVIEW", "APPROVED", "REJECTED", "ESCALATED", "NEEDS_REVIEW"];
const PRIORITIES = ["HIGH", "MEDIUM", "LOW"];

function getLockedCategory(user: UserInfo | null): string | null {
  if (!user) return null;
  const hasAdmin = user.roles.some((r) => r.role === "ADMIN");
  const hasGeneral = user.roles.some((r) => r.role === "REVIEWER_GENERAL");
  if (hasAdmin || hasGeneral) return null;
  const catRole = user.roles.find((r) => r.role === "REVIEWER_CATEGORY");
  return catRole?.category ?? null;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [skuData, setSkuData] = useState<SkuListResponse | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [currentUser, setCurrentUser] = useState<UserInfo | null>(null);

  const lockedCategory = getLockedCategory(currentUser);

  useEffect(() => {
    fetchMe().then(setCurrentUser).catch(() => {});
  }, []);

  // When locked category is determined, set it as a filter
  useEffect(() => {
    if (lockedCategory) {
      setFilters((f) => ({ ...f, category: lockedCategory }));
    }
  }, [lockedCategory]);

  const loadData = useCallback(async () => {
    try {
      const [s, sk] = await Promise.all([
        fetchDashboardStats(),
        fetchSkus({ ...filters, page: String(page), page_size: "20" }),
      ]);
      setStats(s);
      setSkuData(sk);
    } catch (err) {
      console.error("Failed to load dashboard data:", err);
    }
  }, [filters, page]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const updateFilter = (key: string, value: string) => {
    setPage(1);
    setFilters((f) => {
      if (!value) {
        const { [key]: _, ...rest } = f;
        return rest;
      }
      return { ...f, [key]: value };
    });
  };

  return (
    <div className="max-w-7xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

      {/* Stats widgets */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatsCard label="Pending Review" value={stats?.pending_review_count ?? 0} />
        <StatsCard label="Escalated" value={stats?.escalated_count ?? 0} />
        <ThroughputChart data={stats?.throughput ?? []} />
        <RejectionChart data={stats?.top_rejection_reasons ?? []} />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <input
          type="text"
          placeholder="Search SKU or title..."
          className="border rounded px-3 py-1.5 text-sm"
          onChange={(e) => updateFilter("search", e.target.value)}
        />
        {lockedCategory ? (
          <input
            type="text"
            value={lockedCategory}
            disabled
            className="border rounded px-3 py-1.5 text-sm bg-gray-100 text-gray-500 cursor-not-allowed"
            title="Category locked to your assignment"
          />
        ) : (
          <input
            type="text"
            placeholder="Category"
            className="border rounded px-3 py-1.5 text-sm"
            onChange={(e) => updateFilter("category", e.target.value)}
          />
        )}
        <select
          className="border rounded px-3 py-1.5 text-sm"
          onChange={(e) => updateFilter("status", e.target.value)}
          defaultValue=""
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          className="border rounded px-3 py-1.5 text-sm"
          onChange={(e) => updateFilter("priority", e.target.value)}
          defaultValue=""
        >
          <option value="">All priorities</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      {/* SKU table */}
      {skuData && (
        <SkuTable
          items={skuData.items}
          total={skuData.total}
          page={skuData.page}
          pageSize={skuData.page_size}
          onPageChange={setPage}
        />
      )}

      <p className="mt-4 text-xs text-gray-400">
        Keyboard: j/k navigate rows, Enter to open SKU
      </p>
    </div>
  );
}
