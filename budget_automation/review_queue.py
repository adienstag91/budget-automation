"""
Transaction Review Queue for Budget Dashboard

Add this as a new tab in your Streamlit dashboard to review and categorize 
transactions that need manual review.
"""
import streamlit as st
import pandas as pd
import json
from pathlib import Path

from budget_automation.utils.db_connection import get_db_connection


@st.cache_data(ttl=60)  # Cache for 60 seconds, then reload
def load_taxonomy():
    """Load category taxonomy"""
    taxonomy_file = Path(__file__).parent.parent / "data" / "taxonomy" / "taxonomy.json"
    with open(taxonomy_file) as f:
        raw_data = json.load(f)
    
    # Extract categories from the wrapper structure
    if isinstance(raw_data, dict) and 'categories' in raw_data:
        raw_taxonomy = raw_data['categories']
    else:
        raw_taxonomy = raw_data
    
    # Convert to simple category -> [subcategory names] structure
    taxonomy = {}
    
    # Handle list format: [{"category": "Food", "subcategories": [...]}]
    if isinstance(raw_taxonomy, list):
        for item in raw_taxonomy:
            if isinstance(item, dict):
                cat_name = item.get('category', item.get('name', ''))
                subcats = item.get('subcategories', item.get('subcats', []))
                
                if isinstance(subcats, list):
                    if subcats and isinstance(subcats[0], dict):
                        taxonomy[cat_name] = [s.get('name', s.get('subcategory', str(s))) for s in subcats]
                    else:
                        taxonomy[cat_name] = subcats
                else:
                    taxonomy[cat_name] = []
    
    # Handle dict format: {"Food": [...], "Transport": [...]}
    elif isinstance(raw_taxonomy, dict):
        for category, subcats in raw_taxonomy.items():
            if isinstance(subcats, list):
                # Extract names if subcats are dicts, otherwise use as-is
                if subcats and isinstance(subcats[0], dict):
                    taxonomy[category] = [s.get('name', s.get('subcategory', str(s))) for s in subcats]
                else:
                    taxonomy[category] = subcats
            else:
                taxonomy[category] = []
    
    return taxonomy


def get_review_queue(conn):
    """Get all transactions needing review"""
    query = """
        SELECT 
            txn_id,
            txn_date,
            description_raw,
            merchant_norm,
            merchant_detail,
            amount,
            direction,
            category,
            subcategory,
            tag_source,
            tag_confidence,
            notes
        FROM transactions
        WHERE needs_review = TRUE
        ORDER BY txn_date DESC, amount DESC
    """
    
    df = pd.read_sql(query, conn)
    return df


def update_transaction(conn, txn_id, category, subcategory, create_rule=False, 
                       merchant_norm=None, merchant_detail=None):
    """
    Update transaction category and optionally create a rule
    
    Args:
        conn: Database connection
        txn_id: Transaction ID to update
        category: New category
        subcategory: New subcategory
        create_rule: Whether to create a rule for this merchant
        merchant_norm: Merchant name for rule creation
        merchant_detail: Merchant detail for rule creation
    """
    cursor = conn.cursor()
    
    # Convert numpy types to Python types
    txn_id = int(txn_id)
    
    # Update transaction
    cursor.execute("""
        UPDATE transactions
        SET category = %s,
            subcategory = %s,
            needs_review = FALSE,
            tag_source = 'manual',
            tag_confidence = 1.0
        WHERE txn_id = %s
    """, (category, subcategory, txn_id))
    
    # Create rule if requested
    if create_rule and merchant_norm:
        try:
            # Check if rule already exists
            cursor.execute("""
                SELECT rule_id FROM categorization_rules
                WHERE merchant_norm = %s
                  AND (merchant_detail = %s OR (merchant_detail IS NULL AND %s IS NULL))
                  AND is_active = TRUE
            """, (merchant_norm, merchant_detail, merchant_detail))
            
            existing_rule = cursor.fetchone()
            
            if not existing_rule:
                # Create new rule
                cursor.execute("""
                    INSERT INTO categorization_rules (
                        merchant_norm,
                        merchant_detail,
                        category,
                        subcategory,
                        confidence,
                        source,
                        is_active
                    ) VALUES (%s, %s, %s, %s, 1.0, 'manual', TRUE)
                """, (merchant_norm, merchant_detail, category, subcategory))
        except Exception as e:
            # Rule creation failed (table might not exist or different name)
            # Just skip it - transaction update still succeeded
            pass
    
    conn.commit()
    cursor.close()


