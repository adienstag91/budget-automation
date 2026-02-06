"""
Venmo Transaction Import - ELT Architecture

Imports Venmo transaction CSV into staging table (venmo_transactions_raw).
Handles deduplication automatically - safe to import full history multiple times.
"""
import csv
import argparse
from pathlib import Path
from datetime import datetime
import hashlib

from budget_automation.utils.db_connection import get_db_connection


def parse_venmo_amount(amount_str):
    """Parse Venmo amount string (e.g., '+ $100.00' or '- $50.00')"""
    amount_str = amount_str.strip()
    
    # Determine direction
    if amount_str.startswith('+'):
        direction = 'credit'
        amount_str = amount_str[1:].strip()
    elif amount_str.startswith('-'):
        direction = 'debit'
        amount_str = amount_str[1:].strip()
    else:
        direction = 'unknown'
    
    # Remove $ and parse
    amount_str = amount_str.replace('$', '').replace(',', '').strip()
    
    try:
        amount = float(amount_str)
    except:
        amount = 0.0
    
    return abs(amount), direction


def parse_venmo_csv(csv_path):
    """
    Parse Venmo statement CSV
    
    Venmo CSVs have unusual format:
    - Row 1: Account Statement - (@username)
    - Row 2: Account Activity  
    - Row 3: Column names
    - Row 4: Empty
    - Row 5+: Data
    """
    transactions = []
    account_owner = None
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        # Read first line to get account owner
        first_line = f.readline()
        import re
        match = re.search(r'@([\w-]+)', first_line)
        if match:
            account_owner = match.group(1).split('-')[0]  # Extract first name
        
        # Skip second row
        next(f)
        
        # Read CSV starting from row 3
        reader = csv.DictReader(f)
        
        for row in reader:
            # Skip empty rows
            if not row.get('Datetime') or not row['Datetime'].strip():
                continue
            
            if not row.get('Amount (total)') or not row['Amount (total)'].strip():
                continue
            
            try:
                # Parse datetime
                datetime_str = row['Datetime'].strip()
                txn_datetime = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
                txn_date = txn_datetime.date()
                
                # Parse amount and direction
                amount, direction = parse_venmo_amount(row['Amount (total)'])
                
                # Generate unique ID (Venmo doesn't provide one)
                # Use hash of key fields
                unique_str = f"{datetime_str}_{amount}_{direction}_{row.get('From', '')}_{row.get('To', '')}_{row.get('Note', '')}_{account_owner}"
                venmo_id = hashlib.md5(unique_str.encode()).hexdigest()
                
                txn = {
                    'venmo_id': venmo_id,
                    'transaction_datetime': txn_datetime,
                    'transaction_date': txn_date,
                    'transaction_type': row.get('Type', '').strip(),
                    'amount': amount,
                    'direction': direction,
                    'from_name': row.get('From', '').strip(),
                    'to_name': row.get('To', '').strip(),
                    'note': row.get('Note', '').strip(),
                    'account_owner': account_owner,
                }
                
                transactions.append(txn)
                
            except Exception as e:
                print(f"⚠️  Skipping malformed row: {e}")
                continue
    
    return transactions


