# Budget Automation - Product Roadmap

## 🎯 Vision
Personal budgeting system with automated categorization, enrichment, and actionable insights for joint household finances.

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
