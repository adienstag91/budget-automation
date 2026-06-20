# Deployment & Data Privacy

How this app goes from "runs on one laptop" to "real data private, reachable
anywhere, code public with a demo." Read the architecture, then follow the
phases in order.

## Architecture: code is public, data is private

The repository (code) is public. Your **real spending data never lives in git** —
it lives only in a managed Postgres that sits behind authentication. "Demo mode"
vs "real mode" is **not** a toggle inside one database; it's *which database the
app connects to* (`DATABASE_URL`) plus *whether auth is enforced*. Same code,
three environments:

| Environment    | Data                                  | Auth                | Used by                          |
| -------------- | ------------------------------------- | ------------------- | -------------------------------- |
| **Production** | real spending, managed cloud Postgres | Cloudflare Access   | you + spouse, any device         |
| **Demo**       | synthetic seed (`scripts/seed_demo`)  | public / none       | public showcase                  |
| **Local dev**  | synthetic seed in Docker Postgres     | none                | you locally + Claude Code on web |

Because the public/demo surface points at a *different database*, it physically
cannot contain real data — even if there's a bug. Claude Code web sessions clone
**code only** and run against the demo seed, so dev work never touches real data.

---

## ⚠️ Phase 0 — Scrub real data from git history (DO THIS BEFORE GOING PUBLIC)

`amazon_products_analysis.csv` (real purchase data) is no longer tracked but
**still exists in git history** and is recoverable from any clone. `.gitignore`
only prevents *future* commits. Before flipping the repo to public:

```bash
# 1. Fresh clone (git-filter-repo wants a clean mirror)
cd /tmp && git clone https://github.com/adienstag91/budget-automation scrub && cd scrub

# 2. Remove the file from ALL history
pip install git-filter-repo
git filter-repo --path amazon_products_analysis.csv --invert-paths

# 3. Re-add origin (filter-repo strips it on purpose) and force-push every ref
git remote add origin https://github.com/adienstag91/budget-automation
git push origin --force --all
git push origin --force --tags
```

Caveats (important):
- This **rewrites history**. Any existing clones/branches must be re-cloned.
  You're the only dev, so coordinate with yourself: re-clone your laptop copy
  after pushing.
- GitHub may keep the old blob cached for a while; once the repo has been public
  with this file, treat the contents as **already exposed**. The scrub prevents
  *future* discovery, not past leaks.
- Sweep for other accidental data before going public:
  `git log --all --diff-filter=A --name-only -- '*.csv' '*.CSV'`

---

## Phase 1 — Foundation (done in code)

- `DATABASE_URL` support in `budget_automation/utils/db_connection.py` and the
  inline connector in `api.py`. Managed hosts inject this; local dev still uses
  the `DB_*` vars and Docker Postgres.
- This runbook + roadmap entries.

## Phase 2 — Make it deployable (done in code)

- **`Dockerfile`** — multi-stage: `vite build` the React app, then run FastAPI
  (uvicorn) serving both the built static bundle and `/api` from one container.
  api.py serves `frontend/dist` (with SPA fallback) when it's present.
- **`scripts/seed_demo.py`** — `APP_MODE=demo python -m scripts.seed_demo`
  generates deterministic synthetic transactions across ~14 months. Refuses to
  run unless `APP_MODE=demo` (or `--force`) so it can't wipe a real DB.
- **Demo banner** — `/api/config` reports the mode; the React shell shows a
  "Demo — synthetic data" banner when `APP_MODE=demo`.
- **`fly.toml`** — the public demo app (`budget-automation-demo`), with a
  `/api/health` check.
- **`.dockerignore` / `.env.example`** — keep the image free of data/secrets and
  document the env vars.

## Phase 3 — Go live

### Recommended stack
- **Host:** Fly.io (single always-on container + Fly Postgres, ~$5–15/mo,
  automated backups).
- **Auth:** Cloudflare Access (Zero Trust) in front — email allow-list (you +
  spouse) + MFA, **no auth code in the app**.