def import_venmo_transactions(*csv_paths, dry_run=False):
    """
    Import Venmo transactions into staging table with deduplication
    
    Args:
        csv_paths: One or more paths to Venmo CSV files
        dry_run: If True, show what would be imported without importing
    """
    print("=" * 80)
    print("💸 VENMO TRANSACTION IMPORT (ELT)")
    print("=" * 80)
    print(f"CSV Files: {', '.join(str(p) for p in csv_paths)}")
    print(f"Dry Run: {dry_run}")
    print("=" * 80)
    
    # Parse all CSVs
    print(f"\n📄 Parsing {len(csv_paths)} Venmo CSV(s)...")
    all_transactions = []
    
    for csv_path in csv_paths:
        transactions = parse_venmo_csv(csv_path)
        all_transactions.extend(transactions)
        account = transactions[0]['account_owner'] if transactions else 'Unknown'
        print(f"   ✅ {Path(csv_path).name}: {len(transactions)} transactions (@{account})")
    
    print(f"✅ Parsed {len(all_transactions)} total transactions")
    
    if not all_transactions:
        print("⚠️  No valid transactions found in CSV(s)")
        return
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    conn = get_db_connection()
    cursor = conn.cursor()
    print("✅ Connected")
    
    # Generate batch ID
    batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Check for existing transactions
    print("\n🔍 Checking for existing transactions...")
    venmo_ids = [t['venmo_id'] for t in all_transactions]
    
    placeholders = ','.join(['%s'] * len(venmo_ids))
    check_query = f"""
        SELECT venmo_id
        FROM venmo_transactions_raw
        WHERE venmo_id IN ({placeholders})
    """
    
    cursor.execute(check_query, venmo_ids)
    existing_ids = set(row[0] for row in cursor.fetchall())
    
    print(f"✅ Found {len(existing_ids)} existing transactions")
    
    # Filter to new transactions only
    new_transactions = [t for t in all_transactions if t['venmo_id'] not in existing_ids]
    duplicate_count = len(all_transactions) - len(new_transactions)
    
    # Breakdown by type
    payments = [t for t in new_transactions if t['transaction_type'] == 'Payment']
    transfers = [t for t in new_transactions if t['transaction_type'] == 'Standard Transfer']
    other = [t for t in new_transactions if t['transaction_type'] not in ['Payment', 'Standard Transfer']]
    
    print(f"\n📊 Summary:")
    print(f"  • Total in CSV(s): {len(all_transactions)}")
    print(f"  • Already imported: {duplicate_count}")
    print(f"  • New to import: {len(new_transactions)}")
    print(f"    - Payments: {len(payments)}")
    print(f"    - Transfers: {len(transfers)}")
    print(f"    - Other: {len(other)}")
    
    if not new_transactions:
        print("\n✅ All transactions already imported! Nothing to do.")
        cursor.close()
        conn.close()
        return
    
    # Show sample
    print(f"\n📋 Sample of new transactions (first 5):")
    for txn in new_transactions[:5]:
        print(f"  • {txn['transaction_date']} | {txn['transaction_type']:20} | {txn['direction']:6} | ${txn['amount']:.2f} | {txn['note'][:30]}")
    
    if len(new_transactions) > 5:
        print(f"  ... and {len(new_transactions) - 5} more")
    
    # Execute import
    if dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN - No changes made")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        response = input(f"Import {len(new_transactions)} new transactions? (y/n): ")
        
        if response.lower() != 'y':
            print("❌ Cancelled")
            cursor.close()
            conn.close()
            return
        
        print(f"\n📥 Importing {len(new_transactions)} transactions...")
        
        insert_query = """
            INSERT INTO venmo_transactions_raw (
                venmo_id, transaction_datetime, transaction_date,
                transaction_type, amount, direction, from_name, to_name,
                note, account_owner, import_batch_id
            ) VALUES (
                %(venmo_id)s, %(transaction_datetime)s, %(transaction_date)s,
                %(transaction_type)s, %(amount)s, %(direction)s, 
                %(from_name)s, %(to_name)s, %(note)s, %(account_owner)s,
                %(batch_id)s
            )
        """
        
        inserted = 0
        for txn in new_transactions:
            txn['batch_id'] = batch_id
            cursor.execute(insert_query, txn)
            inserted += 1
        
        conn.commit()
        
        print(f"✅ Imported {inserted} transactions")
        
        print("\n" + "=" * 80)
        print("✅ IMPORT COMPLETE!")
        print("=" * 80)
        print(f"Batch ID: {batch_id}")
        print(f"\n💡 Next step: Run enrichment to match/expand transactions")
        print(f"   python budget_automation/core/venmo_enrichment.py --expand --llm")
    
    cursor.close()
    conn.close()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Import Venmo transactions into staging table',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - see what would be imported
  python -m budget_automation.core.venmo_import \\
    data/uploads/statements/venmo/VenmoStatement_Andrew_Dec_2025.csv \\
    data/uploads/statements/venmo/VenmoStatement_Amanda_Dec_2025.csv \\
    --dry-run
  
  # Import new transactions
  python -m budget_automation.core.venmo_import \\
    data/uploads/statements/venmo/VenmoStatement_*.csv
  
  # Safe to run multiple times - automatically deduplicates!
        """
    )
    
    parser.add_argument(
        'csv_files',
        nargs='+',
        help='Path(s) to Venmo CSV file(s)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be imported without making changes'
    )
    
    args = parser.parse_args()
    
    # Resolve file paths
    csv_paths = [Path(f).expanduser() for f in args.csv_files]
    
    for csv_path in csv_paths:
        if not csv_path.exists():
            print(f"❌ Error: CSV file not found: {csv_path}")
            return 1
    
    import_venmo_transactions(*csv_paths, dry_run=args.dry_run)
    
    return 0


if __name__ == "__main__":
    exit(main())
