"""
Amazon Order Import - ELT Architecture

Imports Amazon order history CSV into staging table (amazon_orders_raw).
Handles deduplication automatically - safe to import full history multiple times.
"""
import csv
import argparse
from pathlib import Path
from datetime import datetime
import uuid

from budget_automation.utils.db_connection import get_db_connection


def parse_amazon_csv(csv_path):
    """Parse Amazon order history CSV"""
    orders = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            try:
                # Parse order date
                order_date_str = row.get('Order Date', '').strip()
                if order_date_str:
                    order_date = datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
                else:
                    continue  # Skip rows without order date
                
                # Parse ship date (optional)
                ship_date_str = row.get('Ship Date', '').strip()
                ship_date = None
                if ship_date_str and ship_date_str != 'Not Available':
                    try:
                        ship_date = datetime.fromisoformat(ship_date_str.replace('Z', '+00:00'))
                    except:
                        pass
                
                # Parse numeric fields
                def parse_decimal(value):
                    if not value or value.strip() == '':
                        return None
                    try:
                        return float(value.strip())
                    except:
                        return None
                
                def parse_int(value):
                    if not value or value.strip() == '':
                        return None
                    try:
                        return int(value.strip())
                    except:
                        return None
                
                order = {
                    'order_id': row.get('Order ID', '').strip(),
                    'asin': row.get('ASIN', '').strip(),
                    'website': row.get('﻿"Website"', row.get('Website', '')).strip().strip('"'),
                    'order_date': order_date,
                    'purchase_order_number': row.get('Purchase Order Number', '').strip(),
                    'currency': row.get('Currency', '').strip(),
                    'unit_price': parse_decimal(row.get('Unit Price')),
                    'unit_price_tax': parse_decimal(row.get('Unit Price Tax')),
                    'shipping_charge': parse_decimal(row.get('Shipping Charge')),
                    'total_discounts': parse_decimal(row.get('Total Discounts')),
                    'total_owed': parse_decimal(row.get('Total Owed')),
                    'shipment_item_subtotal': parse_decimal(row.get('Shipment Item Subtotal')),
                    'shipment_item_subtotal_tax': parse_decimal(row.get('Shipment Item Subtotal Tax')),
                    'product_name': row.get('Product Name', '').strip(),
                    'product_condition': row.get('Product Condition', '').strip(),
                    'quantity': parse_int(row.get('Quantity')),
                    'payment_instrument_type': row.get('Payment Instrument Type', '').strip(),
                    'order_status': row.get('Order Status', '').strip(),
                    'shipment_status': row.get('Shipment Status', '').strip(),
                    'ship_date': ship_date,
                    'shipping_option': row.get('Shipping Option', '').strip(),
                    'shipping_address': row.get('Shipping Address', '').strip(),
                    'billing_address': row.get('Billing Address', '').strip(),
                    'carrier_name_tracking': row.get('Carrier Name & Tracking Number', '').strip(),
                    'gift_message': row.get('Gift Message', '').strip() if row.get('Gift Message') != 'Not Available' else None,
                    'gift_sender_name': row.get('Gift Sender Name', '').strip() if row.get('Gift Sender Name') != 'Not Available' else None,
                    'gift_recipient_contact': row.get('Gift Recipient Contact Details', '').strip() if row.get('Gift Recipient Contact Details') != 'Not Available' else None,
                    'item_serial_number': row.get('Item Serial Number', '').strip() if row.get('Item Serial Number') != 'Not Available' else None,
                }
                
                # Validate required fields
                if order['order_id'] and order['asin']:
                    orders.append(order)
                    
            except Exception as e:
                print(f"⚠️  Skipping malformed row: {e}")
                continue
    
    return orders


