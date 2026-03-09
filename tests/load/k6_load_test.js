/**
 * k6 Load Test — Catalog Intelligence Engine
 *
 * Validates 1,000 SKU scale per specs.md.
 *
 * Usage:
 *   k6 run tests/load/k6_load_test.js
 *
 * Environment variables:
 *   BASE_URL    — API base URL (default: http://localhost:8000)
 *   AUTH_EMAIL  — admin email for X-User-Email header (default: admin@test.com)
 *   SKU_COUNT   — number of SKUs to ingest (default: 1000)
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const AUTH_EMAIL = __ENV.AUTH_EMAIL || "admin@test.com";
const SKU_COUNT = parseInt(__ENV.SKU_COUNT || "1000", 10);

// Custom metrics
const errorRate = new Rate("errors");
const ingestionDuration = new Trend("ingestion_duration_ms");
const auditDuration = new Trend("audit_duration_ms");
const enrichDuration = new Trend("enrich_duration_ms");

const headers = {
  "Content-Type": "application/json",
  "X-User-Email": AUTH_EMAIL,
};

export const options = {
  scenarios: {
    // Phase 1: Ingest 1,000 SKUs in batches
    ingestion: {
      executor: "shared-iterations",
      vus: 5,
      iterations: Math.ceil(SKU_COUNT / 50), // 50 items per batch
      maxDuration: "5m",
      exec: "ingestBatch",
      startTime: "0s",
    },
    // Phase 2: Run audit on all SKUs
    audit: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "5m",
      exec: "runAudit",
      startTime: "5m",
    },
    // Phase 3: Enrich a sample of SKUs
    enrichment: {
      executor: "constant-arrival-rate",
      rate: 10, // 10 requests per second
      timeUnit: "1s",
      duration: "2m",
      preAllocatedVUs: 20,
      maxVUs: 50,
      exec: "enrichSku",
      startTime: "10m",
    },
    // Phase 4: Simulate reviewer throughput
    review: {
      executor: "constant-vus",
      vus: 5,
      duration: "2m",
      exec: "reviewSku",
      startTime: "12m",
    },
    // Phase 5: Export and Algolia sync
    exports: {
      executor: "shared-iterations",
      vus: 2,
      iterations: 5,
      maxDuration: "2m",
      exec: "exportAndSync",
      startTime: "14m",
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<5000"], // p95 < 5s
    errors: ["rate<0.05"], // <5% error rate
    ingestion_duration_ms: ["p(95)<10000"],
    audit_duration_ms: ["p(95)<30000"],
    enrich_duration_ms: ["p(95)<15000"],
  },
};

function generateSku(index) {
  return {
    sku_id: `LOAD-${String(index).padStart(5, "0")}`,
    title: `Load Test Product ${index}`,
    brand: `Brand${index % 20}`,
    category: ["laptops", "smartphones", "tablets", "headphones", "monitors"][index % 5],
    price: 99.99 + (index % 900),
    source: "json",
    attributes: {
      ram: `${8 + (index % 4) * 8}GB`,
      storage: `${256 * (1 + (index % 4))}GB`,
      color: ["black", "silver", "white", "blue"][index % 4],
    },
  };
}

export function ingestBatch() {
  const batchSize = 50;
  const vuId = __VU;
  const iterationId = __ITER;
  const startIdx = iterationId * batchSize;

  const items = [];
  for (let i = 0; i < batchSize && startIdx + i < SKU_COUNT; i++) {
    items.push(generateSku(startIdx + i));
  }

  if (items.length === 0) return;

  const res = http.post(
    `${BASE_URL}/ingest/jobs`,
    JSON.stringify({ items }),
    { headers, tags: { name: "ingest" } }
  );

  ingestionDuration.add(res.timings.duration);
  const success = check(res, {
    "ingest status 200": (r) => r.status === 200,
    "ingest count_ok > 0": (r) => {
      const body = r.json();
      return body && body.count_ok > 0;
    },
  });
  errorRate.add(!success);
}

export function runAudit() {
  const res = http.post(
    `${BASE_URL}/audit/run`,
    JSON.stringify({}),
    { headers, tags: { name: "audit" }, timeout: "120s" }
  );

  auditDuration.add(res.timings.duration);
  const success = check(res, {
    "audit status 200": (r) => r.status === 200,
    "audit processed > 0": (r) => {
      const body = r.json();
      return body && body.processed > 0;
    },
  });
  errorRate.add(!success);
}

export function enrichSku() {
  const skuIndex = Math.floor(Math.random() * SKU_COUNT);
  const skuId = `LOAD-${String(skuIndex).padStart(5, "0")}`;

  const res = http.post(
    `${BASE_URL}/skus/${skuId}/enrich`,
    JSON.stringify({}),
    { headers, tags: { name: "enrich" } }
  );

  enrichDuration.add(res.timings.duration);
  const success = check(res, {
    "enrich status 200 or 404": (r) => r.status === 200 || r.status === 404,
  });
  errorRate.add(!success);
  sleep(0.1);
}

export function reviewSku() {
  // Get a list of SKUs to review
  const listRes = http.get(
    `${BASE_URL}/skus?status=PENDING_REVIEW&page_size=10`,
    { headers, tags: { name: "list_skus" } }
  );

  if (listRes.status !== 200) {
    errorRate.add(true);
    sleep(1);
    return;
  }

  const data = listRes.json();
  if (!data.items || data.items.length === 0) {
    sleep(1);
    return;
  }

  // Review a random SKU from the list
  const sku = data.items[Math.floor(Math.random() * data.items.length)];
  if (!sku.enrichment || !sku.enrichment.version_id) {
    sleep(1);
    return;
  }

  const action = Math.random() < 0.8 ? "approve" : "reject";
  const body = {
    action,
    version_id: sku.enrichment.version_id,
  };
  if (action === "reject") {
    body.rejection_reason = "Load test rejection";
  }

  const res = http.post(
    `${BASE_URL}/skus/${sku.sku_id}/review`,
    JSON.stringify(body),
    { headers, tags: { name: "review" } }
  );

  const success = check(res, {
    "review status 200": (r) => r.status === 200,
  });
  errorRate.add(!success);
  sleep(0.5);
}

export function exportAndSync() {
  group("export", () => {
    const res = http.get(`${BASE_URL}/exports/latest`, {
      headers,
      tags: { name: "export" },
    });
    check(res, { "export status 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("algolia_sync", () => {
    const res = http.post(`${BASE_URL}/algolia/sync`, "{}", {
      headers,
      tags: { name: "algolia_sync" },
    });
    check(res, { "algolia sync status 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  sleep(1);
}
