"""
Amazon Order Enrichment - ELT Architecture

Matches Amazon orders from staging table (amazon_orders_raw) to credit card 
transactions and expands them into detailed line items with LLM categorization.
"""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json

from budget_automation.utils.db_connection import get_db_connection
from budget_automation.core.llm_categorizer import LLMCategorizer


def get_unenriched_orders(conn, start_date='2023-01-01'):
    """
    Get orders from staging table that haven't been enriched yet
    
    Returns list of orders with all items grouped by order_id
    """
    cursor = conn.cursor()
    
    # Get all unenriched order items
    cursor.execute("""
        SELECT 
            order_id,
            order_date,
            product_name,
            asin,
            quantity,
            unit_price,
            unit_price_tax,
            shipping_charge,
            total_owed,
            total_discounts
        FROM amazon_orders_raw
        WHERE enriched = FALSE
          AND order_date >= %s
        ORDER BY order_date, order_id
    """, (start_date,))
    
    rows = cursor.fetchall()
    cursor.close()
    
    # Group items by order_id
    orders = {}
    for row in rows:
        order_id = row[0]
        
        if order_id not in orders:
            orders[order_id] = {
                'order_id': order_id,
                'order_date': row[1],
                'items': [],
                'total': Decimal('0.00')
            }
        
        item = {
            'product_name': row[2],
            'asin': row[3],
            'quantity': row[4] or 1,
            'unit_price': Decimal(str(row[5])) if row[5] else Decimal('0.00'),
            'unit_price_tax': Decimal(str(row[6])) if row[6] else Decimal('0.00'),
            'shipping_charge': Decimal(str(row[7])) if row[7] else Decimal('0.00'),
            'total_owed': Decimal(str(row[8])) if row[8] else Decimal('0.00'),
            'total_discounts': Decimal(str(row[9])) if row[9] else Decimal('0.00')
        }
        
        orders[order_id]['items'].append(item)
        orders[order_id]['total'] += item['total_owed']
    
    return list(orders.values())


def find_matching_transaction(conn, order_date, order_total, window_days=3):
    """
    Find credit card transaction that matches this Amazon order
    
    Args:
        order_date: Date of Amazon order
        order_total: Total amount charged
        window_days: Days before/after to search
    
    Returns transaction ID if found, None otherwise
    """
    cursor = conn.cursor()
    
    # Search for AMAZON transactions within date window
    start_date = order_date - timedelta(days=window_days)
    end_date = order_date + timedelta(days=window_days)
    
    cursor.execute("""
        SELECT txn_id, txn_date, amount, merchant_raw
        FROM transactions
        WHERE merchant_norm = 'AMAZON'
          AND txn_date BETWEEN %s AND %s
          AND ABS(amount - %s) < 0.02
          AND (created_by = 'import' OR created_by IS NULL)
        ORDER BY ABS(EXTRACT(EPOCH FROM (txn_date - %s))), ABS(amount - %s)
        LIMIT 1
    """, (start_date, end_date, float(order_total), order_date, float(order_total)))
    
    result = cursor.fetchone()
    cursor.close()
    
    if result:
        return {
            'txn_id': result[0],
            'txn_date': result[1],
            'amount': result[2],
            'merchant_raw': result[3]
        }
    
    return None


def categorize_product_with_llm(product_name, llm_categorizer):
    """
    Use LLM to categorize an Amazon product
    
    Returns: (category, subcategory) tuple
    """
    if not llm_categorizer:
        # Fallback to Shopping/Amazon if no LLM
        return ('Shopping', 'Amazon')
    
    try:
        # Create a minimal transaction-like dict for LLM
        fake_txn = {
            'merchant_norm': 'AMAZON',
            'merchant_detail': product_name[:100],  # Truncate long names
            'amount': 0,  # Amount doesn't matter for categorization
            'description': f"Amazon - {product_name}"
        }
        
        result = llm_categorizer.categorize_transaction(fake_txn)
        return (result['category'], result['subcategory'])
        
    except Exception as e:
        print(f"⚠️  LLM categorization failed for '{product_name[:50]}': {e}")
        return ('Shopping', 'Amazon')


