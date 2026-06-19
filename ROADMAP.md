# Budget Automation — Roadmap

_Last updated: 2026-06-19_

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
- **Amazon enrichment (Phase 1)** — import all orders (matched *and* unmatched),
  expand each into per-item line items, soft-supersede the matched card charge
  (`exclude_from_budget`) instead of deleting, record the payment source in notes
  (credit card vs. "unknown / possibly gift card"), and send everything to the
  Review Queue for a manual pass. CLI + Import UI (upload → preview → commit).
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
- [ ] **Amazon enrichment — returns & refunds (Phase 2)** — the real accuracy
      fix. Today a return double-distorts the books: the line item still counts as
      spend *and* the card refund lands as stray income/uncategorized credit.
      - [ ] _Quick win first:_ read `payment_instrument_type` (already captured at
            import, currently ignored) to label payment source from Amazon's own
            data instead of inferring it purely from "did a card charge match."
            Sharpens the gift-card/partial cases for free.
      - [ ] Import the Amazon **Returns/Refunds** export into a staging table
            (`amazon_returns_raw`), same upload → preview → commit flow.
      - [ ] Auto-mark returned line items (`is_return`, and exclude/net them out)
            so a returned purchase stops counting as spend.
      - [ ] Match the **card refund credit** back to the original order/item and
            net it against the original category, rather than leaving it as a
            floating income/credit row.
- [ ] **Amazon enrichment — gift cards & partial payments (Phase 3)** — later;
      lower frequency, higher complexity.
      - [ ] Gift-card balance tracking — treat gift-card-funded orders as drawing
            down a tracked balance, not as card spend.
      - [ ] Partial-payment splitting — one order paid part gift card / part card
            won't match the card charge on total; split line items across funding
            sources (these fall through as "unmatched/unknown" today).
- [ ] **More enrichment sources** — line-item enrichment for Costco, Target, etc.
      (same pattern as Amazon: expand a generic store charge into its items, or
      ingest an itemized receipt/order export).

## 🌥️ Productionizing (to use day-to-day + share)
- [ ] **Host in the cloud** — deploy the API + frontend + Postgres so it's usable
      off this laptop (e.g. Fly.io / Render / Railway; managed Postgres).
- [ ] **Password protection / auth** — so the household (e.g. spouse) can log in
      and use it. Start with simple auth; multi-user later.
- [ ] **Demo data + privacy** — separate the real spending DB from a shareable
      **demo seed**: a script that populates synthetic/anonymized transactions so
      the app can be demoed publicly without exposing real finances. (Pair with
      scrubbing real data from git history — see below.)
- [ ] **Automated data sync** _(ambitious — the big quality-of-life win)_ —
      auto-fetch + import data instead of manual export/upload: bank transactions
      via an aggregator API (e.g. Plaid) for Chase, and scripted/scheduled
      retrieval of Amazon order history and Venmo statements. Goal: imports happen
      on a schedule, not by hand.

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
