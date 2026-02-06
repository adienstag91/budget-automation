# Technical Debt & Parked Items

*Items we've encountered and need to revisit*

---

## 🔴 High Priority

### LLM Categorization Broken
**Context:**
- Tried to enable LLM categorization in Amazon enrichment Phase 1
- Error: `Missing taxonomy_loader module` and taxonomy format parsing errors
- Root cause: Taxonomy structure changed (wrapper format) but LLM loader not updated

**Impact:**
- Can't auto-categorize enriched transactions with LLM
- Currently falling back to generic categories ("Shopping/Amazon", "Income/Other")
- Requires manual categorization in dashboard

**Workaround:**
- Manual categorization in dashboard Review Queue
- Create rules after categorizing a few similar items

**To Fix:**
- Debug `budget_automation/llm/taxonomy_loader.py`
- Update to handle new taxonomy.json wrapper structure
- Test with sample transactions
- Re-enable `--llm` flag in enrichment scripts

**Parked:** 2026-02-04  
**Priority:** High (blocks auto-categorization)  
**Effort:** ~2 hours

---

### CSV Import Duplicate Detection Bug
**Context:**
- When re-importing December credit statement, 15 transactions marked as "duplicates"
- One specific transaction ($41.06 Amazon on 12/3) rejected but doesn't exist in database
- Hash calculation mystery: transaction exists in CSV but import thinks it's duplicate

**Impact:**
- Had to manually INSERT missing transactions
- Unreliable deduplication could cause missing data

**Investigation Done:**
- Hash uses: `txn_date|description_raw|amount|row_index`
- Checked database for existing hash: not found
- Checked for similar transactions: not found
- Theory: Cross-statement duplicates? But transaction date doesn't overlap

**Workaround:**
- Manual INSERT for missing transactions
- Verify count after import (should match CSV row count)

**To Fix:**
- Add debug logging to `budget_automation/core/csv_parser.py`
- Print hash for each row during import
- Add `--verbose` flag to show skipped duplicates with reason
- Add validation: count imported vs CSV rows

**Parked:** 2026-02-04  
**Priority:** High (data integrity)  
**Effort:** ~3 hours

---

## 🟡 Medium Priority

### Docker Compose Version Warning
**Context:**
- Every `docker-compose` command shows:
  ```
  WARN[0000] the attribute `version` is obsolete, it will be ignored
  ```

**Impact:**
- Annoying but harmless
- Will break in future Docker Compose versions

**To Fix:**
- Remove `version:` line from `docker-compose.yml`
- Update to Compose v2 syntax

**Parked:** 2026-02-04  
**Priority:** Low (cosmetic)  
**Effort:** 5 minutes

---

### Dashboard "Source" Column Confusion
**Context:**
- Dashboard shows "Source" column but it's unclear what it represents
- Database has 3 similar fields:
  - `source`: Data source (chase_credit, amazon_enrichment, venmo_enrichment)
  - `tag_source`: Categorization method (rule, llm, manual, venmo_expanded)
  - `created_by`: Process that created it (import, amazon_enrichment, venmo_enrichment)

**Impact:**
- User confusion about what "Source" means
- Might be showing wrong field

**To Fix:**
- Clarify which field dashboard displays
- Consider renaming column or showing multiple fields
- Add tooltip explaining each field

**Parked:** 2026-02-05  
**Priority:** Medium (UX clarity)  
**Effort:** 30 minutes

---

## 🟢 Low Priority / Nice to Have

### Dashboard Edit Capabilities Missing
**Context:**
- Currently can only view/categorize transactions
- Cannot edit merchant, amount, date, or notes
- Cannot delete transactions (must use SQL)
- No bulk operations (except bulk categorize)

**Desired Features:**
- Inline editing (click to edit)
- Delete button with confirmation
- Bulk select → delete/edit
- Undo last action

**Impact:**
- Quality of life improvement
- Currently need to use SQL for corrections

**To Add:**
- Edit transaction form/modal
- Delete with confirmation dialog
- Bulk selection checkboxes
- History/undo system

**Parked:** 2026-02-05  
**Priority:** Low (can use SQL as workaround)  
**Effort:** ~3 hours per feature