def expand_amazon_order(conn, order, matched_txn, payment_source, llm_categorizer=None, dry_run=False):
    """
    Expand an Amazon order into detailed line items
    
    Handles both:
    - Matched orders (has CC transaction) - deletes CC txn, creates line items
    - Unmatched orders (no CC transaction) - creates line items anyway
    
    Args:
        payment_source: 'credit_card' or 'unknown' (likely gift card)
    """
    cursor = conn.cursor()
    
    if dry_run:
        print(f"\n📦 {order['order_id']} | {order['order_date'].date()} | ${order['total']:.2f}")
        
        if matched_txn:
            print(f"   Matched to: txn_id={matched_txn['txn_id']} | {matched_txn['txn_date']} | ${matched_txn['amount']:.2f}")
            print(f"   Payment: Credit Card")
        else:
            print(f"   No CC match found")
            print(f"   Payment: Unknown (possibly gift card)")
        
        print(f"   Would expand into {len(order['items'])} items:")
        
        for item in order['items']:
            category, subcategory = categorize_product_with_llm(item['product_name'], llm_categorizer)
            print(f"      • {item['product_name'][:60]:60} ${item['total_owed']:7.2f} → {category}/{subcategory}")
        
        return
    
    # Get account/source info
    if matched_txn:
        # Use info from matched CC transaction
        cursor.execute("""
            SELECT account_id, source, txn_date
            FROM transactions
            WHERE txn_id = %s
        """, (matched_txn['txn_id'],))
        
        txn_info = cursor.fetchone()
        if not txn_info:
            print(f"⚠️  Could not find transaction {matched_txn['txn_id']}")
            cursor.close()
            return
        
        account_id, _, txn_date = txn_info  # Ignore original source
        source = 'amazon_enrichment'  # Use amazon_enrichment as source
        
        # Delete original CC transaction since we're replacing it
        cursor.execute("DELETE FROM transactions WHERE txn_id = %s", (matched_txn['txn_id'],))
    else:
        # For unmatched orders, use default account (assume Chase Credit)
        cursor.execute("SELECT account_id FROM accounts WHERE account_name = 'Chase Credit' LIMIT 1")
        result = cursor.fetchone()
        account_id = result[0] if result else 2  # Default to account_id 2
        source = 'amazon_enrichment'
        txn_date = order['order_date']
    
    # Create transaction for each item
    for item in order['items']:
        # Categorize with LLM
        category, subcategory = categorize_product_with_llm(item['product_name'], llm_categorizer)
        
        # Truncate product name to fit merchant_detail field (64 chars)
        product_name_short = item['product_name'][:60]
        
        # Create source row hash for deduplication
        import hashlib
        hash_str = f"amazon_{order['order_id']}_{item['asin']}"
        source_row_hash = f"amz_{hashlib.md5(hash_str.encode()).hexdigest()[:8]}"
        
        # Build payment note
        if payment_source == 'credit_card':
            payment_note = f"Order: {order['order_id']} | ASIN: {item['asin']} | Qty: {item['quantity']} | Paid via credit card"
        else:
            payment_note = f"Order: {order['order_id']} | ASIN: {item['asin']} | Qty: {item['quantity']} | Payment method unknown (possibly gift card)"
        
        # Insert new transaction
        cursor.execute("""
            INSERT INTO transactions (
                account_id,
                txn_date,
                post_date,
                description_raw,
                direction,
                amount,
                merchant_raw,
                merchant_norm,
                merchant_detail,
                category,
                subcategory,
                needs_review,
                source,
                source_row_hash,
                created_by,
                notes
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            account_id,
            txn_date,
            txn_date,  # post_date = txn_date for Amazon orders
            f"Amazon - {product_name_short}",  # description_raw
            'debit',  # All Amazon purchases are debits
            float(item['total_owed']),
            'AMAZON',
            'AMAZON',
            product_name_short,
            category,
            subcategory,
            True,  # Always needs review in Phase 1
            source,
            source_row_hash,
            'amazon_enrichment',
            payment_note
        ))
    
    # Mark all items in this order as enriched
    # Note: For matched orders, we deleted the CC transaction so matched_txn_id = NULL
    # For unmatched orders, there was never a transaction so also NULL
    cursor.execute("""
        UPDATE amazon_orders_raw
        SET enriched = TRUE,
            enriched_date = NOW(),
            matched_txn_id = NULL
        WHERE order_id = %s
    """, (order['order_id'],))
    
    conn.commit()
    cursor.close()


def enrich_amazon_orders(start_date='2023-01-01', use_llm=False, dry_run=False):
    """
    Main enrichment process
    
    Args:
        start_date: Only enrich orders from this date forward
        use_llm: Use LLM for categorization (slower but smarter)
        dry_run: Show what would happen without making changes
    """
    print("=" * 80)
    print("📦 AMAZON ORDER ENRICHMENT")
    print("=" * 80)
    print(f"Start Date: {start_date}")
    print(f"Use LLM: {use_llm}")
    print(f"Dry Run: {dry_run}")
    print("=" * 80)
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    conn = get_db_connection()
    print("✅ Connected")
    
    # Initialize LLM categorizer if requested
    llm_categorizer = None
    if use_llm:
        print("\n🤖 Initializing LLM categorizer...")
        try:
            import json
            from pathlib import Path
            
            # Load taxonomy from file
            taxonomy_path = Path('data/taxonomy/taxonomy.json')
            with open(taxonomy_path) as f:
                taxonomy_data = json.load(f)
            
            # Extract categories - handle different formats
            taxonomy = {}
            
            if isinstance(taxonomy_data, dict) and 'categories' in taxonomy_data:
                # Wrapped format: {"version": ..., "categories": [...]}
                categories = taxonomy_data['categories']
            elif isinstance(taxonomy_data, list):
                # Direct list format: [{category: ...}, ...]
                categories = taxonomy_data
            else:
                # Assume it's already in the right format
                categories = taxonomy_data
            
            # Convert to dict format {category: [subcats]}
            if isinstance(categories, list):
                for cat in categories:
                    if isinstance(cat, dict):
                        cat_name = cat.get('category', cat.get('name', ''))
                        if cat_name:
                            subcats = cat.get('subcategories', [])
                            taxonomy[cat_name] = [
                                s.get('name', s) if isinstance(s, dict) else str(s) 
                                for s in subcats
                            ]
            elif isinstance(categories, dict):
                # Already in right format
                taxonomy = categories
            
            if not taxonomy:
                raise Exception("No categories found in taxonomy file")
            
            llm_categorizer = LLMCategorizer(taxonomy)
            print(f"✅ LLM ready (loaded {len(taxonomy)} categories)")
        except Exception as e:
            print(f"⚠️  LLM initialization failed: {e}")
            print("   Continuing without LLM (will use Shopping/Amazon for all)")
    
    # Get unenriched orders
    print(f"\n📥 Loading unenriched orders from {start_date}...")
    orders = get_unenriched_orders(conn, start_date)
    print(f"✅ Found {len(orders)} orders to process")
    
    if not orders:
        print("\n✅ No orders to enrich!")
        conn.close()
        return
    
    # Show summary
    total_items = sum(len(o['items']) for o in orders)
    total_amount = sum(o['total'] for o in orders)
    
    print(f"\n📊 Summary:")
    print(f"  • Orders: {len(orders)}")
    print(f"  • Items: {total_items}")
    print(f"  • Total Amount: ${total_amount:,.2f}")
    print(f"  • Date Range: {min(o['order_date'] for o in orders).date()} to {max(o['order_date'] for o in orders).date()}")
    
    # Match orders to transactions
    print(f"\n🔍 Matching orders to credit card transactions...")
    
    matched = []
    unmatched = []
    
    for order in orders:
        match = find_matching_transaction(conn, order['order_date'], order['total'])
        
        if match:
            matched.append({'order': order, 'transaction': match})
        else:
            unmatched.append(order)
    
    print(f"✅ Matched: {len(matched)} orders")
    print(f"⚠️  Unmatched: {len(unmatched)} orders")
    
    if unmatched:
        print(f"\n⚠️  Unmatched orders (no credit card transaction found):")
        for order in unmatched[:10]:
            print(f"   • {order['order_date'].date()} | {order['order_id']} | ${order['total']:.2f} | {len(order['items'])} items")
        if len(unmatched) > 10:
            print(f"   ... and {len(unmatched) - 10} more")
    
    if not matched:
        print("\n⚠️  No orders could be matched to transactions")
        print("   Will still enrich unmatched orders (likely paid via gift card)")
    
    # Combine matched and unmatched for enrichment
    all_orders_to_enrich = []
    
    # Add matched orders with transaction info
    for item in matched:
        all_orders_to_enrich.append({
            'order': item['order'],
            'transaction': item['transaction'],
            'payment_source': 'credit_card'
        })
    
    # Add unmatched orders without transaction info
    for order in unmatched:
        all_orders_to_enrich.append({
            'order': order,
            'transaction': None,
            'payment_source': 'unknown'  # Likely gift card
        })
    
    print(f"\n📊 Enrichment Plan:")
    print(f"  • Total orders to enrich: {len(all_orders_to_enrich)}")
    print(f"  • With CC match: {len(matched)}")
    print(f"  • Without CC match: {len(unmatched)}")
    
    # Calculate totals
    total_items_to_create = sum(len(item['order']['items']) for item in all_orders_to_enrich)
    
    print(f"  • Will create {total_items_to_create} line items")
    
    # Expand orders
    if dry_run:
        print(f"\n" + "=" * 80)
        print("DRY RUN - Showing what would happen")
        print("=" * 80)
        
        # Show first 5 orders
        for item in all_orders_to_enrich[:5]:
            expand_amazon_order(
                conn, 
                item['order'], 
                item['transaction'], 
                item['payment_source'],
                llm_categorizer, 
                dry_run=True
            )
        
        if len(all_orders_to_enrich) > 5:
            print(f"\n... and {len(all_orders_to_enrich) - 5} more orders")
        
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE")
        print("=" * 80)
    else:
        print(f"\n" + "=" * 80)
        response = input(f"Expand {len(all_orders_to_enrich)} orders into {total_items_to_create} line items? (y/n): ")
        
        if response.lower() != 'y':
            print("❌ Cancelled")
            conn.close()
            return
        
        print(f"\n📤 Expanding {len(all_orders_to_enrich)} orders...")
        
        for i, item in enumerate(all_orders_to_enrich, 1):
            order = item['order']
            payment_type = "CC match" if item['payment_source'] == 'credit_card' else "No CC match"
            print(f"   [{i}/{len(all_orders_to_enrich)}] {order['order_id']} ({len(order['items'])} items) - {payment_type}")
            expand_amazon_order(
                conn, 
                order, 
                item['transaction'], 
                item['payment_source'],
                llm_categorizer, 
                dry_run=False
            )
        
        print(f"\n✅ Expanded {len(all_orders_to_enrich)} orders into {total_items_to_create} transactions")
        
        print("\n" + "=" * 80)
        print("✅ ENRICHMENT COMPLETE!")
        print("=" * 80)
        print(f"\n💡 Next step: Review transactions in dashboard")
        print(f"   streamlit run budget_automation/dashboard.py")
        print(f"   → Review Queue tab → Filter by 'amazon_enrichment'")
        print(f"\n📊 Summary:")
        print(f"   • Orders enriched: {len(all_orders_to_enrich)}")
        print(f"   • Paid via CC: {len(matched)}")
        print(f"   • Payment unknown (likely gift card): {len(unmatched)}")
        print(f"   • Line items created: {total_items_to_create}")
    
    conn.close()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Enrich Amazon orders with detailed line items',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - see what would happen
  python -m budget_automation.core.amazon_enrichment --dry-run
  
  # Enrich orders from 2023 onwards (no LLM)
  python -m budget_automation.core.amazon_enrichment --expand
  
  # Enrich with LLM categorization (slower but better)
  python -m budget_automation.core.amazon_enrichment --expand --llm
  
  # Start from different date
  python -m budget_automation.core.amazon_enrichment --expand --start-date 2024-01-01
        """
    )
    
    parser.add_argument(
        '--expand',
        action='store_true',
        help='Actually expand orders (required to make changes)'
    )
    
    parser.add_argument(
        '--llm',
        action='store_true',
        help='Use LLM for smart categorization (requires ANTHROPIC_API_KEY)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would happen without making changes'
    )
    
    parser.add_argument(
        '--start-date',
        default='2023-01-01',
        help='Only enrich orders from this date forward (YYYY-MM-DD)'
    )
    
    args = parser.parse_args()
    
    # Dry run or expand required
    if not args.dry_run and not args.expand:
        print("❌ Error: Must specify either --dry-run or --expand")
        print("   Use --dry-run to preview changes")
        print("   Use --expand to actually enrich orders")
        return 1
    
    enrich_amazon_orders(
        start_date=args.start_date,
        use_llm=args.llm,
        dry_run=args.dry_run
    )
    
    return 0


if __name__ == "__main__":
    exit(main())
