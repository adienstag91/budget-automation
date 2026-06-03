# Budget Automation - Product Roadmap

## 🎯 Vision
Personal budgeting system with automated categorization, enrichment, and actionable insights for joint household finances.

---

# 🗺️ Active Roadmap (React Pivot App) — updated 2026-06-02

The frontend moved from Streamlit to a **React pivot app** (`frontend/`) backed
by **FastAPI** (`api.py`) → PostgreSQL. The Excel-style pivot (category >
subcategory > months, with drilldown + recategorize) is built and working.

Goal: get to a real production state for making budgeting decisions now that
there's regular income to manage.

## The core loop (what this whole system is for)
Each upload → rules auto-categorize most transactions → whatever's left lands in
the **needs-review** queue → you recategorize it and (optionally) create a rule →
that rule catches the same merchant **automatically next time**. So the queue
should shrink with every import. Clearing the current 96 well = fewer surprises
on the next upload. This is the feedback loop, and it's already how the pipeline
works.

## Sequencing principles
1. **DB correct & trustworthy first** — decisions need a clean, well-set-up DB.
2. **Foundations before leaves** — build what other features depend on early.
3. **Interleave quick wins** — cheap high-value items keep momentum.

## Phase 0 — DB Setup & Trust (do first)
Goal: confirm the database is set up correctly and the numbers are trustworthy
**before** the next big upload.
- [ ] **DB health pass** — confirm schema, accounts, taxonomy, and indexes are
      right; spot-check that pivot totals match reality.
- [ ] **Decide the unused tag columns** (see note below) — keep & use, or drop.
- [ ] **Clear the 96 needs-review** transactions — recategorize each and create
      rules where it makes sense, *so the next upload needs less review.*
      Needs a small **Review Queue screen** (API already supports it).
- [ ] **Import + enrichment UX** (Amazon / Venmo) — upload CSV, run enrichment,
      see results. Makes adding data self-service going forward.
- [ ] **Import newer statements** (Chase checking + credit past Jan 5) — only
      after the above, so they import into a clean system.

### Note on the "tag" columns (resolved — renamed for clarity)
There were two unrelated things confusingly both called "tag":
- The old `tag_source` / `tag_confidence` columns were **categorization
  provenance**, not tags — they record *how* each txn was categorized (`rule`,
  `llm`, `manual`, etc.) and the confidence, and drive `needs_review`.
  **Renamed to `category_source` / `category_confidence`** across DB + code.
- `trip_tag` was the **real** manual/ad-hoc tag concept. **Renamed to `tags`
  and changed to a `TEXT[]` array** (multiple tags per txn, e.g.
  `{Hawaii, anniversary}`), with a GIN index. Still empty — populated via UI when
  built. No longer trip-specific.

## Phase 1 — Core View Power (quick wins, high value)
Goal: slice the pivot the way you actually think.
- [ ] **Income vs expense filter** (nearly free — `direction` already in DB)
- [ ] **Search / view by category, subcategory, or merchant** (reuses drilldown)
- [ ] **Conditional formatting** — highlight unusually high month cells

## Phase 2 — Tagging (deprioritized — only if you want it)
Tagging is **not a priority**. The `tags TEXT[]` column already exists (empty)
with a GIN index, so the data model is done — only the UI/API remain.
- [ ] (optional) **Use `tags`** — add/remove multiple tags on a txn (drilldown)
- [ ] (optional) **Filter / total by tag** — "show everything tagged Hawaii"

## Phase 3 — Taxonomy Management (Taxonomy Management page)
Goal: manage the category tree from a dedicated FE page **without touching SQL**,
where every edit **cascades to the underlying transactions and rules**. This is the
single audited path for all future taxonomy changes.

### Why this is needed (context)
The taxonomy currently has **duplicate/parallel categories** from an earlier redesign:
the **legacy** set holds all the real data (`Housing & Utilities` 157 txns,
`Pet Care`, etc.), while a **newer near-empty** set (`Housing`, `Home`, `Charity`,
`Education`, `Personal`, `Pet`; `display_order >= 100`, created 2026-02-04) holds only
**2 stray Amazon txns total** and is referenced by **zero merchant_rules**. Both sets
appear in the recategorize dropdown, which is confusing. We deliberately deferred
cleaning these up so it goes through this page rather than hand-written SQL.