---

### No Account Owner Tracking for Amazon
**Context:**
- Andrew and Amanda have separate Amazon accounts
- Both charge to joint credit card
- Currently no way to differentiate whose purchase
- Venmo solved this with `account_owner` in staging table

**Impact:**
- Can't filter "Amanda's Amazon purchases" vs "Andrew's"
- Can't track individual spending in joint account

**Options:**
1. Manual tagging in dashboard
2. Separate CSV imports with `--account-owner` flag
3. Add `account_owner` column to amazon_orders_raw

**Workaround:**
- Ignore for now (track joint spending only)
- Manually tag in notes if needed

**Parked:** 2026-02-05  
**Priority:** Low (can revisit in Phase 2)  
**Effort:** ~2 hours to implement Option 2

---

### Merchant Normalizer Edge Cases
**Context:**
- Some merchants don't normalize well:
  - "Amazon.com*BI3U66OG0" → "AMAZON" ✅
  - "AMAZON MKTPL*BI37A6142" → "AMAZON" ✅
  - But what about "Amazon Prime Video"? "Amazon Music"?
  
**Impact:**
- Might over-normalize (lose nuance)
- Might under-normalize (too fragmented)

**To Review:**
- Audit merchant_norm values
- Decide: Should "Amazon Prime Video" stay separate or merge?
- Consider: merchant_category field (Shopping vs Entertainment)

**Parked:** 2026-02-05  
**Priority:** Low (current logic works well enough)  
**Effort:** ~1 hour audit + decisions

---

### Streamlit Performance with Large Dataset
**Context:**
- Currently ~6,000 transactions loads fine
- What happens at 20,000? 50,000?
- Streamlit can be slow with large dataframes

**Impact:**
- Future scalability concern
- Might need pagination or lazy loading

**Options:**
1. Pagination (show 100 at a time)
2. Lazy loading (load as you scroll)
3. Pre-aggregate data (cache summaries)
4. Migrate to faster framework (React + FastAPI)

**Parked:** 2026-02-05  
**Priority:** Low (not a problem yet)  
**Effort:** Unknown (depends on solution)

---

### No Automated Tests
**Context:**
- Entire codebase has zero tests
- Relied on manual testing and validation
- Risky for refactoring or major changes

**Impact:**
- Can't confidently refactor
- Bugs might slip through
- New contributors would struggle

**To Add:**
- Unit tests for key functions (merchant_normalizer, csv_parser)
- Integration tests for enrichment pipelines
- End-to-end tests for dashboard flows

**Parked:** 2026-02-05  
**Priority:** Low (but should address before cloud deploy)  
**Effort:** ~16 hours to add comprehensive tests

---

## 📝 Documentation Gaps

### Missing Documentation
- [ ] README.md needs update (still references ETL architecture)
- [ ] API documentation for enrichment scripts
- [ ] Database schema diagram
- [ ] Onboarding guide for contributors
- [ ] Taxonomy design decisions (why these categories?)

---

## 🎯 Refactoring Candidates

### Code Duplication
- Amazon and Venmo enrichment have similar patterns (could extract base class)
- CSV parsers have duplicate date/amount parsing logic
- Dashboard tabs have similar filtering/display code

### Naming Inconsistencies
- `merchant_norm` vs `merchant_normalized`
- `txn_date` vs `transaction_date` vs `date`
- `source` vs `created_by` (overlapping purposes)

### Database Schema Improvements
- Consider: `enrichments` table to track enrichment history
- Consider: `audit_log` table for all changes
- Consider: `user_preferences` table for dashboard settings

---

## 💭 Future Considerations

### When to Address Tech Debt?
- **Before cloud deploy:** Fix tests, documentation, security
- **Before multi-user:** Clean up schema, add audit logs
- **Before scale:** Performance optimization, caching

### Technical Debt Budget
- Allocate 20% of time to tech debt each sprint
- Always fix high-priority debt before new features
- Document as you go (add to this file immediately)

---

*Add to this file whenever you say "let's come back to this later"*  
*Review monthly to reprioritize*
