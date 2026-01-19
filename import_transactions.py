"""
Transaction Import Script

Imports transactions from Chase CSV files, categorizes them, and loads into database.
"""
import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
import psycopg2

from csv_parser import parse_chase_csv
from categorization_orchestrator import CategorizationOrchestrator, Transaction, load_rules_from_db


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host="localhost",
        port=5432,
        database="budget_db",
        user="budget_user",
        password="budget_password_local_dev"
    )


def load_taxonomy(taxonomy_file: Path):
    """Load taxonomy from file"""
    with open(taxonomy_file) as f:
        return json.load(f)


def insert_transactions(conn, transactions: list):
    """
    Insert transactions into database
    
    Handles deduplication via source_row_hash
    """
    cursor = conn.cursor()
    
    inserted = 0
    duplicates = 0
    errors = 0
    
    for txn in transactions:
        try:
            cursor.execute("""
                INSERT INTO transactions (
                    account_id, source, source_row_hash,
                    txn_date, post_date,
                    description_raw, merchant_raw, merchant_norm, merchant_detail,
                    amount, currency, direction, type, is_return,
                    category, subcategory,
                    tag_source, tag_confidence, needs_review,
                    notes, memo, created_by
                )
                VALUES (
                    %(account_id)s, %(source)s, %(source_row_hash)s,
                    %(txn_date)s, %(post_date)s,
                    %(description_raw)s, %(merchant_raw)s, %(merchant_norm)s, %(merchant_detail)s,
                    %(amount)s, %(currency)s, %(direction)s, %(type)s, %(is_return)s,
                    %(category)s, %(subcategory)s,
                    %(tag_source)s, %(tag_confidence)s, %(needs_review)s,
                    %(notes)s, %(memo)s, %(created_by)s
                )
                RETURNING txn_id
            """, txn)
            
            txn_id = cursor.fetchone()[0]
            inserted += 1
            
        except psycopg2.errors.UniqueViolation:
            # Duplicate transaction (same source_row_hash)
            conn.rollback()
            duplicates += 1
        except Exception as e:
            print(f"⚠️  Error inserting transaction: {e}")
            print(f"   Transaction: {txn.get('description_raw', 'unknown')[:50]}")
            conn.rollback()
            errors += 1
    
    conn.commit()
    cursor.close()
    
    return inserted, duplicates, errors


