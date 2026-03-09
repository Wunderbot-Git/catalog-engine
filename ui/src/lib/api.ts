import { DashboardStats, SkuDetail, SkuListResponse, VersionEntry } from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  const email = process.env.NEXT_PUBLIC_DEV_USER_EMAIL || "admin@catalog.dev";
  return {
    "Content-Type": "application/json",
    "X-User-Email": email,
  };
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...getAuthHeaders(), ...init?.headers },
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  return apiFetch("/dashboard/stats");
}

export async function fetchSkus(params: Record<string, string> = {}): Promise<SkuListResponse> {
  const qs = new URLSearchParams(params).toString();
  return apiFetch(`/skus${qs ? `?${qs}` : ""}`);
}

export async function fetchSku(skuId: string): Promise<SkuDetail> {
  return apiFetch(`/skus/${skuId}`);
}

export async function fetchVersions(skuId: string): Promise<VersionEntry[]> {
  return apiFetch(`/skus/${skuId}/versions`);
}

export async function submitReview(skuId: string, body: Record<string, unknown>): Promise<void> {
  await apiFetch(`/skus/${skuId}/review`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function triggerEnrich(skuId: string, body: Record<string, unknown> = {}): Promise<void> {
  await apiFetch(`/skus/${skuId}/enrich`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface UserInfo {
  id: string;
  name: string;
  email: string;
  roles: { role: string; category: string | null }[];
}

export async function fetchUsers(): Promise<UserInfo[]> {
  return apiFetch("/admin/users");
}

export interface CommentEntry {
  comment_id: string;
  version_id: string;
  author_email: string;
  comment_type: string;
  body: string;
  created_at: string;
}

export async function fetchComments(skuId: string): Promise<CommentEntry[]> {
  return apiFetch(`/skus/${skuId}/comments`);
}

export async function fetchMe(): Promise<UserInfo> {
  return apiFetch("/me");
}