### Core capability (the reusable operation)
**Rename / merge a (sub)category and cascade** to all references in one DB
transaction. This same operation powers: consolidating the duplicates, building a
"Bills & Utilities" reorg, and any future reorganization.

### Backend
- [ ] **Category/subcategory tree CRUD** — add / rename / move / merge / delete.
- [ ] **Cascading update endpoints** (single DB transaction each):
      - rename `(category)` → updates `transactions.category`,
        `taxonomy_subcategories.category`, `merchant_rules.category`.
      - rename `(category, subcategory)` → updates `transactions` + `merchant_rules`
        composite refs.
      - merge B into A → re-point all txns/rules from B to A, then delete B.
      - move a subcategory to a different parent category.
      Mind the FKs: `transactions` and `merchant_rules` both have composite FKs to
      `taxonomy_subcategories(category, subcategory)`, and
      `taxonomy_subcategories.category` → `taxonomy_categories` is `ON DELETE CASCADE`.
      Must re-point/insert targets **before** deleting a source to avoid orphans.
- [ ] **Guardrails** — block delete of a non-empty (sub)category unless a merge target
      is given; preview affected-row counts before applying; do it transactionally so a
      partial failure rolls back.

### Frontend (new page in the app shell — the `/taxonomy` route stub already exists conceptually)
- [ ] Tree view of categories → subcategories with txn counts per node.
- [ ] Add / rename / move / merge / delete actions with an **"affects N transactions,
      M rules"** confirmation before applying.

### First jobs to run once the page exists
- [ ] **Drop the 6 empty/stray "new" categories** (`Charity`, `Education`, `Home`,
      `Housing`, `Personal`, `Pet`) — reassign the 2 stray Amazon txns into legacy
      subcategories first, then delete. (Deferred from the Northwestern fix on purpose.)
- [ ] **"Bills & Utilities" reorg** — create a `Bills & Utilities` category and move the
      recurring-bill subcategories into it (e.g. rent, gas/electric, wifi, taxes, car
      payment, **life insurance**). This is a cross-category move (pulls from
      `Housing & Utilities`, `Transportation`, …) so exact membership needs to be
      decided deliberately — do it via this page, not by hand. `Life Insurance`
      currently lives under `Housing & Utilities` as an interim home (see note below).

### Done in advance (interim, 2026-06-02 — Northwestern fix)
- [x] Added a `Life Insurance` subcategory under the legacy `Housing & Utilities`
      (will move into `Bills & Utilities` during the reorg above).
- [x] Normalizer alias `NORTHWESTERN MU → NORTHWESTERN` so ACH-style descriptions
      (`... ISA PYMENT PPD ID: ...`) match going forward; retargeted rule #35 from
      `Home Insurance` → `Life Insurance`; recategorized all 24 Northwestern txns.

## Phase 4 — Insights
Goal: understand trends, not just totals.
- [ ] **Trend-per-category** — click a category/subcategory → line chart over months
- [ ] **Dashboard home** — top categories, monthly totals, income vs expense,
      biggest movers (best once data is clean + tagged)

## Cross-cutting (whenever it fits)
- [ ] Fix the duplicate-detection bug (TECH_DEBT) **before** bulk imports
- [ ] Commit/push to GitHub so work is backed up off the laptop
- [ ] Eventually: free hosting (Vercel/Netlify + deployed API) to retire Lovable cost

---

## (Historical roadmap below — pre-React, kept for context)

## Core Principles
- **Granular visibility**: Move beyond generic categories (e.g., "Shopping/Amazon" → "Baby/Diapers", "Pet/Dog Food")
- **ELT architecture**: Import raw data once, enrich multiple times as logic improves
- **High auto-categorization**: Target 90%+ accuracy through rules + LLM fallback
- **Joint household support**: Track Andrew and Amanda's separate Venmo/Amazon but shared bank accounts

---

## ✅ Done (Weeks 1-6)

### Foundation
- [x] Database schema and migrations
- [x] CSV parsers (Chase checking + credit)
- [x] Merchant normalizer
- [x] Categorization engine (rules + LLM)
- [x] Streamlit dashboard with fuzzy search
- [x] 227 active categorization rules
- [x] 90%+ auto-categorization rate

### ELT Migration
- [x] Staging tables (amazon_orders_raw, venmo_transactions_raw)
- [x] Import scripts with deduplication
- [x] Enrichment pipelines (separate from import)

