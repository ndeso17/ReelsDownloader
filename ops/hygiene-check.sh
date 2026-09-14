#!/usr/bin/env bash
# WP-20 hygiene + gate check script (executor helper)
# Usage: bash ops/hygiene-check.sh
# All checks pass = exit 0, otherwise exit non-zero.

set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0

pass() { echo "[PASS] $1"; ((PASS++)); }
fail() { echo "[FAIL] $1"; ((FAIL++)); }

echo "=== WP-20 Hygiene Checks ==="
echo ""

# 1. No em-dash / en-dash in tracked source/docs (excludes pyc + docs/agents/)
echo "--- Dash check (tracked source + docs only) ---"
DASH_FILES=$(git ls-files -z app/ tests/ docs/*.md 2>/dev/null | xargs -0 grep -lP '\x{2014}|\x{2013}' 2>/dev/null || true)
if [ -z "$DASH_FILES" ]; then
  pass "No em/en-dash in tracked app/tests/docs"
else
  fail "Em/en-dash found: $DASH_FILES"
fi

# 2. .gitignore covers users.json, stats.json, .tmp
echo "--- Gitignore coverage ---"
GITIGNORE=$(cat .gitignore)
for pat in "users.json" "stats.json" ".tmp"; do
  if echo "$GITIGNORE" | grep -qF "$pat"; then
    pass ".gitignore covers $pat"
  else
    fail ".gitignore missing $pat"
  fi
done

# 3. requirements.txt unchanged
echo "--- requirements.txt ---"
REQ_DIFF=$(git diff requirements.txt | wc -l | tr -d ' ')
if [ "$REQ_DIFF" = "0" ]; then
  pass "requirements.txt unchanged"
else
  fail "requirements.txt has changes ($REQ_DIFF lines)"
fi

# 4. No AGENTS.md or docs/agents/ tracked
echo "--- Agent docs not tracked ---"
AGENT_COUNT=$(git ls-files | grep -cE 'AGENTS\.md|docs/agents/' || true)
if [ "$AGENT_COUNT" = "0" ]; then
  pass "No AGENTS.md or docs/agents/ in git ls-files"
else
  fail "Agent docs leaked to tracking: $(git ls-files | grep -E 'AGENTS\.md|docs/agents/')"
fi

# 5. No .env* committed (only .env.example)
echo "--- .env files not committed ---"
ENV_COUNT=$(git ls-files | grep -cE '^\.env($|\.)' || true)
if [ "$ENV_COUNT" = "1" ]; then
  pass "Only .env.example committed (1 file)"
else
  fail ".env files in repo: $(git ls-files | grep '^\.env')"
fi

# 6. ruff check + format
echo "--- ruff ---"
if ruff check . >/dev/null 2>&1 && ruff format --check . >/dev/null 2>&1; then
  pass "ruff check + format OK"
else
  fail "ruff check or format failed"
fi

# 7. python import clean
echo "--- import check ---"
if python -c "import app.main" >/dev/null 2>&1; then
  pass "import app.main clean"
else
  fail "import app.main failed"
fi

# 8. pytest count preserved at 380
echo "--- pytest ---"
PYTEST_OUT=$(python -m pytest -q --tb=no 2>&1)
PASSED=$(echo "$PYTEST_OUT" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+')
if [ "$PASSED" = "380" ]; then
  pass "pytest: $PASSED passed"
else
  fail "pytest expected 380 passed, got: $PYTEST_OUT"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
exit "$FAIL"