### 3a. Deploy the public demo first (no real data — safe to get wrong)
```bash
flyctl launch --no-deploy           # generates/inspects fly.toml
flyctl postgres create              # a small managed Postgres (the demo DB)
flyctl postgres attach <db-name>    # injects DATABASE_URL secret
flyctl secrets set APP_MODE=demo
flyctl deploy
# one-time: run the schema + demo seed against the demo DB
flyctl ssh console -C "python -m budget_automation.cli.init_db"
flyctl ssh console -C "python -m scripts.seed_demo"
```
Result: a public URL showing synthetic data. This proves the pipeline without
risking anything.

### 3b. Stand up private production
```bash
flyctl postgres create              # a SEPARATE Postgres for real data
flyctl apps create budget-prod      # or a second Fly app
flyctl postgres attach <prod-db> -a budget-prod
flyctl secrets set APP_MODE=real ANTHROPIC_API_KEY=sk-... -a budget-prod
flyctl deploy -a budget-prod
```

### 3c. Migrate your real data (one-time, never via git)
```bash
# Dump local real DB, restore into managed prod DB over a secure tunnel.
pg_dump "postgresql://budget_user:...@localhost:5433/budget_db" -Fc -f real.dump
flyctl proxy 5544:5432 -a budget-prod &        # tunnel to managed Postgres
pg_restore --clean --no-owner -d "$PROD_DATABASE_URL" real.dump
rm real.dump                                    # do not keep dumps around
```

### 3d. Lock it down with Cloudflare Access
1. Put the prod app behind a Cloudflare-proxied hostname (orange cloud), or use a
   `*.fly.dev` host fronted by Cloudflare.
2. Cloudflare dashboard → **Zero Trust → Access → Applications** → add a
   self-hosted app for the prod hostname.
3. Policy: **Allow** emails `you@…` and `spouse@…`. Enable a one-time-PIN or
   Google login. Everyone else is blocked before the request ever reaches the app.

---

## Operations

- **Secrets** live in `flyctl secrets` (or the host's store), never in git:
  `DATABASE_URL` (auto from attach), `ANTHROPIC_API_KEY`, `APP_MODE`,
  `REVIEW_THRESHOLD`.
- **Backups:** Fly Postgres snapshots automatically; do a periodic
  `pg_dump` to a private encrypted location and **test a restore** at least once.
- **Imports** (Chase/Amazon/Venmo CSVs) happen through the hosted UI over HTTPS,
  behind Access — your statements never touch git.
- **Redeploy:** push to `main` → `flyctl deploy` (or wire a GitHub Action that
  deploys on merge, using a Fly API token stored as a repo secret).

---

## Troubleshooting production safely (read-only access)

The real DB is private: it's not publicly exposed, and Cloudflare Access only
guards the HTTP app, not the Postgres port. You reach it over a WireGuard tunnel
from an authenticated machine. **Who can read it = whoever you hand the
connection string to.** Claude Code on the web clones *code only* and has no
tunnel, so it can't reach prod by default. Local Claude Code runs as you — if
your `.env`/tunnel exposes the DB it can query it, asking before each command.

To make any troubleshooting (yours or Claude's) incapable of mutating data, use
a **read-only role** instead of the owner credentials.

### One-time: create a read-only role
```bash
# Open a tunnel to the managed Postgres, then connect as the owner.
flyctl proxy 5544:5432 -a budget-prod &
psql "$PROD_DATABASE_URL"      # owner connection (from `flyctl postgres attach`)
```
```sql
-- Least-privilege read-only login.
CREATE ROLE budget_ro LOGIN PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE budget_db TO budget_ro;
GRANT USAGE ON SCHEMA public TO budget_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO budget_ro;
-- Cover future tables too:
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO budget_ro;
```

### Each time you (or Claude Code locally) troubleshoot
```bash
flyctl proxy 5544:5432 -a budget-prod &          # tunnel
export TROUBLESHOOT_URL="postgresql://budget_ro:...@localhost:5544/budget_db"
psql "$TROUBLESHOOT_URL" -c "SELECT category, count(*) FROM transactions GROUP BY 1;"
```
`budget_ro` can only `SELECT` — no `UPDATE`/`DELETE`/`DROP` — so worst case is a
read. Keep the owner `DATABASE_URL` out of any environment you don't fully trust;
hand out `TROUBLESHOOT_URL` (read-only) for debugging instead.