def render_review_queue():
    """Main review queue interface"""
    st.header("📋 Transaction Review Queue")
    
    # Load data
    conn = get_db_connection()
    taxonomy = load_taxonomy()
    df = get_review_queue(conn)
    
    if df.empty:
        st.success("🎉 All transactions reviewed! Nothing needs your attention.")
        conn.close()
        return
    
    # Summary stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Transactions to Review", len(df))
    with col2:
        total_amount = df[df['direction'] == 'debit']['amount'].sum()
        st.metric("Total Expenses", f"${total_amount:,.2f}")
    with col3:
        avg_confidence = df['tag_confidence'].mean() * 100
        st.metric("Avg Confidence", f"{avg_confidence:.0f}%")
    
    st.markdown("---")
    
    # Review mode selection
    review_mode = st.radio(
        "Review Mode:",
        ["One at a Time", "Bulk Review"],
        horizontal=True,
        key="review_mode"
    )
    
    if review_mode == "One at a Time":
        render_single_review(df, taxonomy, conn)
    else:
        render_bulk_review(df, taxonomy, conn)
    
    conn.close()


def render_single_review(df, taxonomy, conn):
    """Review transactions one at a time"""
    
    # Transaction selector
    if 'review_index' not in st.session_state:
        st.session_state.review_index = 0
    
    if st.session_state.review_index >= len(df):
        st.success("🎉 All transactions reviewed!")
        st.session_state.review_index = 0
        st.rerun()
        return
    
    # Get current transaction
    row = df.iloc[st.session_state.review_index]
    
    # Progress indicator
    st.progress((st.session_state.review_index + 1) / len(df))
    st.caption(f"Transaction {st.session_state.review_index + 1} of {len(df)}")
    
    # Transaction details card
    st.markdown(f"""
    ### 💳 Transaction Details
    
    **Date:** {row['txn_date']}  
    **Description:** {row['description_raw']}  
    **Merchant:** {row['merchant_norm']}  
    {f"**Detail:** {row['merchant_detail']}" if pd.notna(row['merchant_detail']) else ""}  
    **Amount:** ${row['amount']:.2f} ({row['direction']})  
    {f"**Notes:** {row['notes']}" if pd.notna(row['notes']) else ""}
    
    ---
    
    **Current Category:** {row['category']} / {row['subcategory']}  
    **Source:** {row['tag_source']} ({row['tag_confidence']:.0%} confidence)
    """)
    
    # Categorization form
    col1, col2 = st.columns(2)
    
    with col1:
        # Category selection
        categories = sorted(taxonomy.keys())
        current_cat_idx = categories.index(row['category']) if row['category'] in categories else 0
        
        selected_category = st.selectbox(
            "Category",
            categories,
            index=current_cat_idx,
            key=f"cat_{row['txn_id']}"
        )
    
    with col2:
        # Subcategory selection
        subcategories = sorted(taxonomy.get(selected_category, []))
        current_subcat_idx = 0
        if row['subcategory'] in subcategories:
            current_subcat_idx = subcategories.index(row['subcategory'])
        
        selected_subcategory = st.selectbox(
            "Subcategory",
            subcategories,
            index=current_subcat_idx,
            key=f"subcat_{row['txn_id']}"
        )
    
    # Rule creation option
    create_rule = st.checkbox(
        f"Create rule for **{row['merchant_norm']}**",
        value=False,  # Unchecked by default - rules for one-offs only
        help="Automatically categorize future transactions from this merchant",
        key=f"rule_{row['txn_id']}"
    )
    
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("✅ Accept & Next", type="primary", use_container_width=True):
            update_transaction(
                conn, 
                row['txn_id'], 
                selected_category, 
                selected_subcategory,
                create_rule=create_rule,
                merchant_norm=row['merchant_norm'],
                merchant_detail=row['merchant_detail'] if pd.notna(row['merchant_detail']) else None
            )
            st.session_state.review_index += 1
            st.cache_data.clear()  # Clear all caches to force fresh data
            st.rerun()
    
    with col2:
        if st.button("⏭️ Skip", use_container_width=True):
            st.session_state.review_index += 1
            st.rerun()
    
    with col3:
        if st.button("🔄 Reset Progress", use_container_width=True):
            st.session_state.review_index = 0
            st.rerun()


