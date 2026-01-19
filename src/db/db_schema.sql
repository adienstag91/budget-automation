-- Budget Automation Database Schema
-- Version 1.0

-- Drop existing tables (for clean setup)
DROP TABLE IF EXISTS tag_events CASCADE;
DROP TABLE IF EXISTS tag_overrides CASCADE;
DROP TABLE IF EXISTS merchant_rules CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS taxonomy_subcategories CASCADE;
DROP TABLE IF EXISTS taxonomy_categories CASCADE;

-- ============================================================================
-- TAXONOMY TABLES
-- ============================================================================

-- Categories (top-level)
CREATE TABLE taxonomy_categories (
    category VARCHAR(100) PRIMARY KEY,
    display_order INTEGER NOT NULL,
    is_income BOOLEAN NOT NULL DEFAULT FALSE,
    is_transfer BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Subcategories (tied to categories)
CREATE TABLE taxonomy_subcategories (
    subcategory_id SERIAL PRIMARY KEY,
    category VARCHAR(100) NOT NULL REFERENCES taxonomy_categories(category) ON DELETE CASCADE,
    subcategory VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, subcategory)
);

CREATE INDEX idx_taxonomy_subcategories_category ON taxonomy_subcategories(category);

-- ============================================================================
-- ACCOUNTS
-- ============================================================================

CREATE TABLE accounts (
    account_id SERIAL PRIMARY KEY,
    account_name VARCHAR(200) NOT NULL,
    account_type VARCHAR(50) NOT NULL, -- 'checking', 'credit', 'savings'
    institution VARCHAR(100) NOT NULL, -- 'Chase', etc.
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_accounts_active ON accounts(is_active);

-- ============================================================================
-- TRANSACTIONS (Core table)
-- ============================================================================

CREATE TABLE transactions (
    txn_id SERIAL PRIMARY KEY,
    
    -- Account & source info
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    source VARCHAR(50) NOT NULL, -- 'chase_checking', 'chase_credit', 'manual'
    source_row_hash VARCHAR(64) UNIQUE NOT NULL, -- SHA256 hash for deduplication
    
    -- Transaction dates
    txn_date DATE NOT NULL,
    post_date DATE NOT NULL,
    
    -- Description fields
    description_raw TEXT NOT NULL, -- Original bank description
    merchant_raw VARCHAR(500), -- Extracted from description
    merchant_norm VARCHAR(500), -- Normalized merchant name
    
    -- Amount & type
    amount DECIMAL(12, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    direction VARCHAR(10) NOT NULL, -- 'debit', 'credit'
    type VARCHAR(50), -- Original bank type (ACH_DEBIT, Sale, etc.)
    
    -- Categorization
    category VARCHAR(100) REFERENCES taxonomy_categories(category),
    subcategory VARCHAR(100),
    
    -- Tagging metadata
    tag_source VARCHAR(50), -- 'rule', 'llm', 'manual', 'learned'
    tag_confidence DECIMAL(3, 2), -- 0.00 to 1.00
    needs_review BOOLEAN DEFAULT FALSE,
    
    -- Special flags
    is_return BOOLEAN DEFAULT FALSE,
    exclude_from_budget BOOLEAN DEFAULT FALSE,
    trip_tag VARCHAR(100), -- 'Europe', 'Honeymoon', etc.
    
    -- Notes
    notes TEXT,
    memo TEXT, -- From bank CSV if available
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), -- 'system', 'user', 'import'
    
    -- Constraints
    FOREIGN KEY (category, subcategory) 
        REFERENCES taxonomy_subcategories(category, subcategory)
        ON DELETE SET NULL
);

-- Indexes for common queries
CREATE INDEX idx_transactions_account ON transactions(account_id);
CREATE INDEX idx_transactions_dates ON transactions(txn_date, post_date);
CREATE INDEX idx_transactions_merchant_norm ON transactions(merchant_norm);
CREATE INDEX idx_transactions_category ON transactions(category, subcategory);
CREATE INDEX idx_transactions_needs_review ON transactions(needs_review) WHERE needs_review = TRUE;
CREATE INDEX idx_transactions_trip_tag ON transactions(trip_tag) WHERE trip_tag IS NOT NULL;
CREATE INDEX idx_transactions_exclude_budget ON transactions(exclude_from_budget) WHERE exclude_from_budget = TRUE;

-- ============================================================================
-- MERCHANT RULES
-- ============================================================================

CREATE TABLE merchant_rules (
    rule_id SERIAL PRIMARY KEY,
    
    -- Rule classification
    rule_pack VARCHAR(50) NOT NULL, -- 'demo', 'personal', 'learned', 'manual'
    priority INTEGER NOT NULL DEFAULT 100, -- Lower number = higher priority
    
    -- Matching
    match_type VARCHAR(20) NOT NULL, -- 'exact', 'contains', 'startswith', 'regex'
    match_value TEXT NOT NULL,
    match_detail TEXT, -- Optional: for composite rules (e.g., SQ + "BREADS BAKERY", Zelle + "DEVI DAYCARE")
    
    -- Target category
    category VARCHAR(100) NOT NULL REFERENCES taxonomy_categories(category),
    subcategory VARCHAR(100) NOT NULL,
    
    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), -- 'system', 'user', 'learned'
    notes TEXT,
    
    -- Constraints
    FOREIGN KEY (category, subcategory) 
        REFERENCES taxonomy_subcategories(category, subcategory)
);