### Enrichment Phase 1
- [x] Amazon enrichment: Expand orders into line items
- [x] Venmo enrichment: Expand cashouts + enrich outgoing payments
- [x] Taxonomy redesign (Baby, Pet, Home, Health subcategories)
- [x] VENMO FROM / VENMO TO naming

---

## 🔥 This Week (Week of Feb 5)
- [ ] Test Amazon enrichment on December 2025
- [ ] Test Venmo enrichment on December 2025
- [ ] Review enriched transactions in dashboard
- [ ] Create rules for recurring purchases

---

## 📅 Next 2-3 Weeks

### Week of Feb 12: Pivot Table + Phase 2 Prep
- [ ] **Pivot table view** 🔥 (1-2 days)
  - Monthly spending by category
  - Trend indicators
  - Export to CSV
  
- [ ] **Fix LLM categorization** (1 day)
  - Debug taxonomy loader
  - Test with sample data
  
- [ ] **Import Amazon returns** (0.5 days)
  - Add returns to staging table
  - Plan Phase 2 logic

### Week of Feb 19: Amazon Phase 2
- [ ] **Amazon returns handling** (2-3 days)
  - Match returns to line items
  - Handle CC refunds
  - Track gift card credits

- [ ] **Full historical enrichment** (1 day)
  - Process all 2,010 orders (2023-2026)
  - Bulk categorization in dashboard

### Week of Feb 26: Dashboard Polish
- [ ] **Edit/delete transactions** (1-2 days)
  - Inline editing
  - Delete button
  - Bulk operations

- [ ] **Better filtering** (1 day)
  - Date ranges
  - Amount ranges
  - Multi-select categories

---

## 🎯 Month 2 (March)

### Costco Enrichment
- [ ] Research: Receipt format or API?
- [ ] Build enrichment pipeline (similar to Amazon)
- [ ] Test on historical data

### Automation (Maybe)
- [ ] Monthly import script
- [ ] Email digest
- [ ] Or: Just keep manual for now?

---

## 🚀 Month 3+ (When Ready)

### Cloud Deploy (If Needed)
- [ ] Railway or Render deployment
- [ ] Mobile-friendly dashboard
- [ ] Share with Amanda

### Nice to Haves
- [ ] Budget alerts
- [ ] Spending trends charts
- [ ] Plaid integration (direct bank connection)
- [ ] Receipt scanning (OCR)

---

## 🤷 Maybe Never / Aspirational

## 🤷 Maybe Never / Aspirational

*Stuff that would be cool but probably overkill for a personal project*

### Advanced Features
- Receipt scanning (OCR) - probably easier to just keep CSVs
- Investment tracking - Fidelity has this already
- Tax optimization - TurboTax exists
- Bill tracking - just use autopay like a normal person

### Integrations
- Plaid (direct bank connection) - $30/month vs free CSV downloads?
- YNAB-style envelope budgeting - might be too rigid
- Mobile app - Streamlit on phone browser is fine

*Keep this list for inspiration but don't feel bad about ignoring it*

---

## 📈 Success Metrics

**Current State (Feb 2026):**
- ✅ 5,863 historical transactions
- ✅ 227 categorization rules
- ✅ 90%+ auto-categorization rate
- ✅ 2,010 Amazon orders ready to enrich

**By End of Month (Feb):**
- 🎯 Pivot table view working
- 🎯 Amazon Phase 1 complete (Dec 2025 tested)
- 🎯 Venmo enrichment complete
- 🎯 <10 transactions/month need manual review

**By Mid-March:**
- 🎯 Amazon Phase 2 complete (returns handling)
- 🎯 Full historical data enriched (2023-2026)
- 🎯 95%+ auto-categorization

**When It Feels Done:**
- ✨ Can open dashboard and see spending breakdown in <30 seconds
- ✨ Monthly import + review takes <15 minutes
- ✨ Amanda can use it without asking Andrew how it works
- ✨ Actually helps make better spending decisions (the whole point!)

---

## 💭 Key Decisions

**Why ELT over ETL?**  
Amazon gives you complete history dumps every time, not just new stuff. Need to be able to re-process as we improve the logic.

**Why staging tables?**  
Can re-run imports safely without messing up enriched data. Also lets us test enrichment logic without re-importing everything.

**Why Streamlit?**  
Fast to build, Python-native, good enough for personal use. Can always rebuild in React later if needed.

**Why PostgreSQL over SQLite?**  
Better JSON support, will work in the cloud when we eventually deploy.

---

*Last updated: 2026-02-05*
