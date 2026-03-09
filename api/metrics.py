"""Prometheus metrics for the Catalog Intelligence Engine.

Metrics defined per specs.md section 14:
- Throughput: SKUs processed
- LLM failure rate
- Latency (p95 per endpoint)
- Queue backlog (PENDING_REVIEW count)
- Time-to-approval
- Human edit rate
"""

from prometheus_client import Counter, Gauge, Histogram, Summary

# --- Throughput ---
SKUS_PROCESSED = Counter(
    "catalog_skus_processed_total",
    "Total SKUs processed",
    ["operation"],  # ingestion, audit, enrichment
)

# --- LLM ---
LLM_CALLS = Counter(
    "catalog_llm_calls_total",
    "Total LLM enrichment calls",
    ["outcome"],  # success, needs_review, error
)

LLM_LATENCY = Histogram(
    "catalog_llm_latency_seconds",
    "LLM call latency in seconds",
    buckets=[0.5, 1, 2, 5, 10, 30],
)

# --- HTTP endpoint latency ---
REQUEST_LATENCY = Histogram(
    "catalog_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# --- Queue backlog ---
PENDING_REVIEW_GAUGE = Gauge(
    "catalog_pending_review_count",
    "Current count of SKUs in PENDING_REVIEW state",
)

# --- Review metrics ---
TIME_TO_APPROVAL = Summary(
    "catalog_time_to_approval_seconds",
    "Time from PENDING_REVIEW to APPROVED in seconds",
)

REVIEW_ACTIONS = Counter(
    "catalog_review_actions_total",
    "Total review actions",
    ["action"],  # approve, approve_with_edits, reject, escalate
)
