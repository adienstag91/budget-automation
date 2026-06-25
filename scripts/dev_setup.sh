#!/usr/bin/env bash
# One-command local development setup.
#
# Brings up Postgres (Docker), initializes the schema + taxonomy + rules +
# accounts, and seeds synthetic demo data. Idempotent: safe to re-run (it skips
# init if the schema already exists and just reseeds). For a clean slate use
# `make reset`.
set -euo pipefail
cd "$(dirname "$0")/.."

# Support both `docker compose` (v2) and legacy `docker-compose`.
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  DC="docker-compose"
fi

# Ensure a .env exists (defaults point at the Docker Postgres on :5433).
if [ ! -f .env ]; then
  cp .env.example .env
  echo "• Created .env from .env.example"
fi

# Ensure the package + CLIs (budget-init) are installed.
if ! command -v budget-init >/dev/null 2>&1; then
  echo "• Installing package (pip install -e .) ..."
  pip install -e . >/dev/null
fi

echo "• Starting Postgres ..."
$DC up -d postgres

echo -n "• Waiting for Postgres "
for _ in $(seq 1 30); do
  if $DC exec -T postgres pg_isready -U budget_user -d budget_db >/dev/null 2>&1; then
    ready=1; break
  fi
  echo -n "."; sleep 1
done
echo
[ "${ready:-}" = "1" ] || { echo "✗ Postgres did not become ready"; exit 1; }

# Apply schema/taxonomy/rules only if the DB hasn't been initialized yet.
exists=$($DC exec -T postgres psql -U budget_user -d budget_db -tAc \
  "SELECT to_regclass('public.transactions')" 2>/dev/null | tr -d '[:space:]')
if [ "$exists" = "transactions" ]; then
  echo "• Schema already present — skipping budget-init"
else
  echo "• Initializing database (schema + taxonomy + rules + accounts) ..."
  budget-init
fi

# Only seed when the transactions table is EMPTY. The seed deletes all
# transactions before inserting synthetic rows, so auto-running it against a
# database that already has data (e.g. real data) would destroy it. If you want
# to (re)seed deliberately, run `make seed`.
txn_count=$($DC exec -T postgres psql -U budget_user -d budget_db -tAc \
  "SELECT count(*) FROM transactions" 2>/dev/null | tr -d '[:space:]')
if [ "${txn_count:-0}" = "0" ]; then
  echo "• Seeding synthetic demo data ..."
  APP_MODE=demo python -m scripts.seed_demo
else
  echo "• transactions already has ${txn_count} rows — skipping demo seed"
  echo "  (run 'make seed' to replace them with demo data on purpose)"
fi

cat <<'DONE'

✅ Local dev ready.
   Backend:  make api    (uvicorn api:app --reload --port 8000)
   Frontend: make web    (cd frontend && npm install && npm run dev → http://localhost:5173)
DONE