def import_amazon_orders(csv_path, dry_run=False):
    """
    Import Amazon orders into staging table with deduplication
    
    Args:
        csv_path: Path to Amazon order history CSV
        dry_run: If True, show what would be imported without importing
    """
    print("=" * 80)
    print("📦 AMAZON ORDER IMPORT (ELT)")
    print("=" * 80)
    print(f"CSV File: {csv_path}")
    print(f"Dry Run: {dry_run}")
    print("=" * 80)
    
    # Parse CSV
    print("\n📄 Parsing Amazon order history CSV...")
    orders = parse_amazon_csv(csv_path)
    print(f"✅ Parsed {len(orders)} order items from CSV")
    
    # Deduplicate within CSV (same order_id + asin can appear multiple times)
    seen_keys = set()
    unique_orders = []
    duplicates_in_csv = 0
    
    for order in orders:
        key = (order['order_id'], order['asin'])
        if key not in seen_keys:
            seen_keys.add(key)
            unique_orders.append(order)
        else:
            duplicates_in_csv += 1
    
    if duplicates_in_csv > 0:
        print(f"⚠️  Found {duplicates_in_csv} duplicate items within CSV (kept first occurrence)")
    
    orders = unique_orders
    print(f"✅ {len(orders)} unique order items to process")
    
    if not orders:
        print("⚠️  No valid orders found in CSV")
        return
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    conn = get_db_connection()
    cursor = conn.cursor()
    print("✅ Connected")
    
    # Generate batch ID for this import
    batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Check for existing orders
    print("\n🔍 Checking for existing orders...")
    order_keys = [(o['order_id'], o['asin']) for o in orders]
    
    # Build query to check existing
    placeholders = ','.join(['(%s, %s)'] * len(order_keys))
    check_query = f"""
        SELECT order_id, asin
        FROM amazon_orders_raw
        WHERE (order_id, asin) IN ({placeholders})
    """
    
    flat_keys = [item for sublist in order_keys for item in sublist]
    cursor.execute(check_query, flat_keys)
    existing_keys = set(cursor.fetchall())
    
    print(f"✅ Found {len(existing_keys)} existing order items")
    
    # Filter to new orders only
    new_orders = [o for o in orders if (o['order_id'], o['asin']) not in existing_keys]
    duplicate_orders = len(orders) - len(new_orders)
    
    print(f"\n📊 Summary:")
    print(f"  • Total in CSV: {len(orders)}")
    print(f"  • Already imported: {duplicate_orders}")
    print(f"  • New to import: {len(new_orders)}")
    
    if not new_orders:
        print("\n✅ All orders already imported! Nothing to do.")
        cursor.close()
        conn.close()
        return
    
    # Show sample of new orders
    print(f"\n📋 Sample of new orders (first 5):")
    for order in new_orders[:5]:
        print(f"  • {order['order_date'].date()} | {order['order_id']} | {order['product_name'][:50]} | ${order['total_owed']:.2f}")
    
    if len(new_orders) > 5:
        print(f"  ... and {len(new_orders) - 5} more")
    
    # Execute import
    if dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN - No changes made")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        response = input(f"Import {len(new_orders)} new orders? (y/n): ")
        
        if response.lower() != 'y':
            print("❌ Cancelled")
            cursor.close()
            conn.close()
            return
        
        print(f"\n📥 Importing {len(new_orders)} orders...")
        
        insert_query = """
            INSERT INTO amazon_orders_raw (
                order_id, asin, website, order_date, purchase_order_number,
                currency, unit_price, unit_price_tax, shipping_charge, 
                total_discounts, total_owed, shipment_item_subtotal,
                shipment_item_subtotal_tax, product_name, product_condition,
                quantity, payment_instrument_type, order_status, 
                shipment_status, ship_date, shipping_option,
                shipping_address, billing_address, carrier_name_tracking,
                gift_message, gift_sender_name, gift_recipient_contact,
                item_serial_number, import_batch_id
            ) VALUES (
                %(order_id)s, %(asin)s, %(website)s, %(order_date)s, 
                %(purchase_order_number)s, %(currency)s, %(unit_price)s, 
                %(unit_price_tax)s, %(shipping_charge)s, %(total_discounts)s,
                %(total_owed)s, %(shipment_item_subtotal)s, 
                %(shipment_item_subtotal_tax)s, %(product_name)s, 
                %(product_condition)s, %(quantity)s, %(payment_instrument_type)s,
                %(order_status)s, %(shipment_status)s, %(ship_date)s,
                %(shipping_option)s, %(shipping_address)s, %(billing_address)s,
                %(carrier_name_tracking)s, %(gift_message)s, %(gift_sender_name)s,
                %(gift_recipient_contact)s, %(item_serial_number)s, %(batch_id)s
            )
        """
        
        inserted = 0
        for order in new_orders:
            order['batch_id'] = batch_id
            cursor.execute(insert_query, order)
            inserted += 1
        
        conn.commit()
        
        print(f"✅ Imported {inserted} order items")
        
        print("\n" + "=" * 80)
        print("✅ IMPORT COMPLETE!")
        print("=" * 80)
        print(f"Batch ID: {batch_id}")
        print(f"\n💡 Next step: Run enrichment to match orders to transactions")
        print(f"   python budget_automation/core/amazon_enrichment.py --expand --llm")
    
    cursor.close()
    conn.close()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Import Amazon order history into staging table',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - see what would be imported
  python -m budget_automation.core.amazon_import \\
    ~/Downloads/Your\\ Orders/Retail.OrderHistory.1/Retail.OrderHistory.1.csv \\
    --dry-run
  
  # Import new orders
  python -m budget_automation.core.amazon_import \\
    ~/Downloads/Your\\ Orders/Retail.OrderHistory.1/Retail.OrderHistory.1.csv
  
  # Safe to run multiple times - automatically deduplicates!
        """
    )
    
    parser.add_argument(
        'csv_file',
        help='Path to Amazon order history CSV file'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be imported without making changes'
    )
    
    args = parser.parse_args()
    
    # Resolve file path
    csv_path = Path(args.csv_file).expanduser()
    if not csv_path.exists():
        print(f"❌ Error: CSV file not found: {csv_path}")
        return 1
    
    import_amazon_orders(csv_path, dry_run=args.dry_run)
    
    return 0


if __name__ == "__main__":
    exit(main())