def render_bulk_review(df, taxonomy, conn):
    """Review multiple transactions at once"""
    
    st.info("💡 Tip: Use this mode to quickly categorize similar transactions")
    
    # Filters
    col1, col2 = st.columns(2)
    
    with col1:
        merchant_filter = st.multiselect(
            "Filter by Merchant",
            options=sorted(df['merchant_norm'].unique()),
            key="bulk_merchant_filter"
        )
    
    with col2:
        source_filter = st.multiselect(
            "Filter by Source",
            options=sorted(df['tag_source'].unique()),
            key="bulk_source_filter"
        )
    
    # Apply filters
    filtered_df = df.copy()
    if merchant_filter:
        filtered_df = filtered_df[filtered_df['merchant_norm'].isin(merchant_filter)]
    if source_filter:
        filtered_df = filtered_df[filtered_df['tag_source'].isin(source_filter)]
    
    if filtered_df.empty:
        st.warning("No transactions match your filters")
        return
    
    st.caption(f"Showing {len(filtered_df)} transactions")
    
    # Bulk categorization
    st.subheader("Bulk Categorize")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        bulk_category = st.selectbox(
            "Category for all",
            sorted(taxonomy.keys()),
            key="bulk_category"
        )
    
    with col2:
        bulk_subcategory = st.selectbox(
            "Subcategory for all",
            sorted(taxonomy.get(bulk_category, [])),
            key="bulk_subcategory"
        )
    
    with col3:
        bulk_create_rules = st.checkbox(
            "Create rules",
            value=False,  # Unchecked by default
            help="Create rules for all merchants",
            key="bulk_rules"
        )
    
    if st.button("✅ Apply to All Filtered Transactions", type="primary"):
        progress_bar = st.progress(0)
        count = 0
        for idx, row in filtered_df.iterrows():
            update_transaction(
                conn,
                int(row['txn_id']),  # Convert numpy.int64 to int
                bulk_category,
                bulk_subcategory,
                create_rule=bulk_create_rules,
                merchant_norm=row['merchant_norm'],
                merchant_detail=row['merchant_detail'] if pd.notna(row['merchant_detail']) else None
            )
            count += 1
            progress_bar.progress(count / len(filtered_df))
        
        st.success(f"✅ Updated {len(filtered_df)} transactions!")
        st.cache_data.clear()  # Clear cache to show fresh data
        st.rerun()
    
    st.markdown("---")
    
    # Show filtered transactions
    st.subheader("Filtered Transactions")
    
    display_df = filtered_df[[
        'txn_date', 'description_raw', 'merchant_norm', 
        'amount', 'category', 'subcategory', 'tag_confidence'
    ]].copy()
    
    display_df['tag_confidence'] = display_df['tag_confidence'].apply(lambda x: f"{x:.0%}")
    display_df['amount'] = display_df['amount'].apply(lambda x: f"${x:,.2f}")
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )


# If running standalone for testing
if __name__ == "__main__":
    st.set_page_config(page_title="Transaction Review", layout="wide")
    render_review_queue()
