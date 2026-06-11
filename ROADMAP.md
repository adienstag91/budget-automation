# Budget Automation — Roadmap

_Last updated: 2026-06-10_

## Vision
A personal budgeting system for joint household finances: import bank/Venmo/Amazon
data, auto-categorize most of it with learned rules, enrich the opaque bits
(Amazon line items, Venmo balance activity), and surface actionable insights.

## Architecture
React pivot app (`frontend/`) → FastAPI (`api.py`) → PostgreSQL (Docker, port 5433).
See `README.md` for setup and run instructions.

## The core loop
Each import → rules auto-categorize most transactions → the rest lands in the
**Review Queue** → you categorize it and (optionally) create a rule → that rule
catches the same merchant automatically next time. The queue shrinks with every
import.

---

## ✅ Done
- **Pivot** — category › subcategory › months, drilldown, inline recategorize;
  views: spending / income / everything (transfers netted, refunds offset).
- **Import** — Chase CSV, Amazon, Venmo, each with upload → preview → commit
  (nothing written until approved). Per-source "last imported" dates.
- **Amazon enrichment** — expand orders into line items; soft-supersede the card
  charge (`exclude_from_budget`) instead of deleting.
- **Venmo enrichment** — balance-aware, funding-source ingestion: classifies each
  Venmo row by Funding Source / Destination, ingests balance income/expense as
  real transactions, and supersedes the matching bank cashout. Deterministic
  (replaced the old subset-sum). Includes a reset endpoint for clean re-runs.
- **Dashboard** — period selector (last month / this month / YTD / all);
  income / expenses / **savings** / net (scoped to real spending, transfers
  excluded); spikes & dips vs trailing median; top categories; major purchases.
- **Rules** management UI · **Taxonomy** management UI · **Review Queue** (+ LLM
  re-run of the whole queue).
- **Transactions** — filter/search/sort, bulk recategorize, inline edit, tags,
  `exclude_from_budget` surfaced (excluded badge + "Hide excluded" toggle),
  **CSV export** of the filtered view.
- **SQL transparency** — "Show SQL" behind Pivot / Transactions / Rules / Stats.

## 🔜 Now / Next
- [ ] **Clear the Review Queue** (~82, inflated by the newly-ingested Venmo
      income/expense rows) — categorize + create rules so future imports need less.
- [ ] **Saved filter presets** on Transactions (save & re-apply common filters).
- [ ] **Budgets / targets** — set a monthly target per category, track actual vs
      target (over/under) on the Dashboard or a dedicated page.

## 🌥️ Productionizing (to use day-to-day + share)
- [ ] **Host in the cloud** — deploy the API + frontend + Postgres so it's usable
      off this laptop (e.g. Fly.io / Render / Railway; managed Postgres).
- [ ] **Password protection / auth** — so the household (e.g. spouse) can log in
      and use it. Start with simple auth; multi-user later.
- [ ] **Demo data + privacy** — separate the real spending DB from a shareable
      **demo seed**: a script that populates synthetic/anonymized transactions so
      the app can be demoed publicly without exposing real finances. (Pair with
      scrubbing real data from git history — see below.)

## 🧹 Tech debt / cleanup
- Real Amazon analysis CSV was untracked (2026-06-10) but **still exists in git
  history** — scrub if the repo goes public (`git filter-repo`).
- Venmo: surface the funding-source classification + a re-run control in the
  Import UI (currently API-only).
- See `TECH_DEBT.md` for the running list.

## Known limitations
- Venmo enrichment only reconciles cashouts **within the staged statement period**
  and for **balance-affecting** payments; bank/card-funded Venmo payments (e.g.
  rent) are already on the bank statement and are relabeled, not re-ingested.
- Taxonomy is the DB source of truth; `data/taxonomy/taxonomy.json` is retired.
