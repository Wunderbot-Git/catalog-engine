export interface DashboardStats {
  pending_review_count: number;
  escalated_count: number;
  throughput: { date: string; count: number }[];
  top_rejection_reasons: { reason: string; count: number }[];
}

export interface SkuListItem {
  sku_id: string;
  title: string;
  brand: string;
  category: string;
  price: number;
  attributes: Record<string, unknown>;
  source: string;
  updated_at: string;
}

export interface SkuListResponse {
  items: SkuListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface Enrichment {
  version_id: string;
  generated_by: string;
  use_case_tags: string[];
  persona_tags: string[];
  trust_signals: Record<string, unknown>;
  agent_summary: string;
  confidence_score: number;
  evidence_fields: string[];
  created_at: string;
  review_status: string;
}

export interface AuditInfo {
  audit_id: string;
  completeness_score: number;
  richness_score: number;
  missing_critical_fields: string[];
  low_quality_fields: string[];
  priority_for_enrichment: string;
}

export interface SkuDetail extends SkuListItem {
  enrichment: Enrichment | null;
  audit: AuditInfo | null;
}

export interface VersionEntry {
  version_id: string;
  parent_version_id: string | null;
  generated_by: string;
  model_name: string | null;
  use_case_tags: string[];
  persona_tags: string[];
  trust_signals: Record<string, unknown>;
  agent_summary: string;
  confidence_score: number;
  evidence_fields: string[];
  created_at: string;
  review_status: string;
  reviewer_id: string | null;
  reviewed_at: string | null;
}
