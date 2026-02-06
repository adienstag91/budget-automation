-- Migration: Add staging tables for ELT architecture
-- Run with: psql -U budget_user -d budget_db -f migrations/001_add_staging_tables.sql

-- Amazon Orders Raw Staging Table
CREATE TABLE IF NOT EXISTS amazon_orders_raw (
    -- Primary identifiers
    order_id VARCHAR(50) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    
    -- Order metadata
    website VARCHAR(50),
    order_date TIMESTAMP NOT NULL,
    purchase_order_number VARCHAR(100),
    
    -- Pricing
    currency VARCHAR(10),
    unit_price DECIMAL(10,2),
    unit_price_tax DECIMAL(10,2),
    shipping_charge DECIMAL(10,2),
    total_discounts DECIMAL(10,2),
    total_owed DECIMAL(10,2),
    shipment_item_subtotal DECIMAL(10,2),
    shipment_item_subtotal_tax DECIMAL(10,2),
    
    -- Product details
    product_name TEXT,
    product_condition VARCHAR(50),
    quantity INTEGER,
    
    -- Order status
    payment_instrument_type VARCHAR(200),
    order_status VARCHAR(50),
    shipment_status VARCHAR(50),
    ship_date TIMESTAMP,
    shipping_option VARCHAR(100),
    
    -- Addresses
    shipping_address TEXT,
    billing_address TEXT,
    
    -- Tracking
    carrier_name_tracking TEXT,
    
    -- Gift info (optional)
    gift_message TEXT,
    gift_sender_name VARCHAR(200),
    gift_recipient_contact TEXT,
    
    -- Item serial
    item_serial_number VARCHAR(100),
    
    -- Import tracking
    import_date TIMESTAMP DEFAULT NOW(),
    import_batch_id VARCHAR(50),  -- Track which import run this came from
    
    -- Enrichment tracking
    enriched BOOLEAN DEFAULT FALSE,
    enriched_date TIMESTAMP,
    matched_txn_id INTEGER,  -- FK to transactions table when matched
    
    -- Composite primary key (one row per item per order)
    PRIMARY KEY (order_id, asin),
    
    -- Index for querying unenriched orders
    CONSTRAINT fk_matched_txn FOREIGN KEY (matched_txn_id) 
        REFERENCES transactions(txn_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_amazon_enriched 
    ON amazon_orders_raw(enriched) WHERE enriched = FALSE;

CREATE INDEX IF NOT EXISTS idx_amazon_order_date 
    ON amazon_orders_raw(order_date);

CREATE INDEX IF NOT EXISTS idx_amazon_import_date 
    ON amazon_orders_raw(import_date);


-- Venmo Transactions Raw Staging Table
CREATE TABLE IF NOT EXISTS venmo_transactions_raw (
    -- Primary identifier (unique transaction ID from Venmo)
    venmo_id VARCHAR(100) NOT NULL PRIMARY KEY,
    
    -- Transaction metadata
    transaction_datetime TIMESTAMP NOT NULL,
    transaction_date DATE NOT NULL,  -- For easier date matching
    transaction_type VARCHAR(50),  -- Payment, Standard Transfer, etc.
    
    -- Amount and direction
    amount DECIMAL(10,2) NOT NULL,
    direction VARCHAR(10) NOT NULL,  -- 'debit' or 'credit'
    
    -- Parties
    from_name VARCHAR(200),
    to_name VARCHAR(200),
    
    -- Details
    note TEXT,
    
    -- Account tracking (for multi-account households)
    account_owner VARCHAR(100),  -- e.g., 'Andrew', 'Amanda'
    
    -- Import tracking
    import_date TIMESTAMP DEFAULT NOW(),
    import_batch_id VARCHAR(50),
    
    -- Enrichment tracking
    enriched BOOLEAN DEFAULT FALSE,
    enriched_date TIMESTAMP,
    matched_txn_id INTEGER,  -- FK to transactions table when matched
    
    CONSTRAINT fk_venmo_matched_txn FOREIGN KEY (matched_txn_id)
        REFERENCES transactions(txn_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_venmo_enriched 
    ON venmo_transactions_raw(enriched) WHERE enriched = FALSE;

CREATE INDEX IF NOT EXISTS idx_venmo_date 
    ON venmo_transactions_raw(transaction_date);

CREATE INDEX IF NOT EXISTS idx_venmo_type_direction 
    ON venmo_transactions_raw(transaction_type, direction);

CREATE INDEX IF NOT EXISTS idx_venmo_account_owner 
    ON venmo_transactions_raw(account_owner);


-- Add comments for documentation
COMMENT ON TABLE amazon_orders_raw IS 'Raw Amazon order history data for ELT processing. Each row is one item in an order.';
COMMENT ON TABLE venmo_transactions_raw IS 'Raw Venmo transaction data for ELT processing.';

COMMENT ON COLUMN amazon_orders_raw.enriched IS 'TRUE if this order has been matched and expanded into transactions table';
COMMENT ON COLUMN amazon_orders_raw.matched_txn_id IS 'The original AMAZON transaction ID that was deleted/expanded';

COMMENT ON COLUMN venmo_transactions_raw.enriched IS 'TRUE if this transaction has been processed (either matched to outgoing payment or expanded from cashout)';
COMMENT ON COLUMN venmo_transactions_raw.matched_txn_id IS 'The original VENMO transaction ID that was enriched/expanded';

-- Success message
SELECT 'Staging tables created successfully!' AS status;
