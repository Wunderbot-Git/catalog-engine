#!/usr/bin/env bash
# Smoke test: end-to-end verification of the Catalog Intelligence Engine stack
# Usage: ./tests/smoke_test.sh [--no-cleanup]
set -euo pipefail

# --- Config ---
API_URL="http://localhost:8080"
UI_URL="http://localhost:3000"
ADMIN_EMAIL="admin@catalog.dev"
HEALTH_TIMEOUT=90
HEALTH_INTERVAL=2

# --- Args ---
CLEANUP=true
if [[ "${1:-}" == "--no-cleanup" ]]; then
  CLEANUP=false
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.yml"

# --- Colors ---
if [[ -z "${NO_COLOR:-}" ]]; then
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; BOLD='\033[1m'; NC='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; BOLD=''; NC=''
fi

# --- Counters ---
PASSED=0; FAILED=0; SKIPPED=0
ENRICHMENT_OK=false
VERSION_ID=""

pass_step()  { ((PASSED++)); echo -e "  ${GREEN}PASS${NC}  $1"; }
fail_step()  { ((FAILED++)); echo -e "  ${RED}FAIL${NC}  $1${2:+ — $2}"; }
skip_step()  { ((SKIPPED++)); echo -e "  ${YELLOW}SKIP${NC}  $1${2:+ — $2}"; }

# --- JSON helper ---
json_field() {
  local json="$1" field="$2"
  if command -v jq &>/dev/null; then
    echo "$json" | jq -r ".$field // empty" 2>/dev/null
  else
    echo "$json" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('$field',''))" 2>/dev/null
  fi
}

# --- Cleanup ---
cleanup() {
  if $CLEANUP; then
    echo ""
    echo "Cleaning up..."
    $COMPOSE down -v --remove-orphans 2>/dev/null || true
  else
    echo ""
    echo "Containers left running (--no-cleanup). Stop with: docker compose down -v"
  fi
}
trap cleanup EXIT

# --- Steps ---

step_start_stack() {
  echo -e "\n${BOLD}Starting stack...${NC}"
  if $COMPOSE up --build -d 2>&1 | tail -5; then
    pass_step "Docker compose started"
  else
    fail_step "Docker compose failed to start"
    exit 1
  fi
}

step_wait_for_api() {
  echo -e "\n${BOLD}Waiting for API...${NC}"
  local elapsed=0
  while [[ $elapsed -lt $HEALTH_TIMEOUT ]]; do
    if curl -sf "$API_URL/health" &>/dev/null; then
      pass_step "API ready (${elapsed}s)"
      return
    fi
    sleep $HEALTH_INTERVAL
    elapsed=$((elapsed + HEALTH_INTERVAL))
  done
  fail_step "API not ready after ${HEALTH_TIMEOUT}s"
  exit 1
}

step_seed_data() {
  echo -e "\n${BOLD}Seeding dev data...${NC}"
  if $COMPOSE exec -T api python -m api.seed 2>&1; then
    pass_step "Dev data seeded"
  else
    fail_step "Seed script failed"
  fi
}

step_ingest() {
  echo -e "\n${BOLD}Ingesting test product...${NC}"
  local body='{"items":[{"sku_id":"SMOKE-001","title":"Smoke Test Laptop","brand":"TestBrand","category":"laptops","price":999.99,"source":"json"}]}'
  local resp
  resp=$(curl -sf -X POST "$API_URL/ingest/jobs" \
    -H "Content-Type: application/json" \
    -H "X-User-Email: $ADMIN_EMAIL" \
    -d "$body" 2>&1) || { fail_step "Ingest" "request failed"; return; }

  local count_ok
  count_ok=$(json_field "$resp" "count_ok")
  if [[ "$count_ok" == "1" ]]; then
    pass_step "Ingest (1 product)"
  else
    fail_step "Ingest" "count_ok=$count_ok, response: $resp"
  fi
}