CREATE INDEX idx_merchant_rules_active ON merchant_rules(is_active, priority);
CREATE INDEX idx_merchant_rules_match ON merchant_rules(match_type, match_value);
CREATE INDEX idx_merchant_rules_pack ON merchant_rules(rule_pack);

-- ============================================================================
-- TAG OVERRIDES (Manual categorization changes)
-- ============================================================================

CREATE TABLE tag_overrides (
    override_id SERIAL PRIMARY KEY,
    txn_id INTEGER NOT NULL REFERENCES transactions(txn_id) ON DELETE CASCADE,
    
    -- Old values
    old_category VARCHAR(100),
    old_subcategory VARCHAR(100),
    old_tag_source VARCHAR(50),
    
    -- New values
    new_category VARCHAR(100) NOT NULL,
    new_subcategory VARCHAR(100) NOT NULL,
    
    -- Metadata
    reason TEXT,
    promote_to_rule BOOLEAN DEFAULT FALSE, -- If TRUE, should create a merchant_rule
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100) NOT NULL
);

CREATE INDEX idx_tag_overrides_txn ON tag_overrides(txn_id);
CREATE INDEX idx_tag_overrides_promote ON tag_overrides(promote_to_rule) WHERE promote_to_rule = TRUE;

-- ============================================================================
-- TAG EVENTS (Audit log for categorization)
-- ============================================================================

CREATE TABLE tag_events (
    event_id SERIAL PRIMARY KEY,
    txn_id INTEGER NOT NULL REFERENCES transactions(txn_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL, -- 'auto_tagged', 'manually_tagged', 'reviewed', 'rule_promoted'
    payload JSONB, -- Flexible storage for event details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tag_events_txn ON tag_events(txn_id);
CREATE INDEX idx_tag_events_type ON tag_events(event_type);
CREATE INDEX idx_tag_events_payload ON tag_events USING GIN (payload);

-- ============================================================================
-- FUTURE TABLES (Placeholders for Phase 4)
-- ============================================================================

-- For Amazon/Costco item-level breakdown
CREATE TABLE IF NOT EXISTS allocations (
    allocation_id SERIAL PRIMARY KEY,
    txn_id INTEGER NOT NULL REFERENCES transactions(txn_id) ON DELETE CASCADE,
    allocated_category VARCHAR(100),
    allocated_subcategory VARCHAR(100),
    allocated_amount DECIMAL(12, 2) NOT NULL,
    basis TEXT, -- 'email_receipt', 'amazon_api', 'manual'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- For linking to external data sources
CREATE TABLE IF NOT EXISTS merchant_enrichment_links (
    link_id SERIAL PRIMARY KEY,
    txn_id INTEGER NOT NULL REFERENCES transactions(txn_id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL, -- 'amazon', 'email', 'plaid'
    external_id VARCHAR(200),
    match_confidence DECIMAL(3, 2),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for transactions table
CREATE TRIGGER update_transactions_updated_at 
    BEFORE UPDATE ON transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger for accounts table
CREATE TRIGGER update_accounts_updated_at 
    BEFORE UPDATE ON accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE transactions IS 'Core transaction table containing all spending/income data';
COMMENT ON COLUMN transactions.source_row_hash IS 'SHA256 hash of raw CSV row for deduplication';
COMMENT ON COLUMN transactions.merchant_norm IS 'Normalized merchant name for matching rules';
COMMENT ON COLUMN transactions.tag_confidence IS 'Confidence score from categorization (0.00-1.00)';
COMMENT ON COLUMN transactions.trip_tag IS 'Optional tag for trips (Europe, Honeymoon, etc) to filter from budget';
COMMENT ON COLUMN transactions.exclude_from_budget IS 'If TRUE, exclude from regular budget analysis';

COMMENT ON TABLE merchant_rules IS 'Categorization rules for automatic tagging';
COMMENT ON COLUMN merchant_rules.rule_pack IS 'Grouping for rules: demo, personal, learned, manual';
COMMENT ON COLUMN merchant_rules.priority IS 'Lower number = higher priority when multiple rules match';

COMMENT ON TABLE tag_overrides IS 'Manual categorization overrides that can be promoted to rules';
COMMENT ON COLUMN tag_overrides.promote_to_rule IS 'Flag to indicate this override should become a merchant_rule';
