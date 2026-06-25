--
-- PostgreSQL database dump
--

\restrict QMnoAZkaUOe2Pgh0Nb0pqhQFbIcDhlPoo79Hekc6u72WsCCVokv9eg2lchemK4S

-- Dumped from database version 16.11
-- Dumped by pg_dump version 16.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts (
    account_id integer NOT NULL,
    account_name character varying(200) NOT NULL,
    account_type character varying(50) NOT NULL,
    institution character varying(100) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: accounts_account_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounts_account_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounts_account_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounts_account_id_seq OWNED BY public.accounts.account_id;


--
-- Name: allocations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.allocations (
    allocation_id integer NOT NULL,
    txn_id integer NOT NULL,
    allocated_category character varying(100),
    allocated_subcategory character varying(100),
    allocated_amount numeric(12,2) NOT NULL,
    basis text,
    notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: allocations_allocation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.allocations_allocation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: allocations_allocation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.allocations_allocation_id_seq OWNED BY public.allocations.allocation_id;


--
-- Name: amazon_orders_raw; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.amazon_orders_raw (
    order_id character varying(50) NOT NULL,
    asin character varying(20) NOT NULL,
    website character varying(50),
    order_date timestamp without time zone NOT NULL,
    purchase_order_number character varying(100),
    currency character varying(10),
    unit_price numeric(10,2),
    unit_price_tax numeric(10,2),
    shipping_charge numeric(10,2),
    total_discounts numeric(10,2),
    total_owed numeric(10,2),
    shipment_item_subtotal numeric(10,2),
    shipment_item_subtotal_tax numeric(10,2),
    product_name text,
    product_condition character varying(50),
    quantity integer,
    payment_instrument_type character varying(200),
    order_status character varying(50),
    shipment_status character varying(50),
    ship_date timestamp without time zone,
    shipping_option character varying(100),
    shipping_address text,
    billing_address text,
    carrier_name_tracking text,
    gift_message text,
    gift_sender_name character varying(200),
    gift_recipient_contact text,
    item_serial_number character varying(100),
    import_date timestamp without time zone DEFAULT now(),
    import_batch_id character varying(50),
    enriched boolean DEFAULT false,
    enriched_date timestamp without time zone,
    matched_txn_id integer
);


--
-- Name: TABLE amazon_orders_raw; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.amazon_orders_raw IS 'Raw Amazon order history data for ELT processing. Each row is one item in an order.';


--
-- Name: COLUMN amazon_orders_raw.enriched; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amazon_orders_raw.enriched IS 'TRUE if this order has been matched and expanded into transactions table';


--
-- Name: COLUMN amazon_orders_raw.matched_txn_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amazon_orders_raw.matched_txn_id IS 'The original AMAZON transaction ID that was deleted/expanded';


--
-- Name: merchant_enrichment_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.merchant_enrichment_links (
    link_id integer NOT NULL,
    txn_id integer NOT NULL,
    provider character varying(50) NOT NULL,
    external_id character varying(200),
    match_confidence numeric(3,2),
    metadata jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: merchant_enrichment_links_link_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.merchant_enrichment_links_link_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: merchant_enrichment_links_link_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.merchant_enrichment_links_link_id_seq OWNED BY public.merchant_enrichment_links.link_id;


--
-- Name: merchant_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.merchant_rules (
    rule_id integer NOT NULL,
    rule_pack character varying(50) NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    match_type character varying(20) NOT NULL,
    match_value text NOT NULL,
    match_detail text,
    category character varying(100) NOT NULL,
    subcategory character varying(100) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by character varying(100),
    notes text
);


--
-- Name: TABLE merchant_rules; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.merchant_rules IS 'Categorization rules for automatic tagging';


--
-- Name: COLUMN merchant_rules.rule_pack; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.merchant_rules.rule_pack IS 'Grouping for rules: demo, personal, learned, manual';


--
-- Name: COLUMN merchant_rules.priority; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.merchant_rules.priority IS 'Lower number = higher priority when multiple rules match';


--
-- Name: merchant_rules_rule_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.merchant_rules_rule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: merchant_rules_rule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.merchant_rules_rule_id_seq OWNED BY public.merchant_rules.rule_id;


--
-- Name: tag_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tag_events (
    event_id integer NOT NULL,
    txn_id integer NOT NULL,
    event_type character varying(50) NOT NULL,
    payload jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: tag_events_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tag_events_event_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tag_events_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tag_events_event_id_seq OWNED BY public.tag_events.event_id;


--
-- Name: tag_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tag_overrides (
    override_id integer NOT NULL,
    txn_id integer NOT NULL,
    old_category character varying(100),
    old_subcategory character varying(100),
    old_category_source character varying(50),
    new_category character varying(100) NOT NULL,
    new_subcategory character varying(100) NOT NULL,
    reason text,
    promote_to_rule boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by character varying(100) NOT NULL
);


--
-- Name: TABLE tag_overrides; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tag_overrides IS 'Manual categorization overrides that can be promoted to rules';


--
-- Name: COLUMN tag_overrides.promote_to_rule; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tag_overrides.promote_to_rule IS 'Flag to indicate this override should become a merchant_rule';


--
-- Name: tag_overrides_override_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tag_overrides_override_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tag_overrides_override_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tag_overrides_override_id_seq OWNED BY public.tag_overrides.override_id;


--
-- Name: taxonomy_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxonomy_categories (
    category character varying(100) NOT NULL,
    display_order integer NOT NULL,
    is_income boolean DEFAULT false NOT NULL,
    is_transfer boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: taxonomy_subcategories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxonomy_subcategories (
    subcategory_id integer NOT NULL,
    category character varying(100) NOT NULL,
    subcategory character varying(100) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: taxonomy_subcategories_subcategory_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.taxonomy_subcategories_subcategory_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: taxonomy_subcategories_subcategory_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.taxonomy_subcategories_subcategory_id_seq OWNED BY public.taxonomy_subcategories.subcategory_id;


--
-- Name: transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transactions (
    txn_id integer NOT NULL,
    account_id integer NOT NULL,
    source character varying(50) NOT NULL,
    source_row_hash character varying(64) NOT NULL,
    txn_date date NOT NULL,
    post_date date NOT NULL,
    description_raw text NOT NULL,
    merchant_raw character varying(500),
    merchant_norm character varying(500),
    amount numeric(12,2) NOT NULL,
    currency character varying(3) DEFAULT 'USD'::character varying,
    direction character varying(10) NOT NULL,
    type character varying(50),
    category character varying(100),
    subcategory character varying(100),
    category_source character varying(50),
    category_confidence numeric(3,2),
    needs_review boolean DEFAULT false,
    is_return boolean DEFAULT false,
    exclude_from_budget boolean DEFAULT false,
    tags text[] DEFAULT '{}'::text[],
    notes text,
    memo text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by character varying(100),
    merchant_detail text
);


--
-- Name: TABLE transactions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.transactions IS 'Core transaction table containing all spending/income data';


--
-- Name: COLUMN transactions.source_row_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transactions.source_row_hash IS 'SHA256 hash of raw CSV row for deduplication';


--
-- Name: COLUMN transactions.merchant_norm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transactions.merchant_norm IS 'Normalized merchant name for matching rules';


--
-- Name: COLUMN transactions.category_source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transactions.category_source IS 'How the category was assigned: rule, llm, manual, venmo_expanded, none';


--
-- Name: COLUMN transactions.category_confidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transactions.category_confidence IS 'Confidence score from categorization (0.00-1.00)';


--
-- Name: COLUMN transactions.exclude_from_budget; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transactions.exclude_from_budget IS 'If TRUE, exclude from regular budget analysis';


--
-- Name: COLUMN transactions.tags; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transactions.tags IS 'Manual, ad-hoc tags (e.g. Hawaii, anniversary). Multiple per txn.';


--
-- Name: transactions_txn_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.transactions_txn_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transactions_txn_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.transactions_txn_id_seq OWNED BY public.transactions.txn_id;


--
-- Name: venmo_transactions_raw; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.venmo_transactions_raw (
    venmo_id character varying(100) NOT NULL,
    transaction_datetime timestamp without time zone NOT NULL,
    transaction_date date NOT NULL,
    transaction_type character varying(50),
    amount numeric(10,2) NOT NULL,
    direction character varying(10) NOT NULL,
    from_name character varying(200),
    to_name character varying(200),
    note text,
    account_owner character varying(100),
    import_date timestamp without time zone DEFAULT now(),
    import_batch_id character varying(50),
    enriched boolean DEFAULT false,
    enriched_date timestamp without time zone,
    matched_txn_id integer,
    funding_source character varying(200),
    destination character varying(200)
);


--
-- Name: TABLE venmo_transactions_raw; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.venmo_transactions_raw IS 'Raw Venmo transaction data for ELT processing.';


--
-- Name: COLUMN venmo_transactions_raw.enriched; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venmo_transactions_raw.enriched IS 'TRUE if this transaction has been processed (either matched to outgoing payment or expanded from cashout)';


--
-- Name: COLUMN venmo_transactions_raw.matched_txn_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venmo_transactions_raw.matched_txn_id IS 'The original VENMO transaction ID that was enriched/expanded';


--
-- Name: COLUMN venmo_transactions_raw.funding_source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venmo_transactions_raw.funding_source IS 'Venmo "Funding Source" column. "Venmo balance" => spent from balance (not on bank statement); a bank/card => bank-funded (already on bank statement).';


--
-- Name: COLUMN venmo_transactions_raw.destination; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venmo_transactions_raw.destination IS 'Venmo "Destination" column. "Venmo balance" => received into balance; a bank => cashout/instant-deposit.';


--
-- Name: accounts account_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts ALTER COLUMN account_id SET DEFAULT nextval('public.accounts_account_id_seq'::regclass);


--
-- Name: allocations allocation_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.allocations ALTER COLUMN allocation_id SET DEFAULT nextval('public.allocations_allocation_id_seq'::regclass);


--
-- Name: merchant_enrichment_links link_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_enrichment_links ALTER COLUMN link_id SET DEFAULT nextval('public.merchant_enrichment_links_link_id_seq'::regclass);


--
-- Name: merchant_rules rule_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_rules ALTER COLUMN rule_id SET DEFAULT nextval('public.merchant_rules_rule_id_seq'::regclass);


--
-- Name: tag_events event_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_events ALTER COLUMN event_id SET DEFAULT nextval('public.tag_events_event_id_seq'::regclass);


--
-- Name: tag_overrides override_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_overrides ALTER COLUMN override_id SET DEFAULT nextval('public.tag_overrides_override_id_seq'::regclass);


--
-- Name: taxonomy_subcategories subcategory_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_subcategories ALTER COLUMN subcategory_id SET DEFAULT nextval('public.taxonomy_subcategories_subcategory_id_seq'::regclass);


--
-- Name: transactions txn_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions ALTER COLUMN txn_id SET DEFAULT nextval('public.transactions_txn_id_seq'::regclass);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (account_id);


--
-- Name: allocations allocations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.allocations
    ADD CONSTRAINT allocations_pkey PRIMARY KEY (allocation_id);


--
-- Name: amazon_orders_raw amazon_orders_raw_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.amazon_orders_raw
    ADD CONSTRAINT amazon_orders_raw_pkey PRIMARY KEY (order_id, asin);


--
-- Name: merchant_enrichment_links merchant_enrichment_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_enrichment_links
    ADD CONSTRAINT merchant_enrichment_links_pkey PRIMARY KEY (link_id);


--
-- Name: merchant_rules merchant_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_rules
    ADD CONSTRAINT merchant_rules_pkey PRIMARY KEY (rule_id);


--
-- Name: tag_events tag_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_events
    ADD CONSTRAINT tag_events_pkey PRIMARY KEY (event_id);


--
-- Name: tag_overrides tag_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_overrides
    ADD CONSTRAINT tag_overrides_pkey PRIMARY KEY (override_id);


--
-- Name: taxonomy_categories taxonomy_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_categories
    ADD CONSTRAINT taxonomy_categories_pkey PRIMARY KEY (category);


--
-- Name: taxonomy_subcategories taxonomy_subcategories_category_subcategory_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_subcategories
    ADD CONSTRAINT taxonomy_subcategories_category_subcategory_key UNIQUE (category, subcategory);


--
-- Name: taxonomy_subcategories taxonomy_subcategories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_subcategories
    ADD CONSTRAINT taxonomy_subcategories_pkey PRIMARY KEY (subcategory_id);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (txn_id);


--
-- Name: transactions transactions_source_row_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_source_row_hash_key UNIQUE (source_row_hash);


--
-- Name: venmo_transactions_raw venmo_transactions_raw_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venmo_transactions_raw
    ADD CONSTRAINT venmo_transactions_raw_pkey PRIMARY KEY (venmo_id);


--
-- Name: idx_accounts_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_accounts_active ON public.accounts USING btree (is_active);


--
-- Name: idx_amazon_enriched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_amazon_enriched ON public.amazon_orders_raw USING btree (enriched) WHERE (enriched = false);


--
-- Name: idx_amazon_import_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_amazon_import_date ON public.amazon_orders_raw USING btree (import_date);


--
-- Name: idx_amazon_order_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_amazon_order_date ON public.amazon_orders_raw USING btree (order_date);


--
-- Name: idx_merchant_rules_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_merchant_rules_active ON public.merchant_rules USING btree (is_active, priority);


--
-- Name: idx_merchant_rules_match; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_merchant_rules_match ON public.merchant_rules USING btree (match_type, match_value);


--
-- Name: idx_merchant_rules_pack; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_merchant_rules_pack ON public.merchant_rules USING btree (rule_pack);


--
-- Name: idx_tag_events_payload; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_events_payload ON public.tag_events USING gin (payload);


--
-- Name: idx_tag_events_txn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_events_txn ON public.tag_events USING btree (txn_id);


--
-- Name: idx_tag_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_events_type ON public.tag_events USING btree (event_type);


--
-- Name: idx_tag_overrides_promote; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_overrides_promote ON public.tag_overrides USING btree (promote_to_rule) WHERE (promote_to_rule = true);


--
-- Name: idx_tag_overrides_txn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_overrides_txn ON public.tag_overrides USING btree (txn_id);


--
-- Name: idx_taxonomy_subcategories_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_taxonomy_subcategories_category ON public.taxonomy_subcategories USING btree (category);


--
-- Name: idx_transactions_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transactions_account ON public.transactions USING btree (account_id);


--
-- Name: idx_transactions_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transactions_category ON public.transactions USING btree (category, subcategory);


--
-- Name: idx_transactions_dates; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transactions_dates ON public.transactions USING btree (txn_date, post_date);


--
-- Name: idx_transactions_exclude_budget; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transactions_exclude_budget ON public.transactions USING btree (exclude_from_budget) WHERE (exclude_from_budget = true);


--
-- Name: idx_transactions_merchant_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transactions_merchant_norm ON public.transactions USING btree (merchant_norm);


--
-- Name: idx_transactions_needs_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transactions_needs_review ON public.transactions USING btree (needs_review) WHERE (needs_review = true);


--
-- Name: idx_transactions_tags; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transactions_tags ON public.transactions USING gin (tags);


--
-- Name: idx_venmo_account_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_venmo_account_owner ON public.venmo_transactions_raw USING btree (account_owner);


--
-- Name: idx_venmo_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_venmo_date ON public.venmo_transactions_raw USING btree (transaction_date);


--
-- Name: idx_venmo_enriched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_venmo_enriched ON public.venmo_transactions_raw USING btree (enriched) WHERE (enriched = false);


--
-- Name: idx_venmo_type_direction; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_venmo_type_direction ON public.venmo_transactions_raw USING btree (transaction_type, direction);


--
-- Name: accounts update_accounts_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_accounts_updated_at BEFORE UPDATE ON public.accounts FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: transactions update_transactions_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_transactions_updated_at BEFORE UPDATE ON public.transactions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: allocations allocations_txn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.allocations
    ADD CONSTRAINT allocations_txn_id_fkey FOREIGN KEY (txn_id) REFERENCES public.transactions(txn_id) ON DELETE CASCADE;


--
-- Name: amazon_orders_raw fk_matched_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.amazon_orders_raw
    ADD CONSTRAINT fk_matched_txn FOREIGN KEY (matched_txn_id) REFERENCES public.transactions(txn_id) ON DELETE SET NULL;


--
-- Name: venmo_transactions_raw fk_venmo_matched_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venmo_transactions_raw
    ADD CONSTRAINT fk_venmo_matched_txn FOREIGN KEY (matched_txn_id) REFERENCES public.transactions(txn_id) ON DELETE SET NULL;


--
-- Name: merchant_enrichment_links merchant_enrichment_links_txn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_enrichment_links
    ADD CONSTRAINT merchant_enrichment_links_txn_id_fkey FOREIGN KEY (txn_id) REFERENCES public.transactions(txn_id) ON DELETE CASCADE;


--
-- Name: merchant_rules merchant_rules_category_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_rules
    ADD CONSTRAINT merchant_rules_category_fkey FOREIGN KEY (category) REFERENCES public.taxonomy_categories(category);


--
-- Name: merchant_rules merchant_rules_category_subcategory_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_rules
    ADD CONSTRAINT merchant_rules_category_subcategory_fkey FOREIGN KEY (category, subcategory) REFERENCES public.taxonomy_subcategories(category, subcategory);


--
-- Name: tag_events tag_events_txn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_events
    ADD CONSTRAINT tag_events_txn_id_fkey FOREIGN KEY (txn_id) REFERENCES public.transactions(txn_id) ON DELETE CASCADE;


--
-- Name: tag_overrides tag_overrides_txn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_overrides
    ADD CONSTRAINT tag_overrides_txn_id_fkey FOREIGN KEY (txn_id) REFERENCES public.transactions(txn_id) ON DELETE CASCADE;


--
-- Name: taxonomy_subcategories taxonomy_subcategories_category_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_subcategories
    ADD CONSTRAINT taxonomy_subcategories_category_fkey FOREIGN KEY (category) REFERENCES public.taxonomy_categories(category) ON DELETE CASCADE;


--
-- Name: transactions transactions_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id);


--
-- Name: transactions transactions_category_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_category_fkey FOREIGN KEY (category) REFERENCES public.taxonomy_categories(category);


--
-- Name: transactions transactions_category_subcategory_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_category_subcategory_fkey FOREIGN KEY (category, subcategory) REFERENCES public.taxonomy_subcategories(category, subcategory) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict QMnoAZkaUOe2Pgh0Nb0pqhQFbIcDhlPoo79Hekc6u72WsCCVokv9eg2lchemK4S