step_list_skus() {
  echo -e "\n${BOLD}Listing SKUs...${NC}"
  local resp
  resp=$(curl -sf "$API_URL/skus" -H "X-User-Email: $ADMIN_EMAIL" 2>&1) || { fail_step "List SKUs" "request failed"; return; }

  if echo "$resp" | grep -q "SMOKE-001"; then
    pass_step "List SKUs (SMOKE-001 found)"
  else
    fail_step "List SKUs" "SMOKE-001 not in response"
  fi
}

step_audit() {
  echo -e "\n${BOLD}Running audit...${NC}"
  local resp
  resp=$(curl -sf -X POST "$API_URL/audit/run" \
    -H "Content-Type: application/json" \
    -H "X-User-Email: $ADMIN_EMAIL" \
    -d '{}' 2>&1) || { fail_step "Audit" "request failed"; return; }

  local processed
  processed=$(json_field "$resp" "processed")
  if [[ -n "$processed" && "$processed" != "0" ]]; then
    pass_step "Audit ($processed SKUs processed)"
  else
    fail_step "Audit" "processed=$processed, response: $resp"
  fi
}

step_enrich() {
  echo -e "\n${BOLD}Enriching SKU...${NC}"
  local http_code resp
  resp=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/skus/SMOKE-001/enrich" \
    -H "Content-Type: application/json" \
    -H "X-User-Email: $ADMIN_EMAIL" \
    -d '{}' 2>&1)
  http_code=$(echo "$resp" | tail -1)
  resp=$(echo "$resp" | sed '$d')

  if [[ "$http_code" == "200" ]]; then
    VERSION_ID=$(json_field "$resp" "version_id")
    ENRICHMENT_OK=true
    pass_step "Enrich (version: ${VERSION_ID:0:8}...)"
  else
    skip_step "Enrich" "LLM unavailable (HTTP $http_code — expected without Vertex AI credentials)"
  fi
}

step_review() {
  echo -e "\n${BOLD}Reviewing SKU...${NC}"
  if ! $ENRICHMENT_OK; then
    skip_step "Review" "skipped (no enrichment to review)"
    return
  fi
  local resp
  resp=$(curl -sf -X POST "$API_URL/skus/SMOKE-001/review" \
    -H "Content-Type: application/json" \
    -H "X-User-Email: $ADMIN_EMAIL" \
    -d "{\"action\":\"approve\",\"version_id\":\"$VERSION_ID\"}" 2>&1) || { fail_step "Review" "request failed"; return; }

  pass_step "Review (approved)"
}

step_export() {
  echo -e "\n${BOLD}Exporting...${NC}"
  local http_code
  http_code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/exports/latest" \
    -H "X-User-Email: $ADMIN_EMAIL" 2>&1)

  if [[ "$http_code" == "200" ]]; then
    pass_step "Export (HTTP 200)"
  else
    fail_step "Export" "HTTP $http_code"
  fi
}

step_dashboard() {
  echo -e "\n${BOLD}Checking dashboard...${NC}"
  local resp
  resp=$(curl -sf "$API_URL/dashboard/stats" -H "X-User-Email: $ADMIN_EMAIL" 2>&1) || { fail_step "Dashboard" "request failed"; return; }

  if echo "$resp" | grep -q "pending_review"; then
    pass_step "Dashboard stats"
  else
    fail_step "Dashboard" "unexpected response"
  fi
}

step_check_ui() {
  echo -e "\n${BOLD}Checking UI...${NC}"
  local http_code
  http_code=$(curl -s -o /dev/null -w "%{http_code}" "$UI_URL" 2>&1)

  if [[ "$http_code" == "200" ]]; then
    pass_step "UI (HTTP 200)"
  else
    fail_step "UI" "HTTP $http_code"
  fi
}

# --- Main ---
main() {
  echo -e "${BOLD}=== Catalog Intelligence Engine — Smoke Test ===${NC}"

  step_start_stack
  step_wait_for_api
  step_seed_data
  step_ingest
  step_list_skus
  step_audit
  step_enrich
  step_review
  step_export
  step_dashboard
  step_check_ui

  echo ""
  echo -e "${BOLD}=== Results: ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC}, ${YELLOW}$SKIPPED skipped${NC} ==="

  if [[ $FAILED -gt 0 ]]; then
    exit 1
  fi
}

main "$@"