def main():
    parser = argparse.ArgumentParser(description='Import Chase CSV transactions')
    parser.add_argument('csv_file', help='Path to Chase CSV file')
    parser.add_argument('--csv-type', choices=['checking', 'credit', 'auto'], 
                       default='auto', help='CSV type (default: auto-detect)')
    parser.add_argument('--account-id', type=int, help='Account ID (default: auto-detect)')
    parser.add_argument('--no-llm', action='store_true', help='Disable LLM categorization')
    parser.add_argument('--dry-run', action='store_true', help='Parse and categorize but do not insert')
    
    args = parser.parse_args()
    
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"❌ File not found: {csv_path}")
        sys.exit(1)
    
    print("=" * 80)
    print("📥 TRANSACTION IMPORT")
    print("=" * 80)
    print(f"CSV File: {csv_path}")
    print(f"CSV Type: {args.csv_type}")
    print(f"LLM Enabled: {not args.no_llm}")
    print(f"Dry Run: {args.dry_run}")
    print("=" * 80)
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    try:
        conn = get_db_connection()
        print("   ✅ Connected")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        print("\nMake sure Docker is running:")
        print("   cd infra && docker-compose up -d")
        sys.exit(1)
    
    try:
        # Load taxonomy
        taxonomy_file = Path(__file__).parent.parent / "data" / "taxonomy.json"
        taxonomy = load_taxonomy(taxonomy_file)
        
        # Load rules from database
        print("\n📚 Loading rules from database...")
        rules = load_rules_from_db(conn)
        print(f"   ✅ Loaded {len(rules)} active rules")
        
        # Parse CSV
        print(f"\n📄 Parsing CSV file...")
        parsed_txns = parse_chase_csv(csv_path, args.csv_type, args.account_id)
        
        # Create orchestrator
        print(f"\n🧠 Initializing categorization engine...")
        orchestrator = CategorizationOrchestrator(
            taxonomy=taxonomy,
            rules=rules,
            review_threshold=0.90,
            enable_llm=not args.no_llm
        )
        print("   ✅ Ready")
        
        # Convert parsed transactions to Transaction objects
        print(f"\n🏷️  Categorizing {len(parsed_txns)} transactions...")
        transactions = []
        for txn_dict in parsed_txns:
            txn = Transaction(
                txn_id=None,
                merchant_norm=txn_dict['merchant_norm'],
                merchant_detail=txn_dict.get('merchant_detail'),
                description_raw=txn_dict['description_raw'],
                amount=float(txn_dict['amount']),
                direction=txn_dict['direction'],
                txn_date=txn_dict['txn_date'],
                post_date=txn_dict['post_date'],
                account_id=txn_dict['account_id'],
                source=txn_dict['source'],
                type=txn_dict['type'],
                is_return=txn_dict['is_return'],
            )
            transactions.append(txn)
        
        # Categorize all transactions
        categorized = orchestrator.categorize_batch(transactions)
        
        # Print stats
        orchestrator.print_stats()
        
        # Show sample of results
        print(f"\n📋 Sample Results (first 10):")
        for i, txn in enumerate(categorized[:10], 1):
            status = "✅" if not txn.needs_review else "⚠️ "
            merchant = txn.merchant_norm
            if txn.merchant_detail:
                merchant += f" ({txn.merchant_detail})"
            print(f"{status} {i:2d}. {merchant:<40} → {txn.category} / {txn.subcategory}")
            print(f"       ${abs(txn.amount):>7.2f}  {txn.tag_source:<8}  {txn.tag_confidence:.0%}")
        
        if len(categorized) > 10:
            print(f"       ... and {len(categorized) - 10} more")
        
        # Insert into database
        if args.dry_run:
            print(f"\n🔍 DRY RUN - Not inserting into database")
        else:
            print(f"\n💾 Inserting into database...")
            
            # Convert Transaction objects back to dicts for insertion
            txn_dicts = []
            for txn in categorized:
                # Get the original parsed transaction to include source_row_hash
                orig_txn = next(t for t in parsed_txns 
                              if t['description_raw'] == txn.description_raw 
                              and t['txn_date'] == txn.txn_date
                              and t['amount'] == txn.amount)
                
                txn_dict = {
                    'account_id': txn.account_id,
                    'source': txn.source,
                    'source_row_hash': orig_txn['source_row_hash'],
                    'txn_date': txn.txn_date,
                    'post_date': txn.post_date,
                    'description_raw': txn.description_raw,
                    'merchant_raw': orig_txn['merchant_raw'],
                    'merchant_norm': txn.merchant_norm,
                    'merchant_detail': txn.merchant_detail,
                    'amount': txn.amount,
                    'currency': orig_txn['currency'],
                    'direction': txn.direction,
                    'type': txn.type,
                    'is_return': txn.is_return,
                    'category': txn.category,
                    'subcategory': txn.subcategory,
                    'tag_source': txn.tag_source,
                    'tag_confidence': txn.tag_confidence,
                    'needs_review': txn.needs_review,
                    'notes': txn.notes,
                    'memo': orig_txn.get('memo'),
                    'created_by': 'import',
                }
                txn_dicts.append(txn_dict)
            
            inserted, duplicates, errors = insert_transactions(conn, txn_dicts)
            
            print(f"   ✅ Inserted: {inserted}")
            if duplicates > 0:
                print(f"   ⏭️  Skipped (duplicates): {duplicates}")
            if errors > 0:
                print(f"   ❌ Errors: {errors}")
        
        # Show review queue summary
        needs_review = [t for t in categorized if t.needs_review]
        if needs_review:
            print(f"\n⚠️  {len(needs_review)} transactions need review:")
            for txn in needs_review[:5]:
                merchant = txn.merchant_norm
                if txn.merchant_detail:
                    merchant += f" ({txn.merchant_detail})"
                print(f"   • {merchant:<50} ${abs(txn.amount):>7.2f}")
            if len(needs_review) > 5:
                print(f"   ... and {len(needs_review) - 5} more")
            
            if not args.dry_run:
                print(f"\nTo review these transactions:")
                print(f"   python pipeline/review_queue.py")
        else:
            print(f"\n✅ All transactions categorized with high confidence!")
        
        print("\n" + "=" * 80)
        print("✅ Import complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
