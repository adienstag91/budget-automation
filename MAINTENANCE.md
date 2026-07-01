# Maintenance & Operations

How to develop, test, deploy, and look after this app day to day. For the
deeper one-time setup runbook (history scrub, first Railway deploy, data
migration, read-only DB role), see `DEPLOY.md`.

## Mental model: two separate worlds

- **Your laptop** — `make api` + `make web` + local Docker Postgres. Your
  workshop: where you build and test. Nothing here affects the live site.
- **Railway** — the published apps running in the cloud. Independent of your
  laptop. Editing code locally does nothing to them until you explicitly deploy.

| Environment | Where | Data | Auth | URL |
| --- | --- | --- | --- | --- |
| **Local dev** | your laptop | local Docker Postgres (sandbox) | none | http://localhost:5173 |
| **Demo** | Railway `budget-demo` | synthetic seed | none (public) | https://budget-demo-production.up.railway.app |
| **Production** | Railway `budget-prod` | real data | password gate (`APP_PASSWORD`) | https://budget-prod-production.up.railway.app |

"Demo vs real" is just *which database the app points at* (`DATABASE_URL`) plus
whether the password gate is on (`APP_PASSWORD`) — same code, different env vars.

## The loop: develop → test → deploy

### 1. Develop & test locally (always first)
```bash
make api      # terminal 1 — backend on :8000
make web      # terminal 2 — frontend on :5173 (proxies /api to :8000)
```
Open http://localhost:5173. It auto-reloads as you edit (uvicorn `--reload`
restarts on `.py` changes; Vite hot-reloads the frontend). This runs against your
**local** database — a safe sandbox. `make api`/`make web` are **local only**;
the live site does not use them (in the cloud it's one container that serves both
the built frontend and the API).

First-time / fresh machine:
```bash
make dev      # Postgres + schema + (synthetic seed only if the DB is empty)
```
`make dev` will NOT seed a database that already has rows — it won't clobber real
data. To deliberately (re)seed demo data: `make seed`.

### 2. Deploy to production
```bash
railway status                      # confirm you're linked to budget-prod (see gotcha #1)
railway up --service budget-prod    # rebuilds the container + deploys (~2–3 min)
```
Changes go live at the prod URL after the deploy finishes. The
"Failed to stream build logs" message is cosmetic — the build runs server-side;
check `railway logs` / the dashboard.

There is **no auto-deploy** for Railway right now — deploys are manual via
`railway up`. (`.github/workflows/deploy.yml` targets Fly.io and is unused.)

## Three things to watch out for

1. **Check which project you're linked to before `railway up`.** You have *two*
   Railway projects (prod + demo). `railway up` deploys to whatever the current
   directory is linked to. Always `railway status` first. To switch:
   `railway link` and pick the project.

2. **Code vs. data vs. schema.**
   - **Code change** → `railway up`. Ships code only.
   - **Data** → lives in Railway Postgres and persists across deploys. You don't
     redeploy data.
   - **Schema change** (new column/table/constraint) → `railway up` ships the
     code, but the change does **not** auto-apply to the prod database. You must
     run the schema change against prod Postgres separately (see "Schema
     changes" below). A code/DB mismatch is what caused the early prod 500s.

3. **Stage risky changes on demo first.** `railway link` → budget-demo →
   `railway up` → verify on the demo URL → then do prod. Safer than testing on
   live data.

Good habit: `git commit` + `git push` as you go (clean history; needed if you
wire up auto-deploy later).

## Common operations

```bash
# Status / which project + services
railway status

# Live logs of the prod app
railway logs --service budget-prod

# List/inspect a service's env vars (values are shown — your terminal only)
railway variables --service budget-prod

# Set an env var (triggers a redeploy). Reference another service's var with
# single quotes so the shell doesn't mangle ${{...}}:
railway variables --service budget-prod --set 'DATABASE_URL=${{Postgres.DATABASE_URL}}'

# Force a fresh deploy (use when a var change didn't roll a new container live)
railway up --service budget-prod

# Get / create the public URL
railway domain --service budget-prod
```

Re-run categorization after importing new data (rules + LLM over the review
queue), against whichever DB your shell points at:
```bash
curl -X POST https://budget-prod-production.up.railway.app/api/transactions/recategorize-review
```
(Needs `ANTHROPIC_API_KEY` set on the service for the LLM step; `/api/health` is
the only endpoint exempt from the password gate.)

## Database

- **Prod data** lives in the Railway `Postgres` service. The app reaches it over
  Railway's private network via the internal `DATABASE_URL`
  (`postgres.railway.internal`).
- **Backups:** periodically dump prod and keep it somewhere private. Over the
  public proxy URL (Postgres service → Variables → `DATABASE_PUBLIC_URL`):
  ```bash
  docker compose exec -T postgres pg_dump --no-owner --no-privileges \
    "$PROD_PUBLIC_URL" > backup.sql      # or run pg_dump directly if installed
  ```
  Test a restore at least once.
- **Schema changes against prod:** apply the SQL to the prod DB over the public
  URL, e.g.:
  ```bash
  export DATABASE_URL='<prod DATABASE_PUBLIC_URL>'
  docker compose exec -T postgres psql "$DATABASE_URL" -c "ALTER TABLE ... ;"
  unset DATABASE_URL
  ```
  Keep `budget_automation/db/db_schema.sql` in sync with the real schema (it had
  drifted before — regenerate from the live DB with `pg_dump --schema-only` if in
  doubt).
- **Troubleshooting reads:** use a read-only role so you can't mutate data — see
  `DEPLOY.md` ("Troubleshooting production safely").

## Secrets & security

- Secrets live in Railway service **Variables** (or local `.env`, which is
  gitignored) — never in git.
- **Never paste real secrets into chats / issues / PRs.** If one leaks, rotate
  it: API keys in the Anthropic Console; `APP_PASSWORD` by editing the variable;
  DB credentials by resetting them in Railway (or disable the public proxy, see
  below).
- Prod env vars: `DATABASE_URL` (reference to Postgres), `APP_MODE=real`,
  `APP_USERNAME`, `APP_PASSWORD`, `ANTHROPIC_API_KEY`. The demo sets
  `APP_MODE=demo` and no `APP_PASSWORD`.

## Outstanding follow-ups

- [x] **Prod Postgres public proxy disabled** — app uses the internal URL, so
  the leaked DB password is no longer usable from outside. Re-enable temporarily
  (Railway → Postgres → Settings → Networking) only when you need laptop access
  for a backup/schema change, then disable again.
- [x] **`APP_PASSWORD` rotated** — the value exposed during setup is dead.
- [x] **Sensitive git history purged** — GitHub confirmed the old commits +
  `amazon_products_analysis.csv` return 404 (verified). Repo is safe to publish.
- [ ] **Make the repo public** — now unblocked; flip it in GitHub → Settings →
  General → Danger Zone when ready. (Publishes code only; prod stays private.)
- [ ] Optional: wire **Railway auto-deploy** (connect the GitHub repo) so pushes
  redeploy automatically instead of manual `railway up`.

## See also
- `DEPLOY.md` — full setup runbook, history scrub, read-only role, data migration.
- `ROADMAP.md` — feature backlog, productionizing status, tech debt.
- `CLAUDE.md` — architecture and conventions.
