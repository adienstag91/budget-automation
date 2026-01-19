# Square/Toast Merchant Learning - How It Works

## The Problem

**Square (SQ)** and **Toast (TST)** are payment processors, not actual businesses.

Your historical data shows:
- **SQ**: 266 transactions across 17 different categories
- **TST**: 159 transactions across 7 different categories

The same merchant (`SQ` or `TST`) appears for completely different businesses like:
- Coffee shops (Breads Bakery, Blue Bottle)
- Restaurants (Arata Sushi, Long Island Bagel)
- Therapy sessions
- Concert ticket booths
- etc.

## The Solution: Composite Rules

We extract the actual **business name** from the transaction description and store it as `merchant_detail`:

```
Raw Description: "SQ *BREADS BAKERY"
↓
merchant_norm: "SQ"
merchant_detail: "BREADS BAKERY"
```

Then we create **composite rules** that match on BOTH:
- `merchant_norm` = "SQ"
- `merchant_detail` = "BREADS BAKERY"

## The Learning Workflow

### First Time You See a Square Business

**Scenario**: Transaction for "SQ *BLUE BOTTLE COFFEE" comes in

1. **System checks rules**
   - Looks for rule: `SQ` + `BLUE BOTTLE COFFEE`
   - Not found
   
2. **Flags for review**
   - Transaction goes to review queue
   - Shows you: "SQ: BLUE BOTTLE COFFEE"
   
3. **You categorize it**
   - You select: Food & Drink / Coffee
   - Click "Save & Create Rule"
   
4. **System creates composite rule**
   ```sql
   INSERT INTO merchant_rules 
   (rule_pack, priority, match_type, match_value, match_detail, category, subcategory)
   VALUES 
   ('personal', 50, 'exact', 'SQ', 'BLUE BOTTLE COFFEE', 'Food & Drink', 'Coffee');
   ```

### Second Time You See That Business

**Scenario**: Another transaction for "SQ *BLUE BOTTLE COFFEE"

1. **System checks rules**
   - Finds rule: `SQ` + `BLUE BOTTLE COFFEE` → Food & Drink / Coffee
   
2. **Auto-categorizes**
   - ✅ Automatically tagged
   - No manual review needed
   - You never see it again

### Different Square Business

**Scenario**: New transaction for "SQ *ARATA SUSHI"

1. **System checks rules**
   - Finds general `SQ` rule (if exists)
   - Does NOT find specific `SQ` + `ARATA SUSHI` rule
   
2. **Flags for review**
   - Goes to review queue
   - You categorize as Food & Drink / Restaurant
   
3. **New rule created**
   - Now you have rules for both businesses

## Example Rules Table

After reviewing a few Square merchants:

| Rule ID | Match Value | Match Detail | Category | Subcategory | Priority |
|---------|-------------|--------------|----------|-------------|----------|
| 1001 | SQ | BREADS BAKERY | Food & Drink | Coffee | 50 |
| 1002 | SQ | BLUE BOTTLE COFFEE | Food & Drink | Coffee | 50 |
| 1003 | SQ | ARATA SUSHI | Food & Drink | Restaurant | 50 |
| 1004 | SQ | HEADWAY | Health & Wellness | Therapy | 50 |
| 1005 | SQ | MSG BOX OFFICE | Entertainment | Concert | 50 |

## The Same Works For:

### Zelle Transactions
```
Raw: "Zelle payment to Devi Daycare  27420707612"
↓
merchant_norm: "ZELLE TO"
merchant_detail: "DEVI DAYCARE"
↓
Rule: ZELLE TO + DEVI DAYCARE → Baby / Daycare
```

### Toast POS Merchants
```
Raw: "TST* Long Island Bagel Ca"
↓
merchant_norm: "TST"
merchant_detail: "LONG ISLAND BAGEL CA"
↓
(First time: review, then create rule)
```

### Other Payment Processors
- **SP** (another POS system)
- Any other payment processor we encounter

## Smart Prioritization

Rules have priorities (lower number = higher priority):

1. **Priority 10**: Manual overrides (Zelle to Devi, Zelle from Dad, etc.)
2. **Priority 50**: Learned composite rules (SQ + specific business)
3. **Priority 100**: General learned rules (AMAZON, COSTCO, etc.)

This means:
- Manual rules always win
- Specific business rules beat general rules
- Your preferences are always respected

## Expected Review Volume

Based on your historical data:

**Square (SQ) - 266 transactions:**
- Estimated unique businesses: ~30-40
- After reviewing 30 merchants once: 236+ auto-categorized ✅

**Toast (TST) - 159 transactions:**
- Estimated unique businesses: ~15-20  
- After reviewing 15 merchants once: 144+ auto-categorized ✅

**Zelle - 75 transactions:**
- Estimated unique payees: ~8-10
- After reviewing 8 payees once: 67+ auto-categorized ✅

## UI Flow (Preview)

### Review Queue Screen

```
┌─────────────────────────────────────────────────────────┐
│ 🔍 Review Queue (12 transactions)                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ Transaction #1                                           │
│ Date: 01/15/2025                                        │
│ Amount: -$18.50                                         │
│ Description: SQ *BLUE BOTTLE COFFEE                     │
│                                                          │
│ Merchant: SQ                                            │
│ Business: BLUE BOTTLE COFFEE                            │
│                                                          │
│ Category:    [Food & Drink ▼]                           │
│ Subcategory: [Coffee ▼]                                 │
│                                                          │
│ [ ] Save only (this transaction)                        │
│ [✓] Save & Create Rule (future transactions too)        │
│                                                          │
│ [Skip] [Save]                                           │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

When you click "Save & Create Rule", the system:
1. Updates this transaction's category
2. Creates a rule: `SQ` + `BLUE BOTTLE COFFEE` → Food & Drink / Coffee
3. Auto-categorizes all future transactions from this business
4. Removes them from review queue

## Benefits

✅ **Learn once, apply forever**
- Categorize each business once
- All future transactions auto-categorized

✅ **Scales with your spending**
- More businesses = more rules = higher automation

✅ **Flexible & accurate**
- Different Square businesses can have different categories
- Your therapy at "SQ *HEADWAY" won't be confused with coffee at "SQ *BREADS BAKERY"

✅ **Respects your choices**
- System learns YOUR categorization preferences
- Not some generic AI guess

## Already Created

We've already created 3 manual high-priority rules:

1. **ZELLE TO + DEVI DAYCARE → Baby / Daycare**
   - Your daycare payments
   
2. **ZELLE FROM + ROBERT DIENSTAG → Income / Family Support**
   - Your dad's weekly support
   
3. **EAST PARK BEVERAGE → Food & Drink / Alcohol**
   - Fixed from the historical ambiguity

These are in `/data/manual_rules.sql` and ready to be loaded.

## Next Steps

1. **Phase 1**: Build the categorization orchestrator
   - Load learned rules (195 high-confidence)
   - Load manual rules (3 + any you add)
   - Apply rules with proper priority
   - Flag unknowns for review
   
2. **Phase 2**: Build Streamlit review UI
   - Show review queue
   - Allow categorization
   - "Save & Create Rule" button
   - Bulk operations for similar merchants

3. **Phase 3**: Dashboard & analytics
   - See where money is going
   - Filter by trip tags
   - Track trends over time

---

**Status**: Ready to build Phase 1! 🚀
