# Active Tasks & Current Sprint

*Updated: 2026-02-05*

---

## 🔥 In Progress (This Week)

### Phase 1 Testing & Validation
- [ ] **Test Amazon enrichment on December 2025**
  - Run: `python budget_automation/core/amazon_enrichment.py --expand --start-date 2025-12-01`
  - Verify: 12 orders → 16 line items
  - Confirm: Generic "AMAZON" transactions deleted, replaced with detailed line items
  - Check: All marked `needs_review=TRUE`, `source='amazon_enrichment'`

- [ ] **Test Venmo enrichment on December 2025**
  - Run: `python budget_automation/core/venmo_enrichment.py --expand`
  - Verify: 6 cashouts expanded, ~10 outgoing enriched
  - Confirm: `VENMO FROM` / `VENMO TO` naming works
  - Check: Notes include Venmo account (@Andrew or @Amanda)

- [ ] **Dashboard review of enriched transactions**
  - Open: `streamlit run budget_automation/dashboard.py`
  - Navigate to: Review Queue tab
  - Filter by: `created_by = 'amazon_enrichment'` or `'venmo_enrichment'`
  - Bulk categorize similar items:
    - IAMS dog food → Pet/Dog Food
    - Pampers diapers → Baby/Diapers & Wipes
    - Venmo from Robert → Income/Family Support

### Rules Creation
- [ ] **Create rules for recurring purchases**
  - IAMS → Pet/Dog Food
  - Pampers/Huggies → Baby/Diapers & Wipes
  - Baby Brezza → Baby/Formula & Feeding
  - Stop & Shop → Food & Drink/Groceries
  - Trader Joe's → Food & Drink/Groceries

---

## 📋 Up Next (This Sprint)

### Amazon Enrichment - Phase 2 Prep
- [ ] **Import returns data**
  - File: `Retail_CustomerReturns_1_1.csv`
  - Add to staging table: `amazon_returns_raw`
  - Schema: order_id, return_date, amount, reason

- [ ] **Plan Phase 2 logic**
  - Match returns to enriched line items
  - Mark items as returned
  - Handle CC refunds automatically
  - Track gift card credits

### Dashboard Enhancements
- [ ] **Add pivot table view** 🔥
  - Monthly spending by category
  - Expandable rows (category → subcategories)
  - Trend indicators (↑ ↓ spending vs last month)
  - Export to CSV

- [ ] **UX: Edit transactions inline**
  - Click to edit merchant/category/amount
  - Delete button (with confirmation)
  - Undo last action

### Full Historical Enrichment
- [ ] **Run Amazon enrichment on full dataset**
  - Start date: 2023-01-01 (3 years)
  - Expected: 299 orders → ~414 line items
  - Monitor: Match rate, duplicate handling
  - Document: Any edge cases or failures

---

## ⏸️ Blocked / Waiting

*None currently*

---

## 🎯 Backlog (Prioritized)

### High Priority
1. **Fix LLM categorization** 
   - Context: Taxonomy loader broken (wrapper structure issue)
   - Impact: Can't auto-categorize enriched transactions
   - Effort: ~2 hours debugging

2. **Pivot table view**
   - Impact: Primary feature request
   - Effort: ~4 hours (Streamlit dataframe grouping)

3. **Costco enrichment**
   - Impact: 2nd biggest merchant after Amazon
   - Effort: Similar to Amazon (~8 hours)
   - Research needed: Receipt format or API?

### Medium Priority
4. **Amazon Phase 2 (returns)**
   - Impact: Complete Amazon enrichment story
   - Effort: ~4 hours
   - Blocker: Need to import returns CSV first

5. **Monthly automation**
   - Impact: Reduces manual work
   - Effort: ~6 hours (cron + email alerts)
   - Consider: Plaid integration vs manual CSV drops

6. **Dashboard edit capabilities**
   - Impact: Quality of life improvement
   - Effort: ~3 hours per feature (edit/delete/bulk)

### Low Priority
7. **Cloud deployment (AWS/Railway)**
   - Impact: Mobile access, always-on
   - Effort: ~16 hours (infra + migration)
   - Can wait until: Core features complete

8. **Multi-user (Amanda separate login)**
   - Impact: Better UX for joint household
   - Effort: ~8 hours (auth + filters)
   - Can wait until: Cloud deployed

---

## 📅 This Week's Goal

**By Sunday Feb 9:**
- ✅ Phase 1 enrichment tested and validated
- ✅ 10+ categorization rules created
- ✅ Dashboard review queue workflow confirmed
- 🎯 Ready to start Phase 2 or pivot table view (decide Friday)

---

## 💡 Ideas / Notes

- Consider adding a "Category Suggestions" feature in review queue
  - Show: "Other IAMS purchases were categorized as Pet/Dog Food"
  - Button: "Apply to all IAMS purchases"

- Dashboard color coding:
  - 🟢 Green: High confidence auto-categorized
  - 🟡 Yellow: Needs review
  - 🔴 Red: Uncategorized / failed

- Exploration: Can we use Amazon API instead of CSV?
  - Pros: Real-time data, no manual export
  - Cons: Rate limits, auth complexity
  - Research: Amazon Advertising API vs MWS

---

*Use this file to track week-to-week progress. Review on Fridays to plan next week.*
