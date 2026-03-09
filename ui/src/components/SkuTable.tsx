"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { SkuListItem } from "@/types/api";

interface SkuTableProps {
  items: SkuListItem[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export default function SkuTable({ items, total, page, pageSize, onPageChange }: SkuTableProps) {
  const router = useRouter();
  const [focusedRow, setFocusedRow] = useState(0);
  const tableRef = useRef<HTMLTableElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (e.key === "j" && focusedRow < items.length - 1) {
        e.preventDefault();
        setFocusedRow((r) => r + 1);
      } else if (e.key === "k" && focusedRow > 0) {
        e.preventDefault();
        setFocusedRow((r) => r - 1);
      } else if (e.key === "Enter" && items[focusedRow]) {
        e.preventDefault();
        router.push(`/skus/${items[focusedRow].sku_id}`);
      }
    },
    [focusedRow, items, router],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div>
      <table ref={tableRef} className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 px-3">SKU</th>
            <th className="py-2 px-3">Title</th>
            <th className="py-2 px-3">Brand</th>
            <th className="py-2 px-3">Category</th>
            <th className="py-2 px-3">Price</th>
            <th className="py-2 px-3">Source</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr
              key={item.sku_id}
              className={`border-b cursor-pointer hover:bg-gray-50 ${
                i === focusedRow ? "bg-blue-50" : ""
              }`}
              onClick={() => router.push(`/skus/${item.sku_id}`)}
            >
              <td className="py-2 px-3 font-mono text-xs">{item.sku_id}</td>
              <td className="py-2 px-3">{item.title}</td>
              <td className="py-2 px-3">{item.brand}</td>
              <td className="py-2 px-3">{item.category}</td>
              <td className="py-2 px-3">${item.price.toFixed(2)}</td>
              <td className="py-2 px-3">{item.source}</td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr>
              <td colSpan={6} className="py-8 text-center text-gray-400">
                No SKUs found
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {totalPages > 1 && (
        <div className="flex justify-between items-center mt-4 text-sm">
          <span className="text-gray-500">
            Page {page} of {totalPages} ({total} total)
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
              className="px-3 py-1 border rounded disabled:opacity-30"
            >
              Prev
            </button>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              className="px-3 py-1 border rounded disabled:opacity-30"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
