#!/usr/bin/env python3
"""
Transaction import CLI

Imports transactions from Chase CSV files.
"""
import argparse
import sys
import json
import os
from pathlib import Path
from dotenv import load_dotenv

from budget_automation.utils.db_connection import get_db_connection
from budget_automation.core.csv_parser import parse_chase_csv
from budget_automation.core.categorization_orchestrator import (
    CategorizationOrchestrator,
    Transaction,
    load_rules_from_db
)


# Load environment variables
load_dotenv()

def insert_transactions(conn, transactions: list):
    """Insert transactions into database with deduplication"""
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
            """, txn)
            
            conn.commit()  # ← Commit immediately after each successful insert
            inserted += 1
            
        except Exception as e:
            conn.rollback()  # ← Only rolls back this one transaction
            if 'duplicate key' in str(e).lower() or 'unique' in str(e).lower():
                duplicates += 1
            else:
                print(f"⚠️  Error: {e}")
                print(f"   Transaction: {txn.get('description_raw', 'unknown')[:50]}")
                errors += 1
    
    cursor.close()
    
    return inserted, duplicates, errors

def main():
    """Main import function"""
    parser = argparse.ArgumentParser(description='Import Chase CSV transactions')
    parser.add_argument('csv_file', help='Path to Chase CSV file')
    parser.add_argument('--csv-type', choices=['checking', 'credit', 'auto'], 
                       default='auto', help='CSV type (default: auto-detect)')
    parser.add_argument('--account-id', type=int, help='Account ID')
    parser.add_argument('--llm', action='store_true', help='Enable LLM categorization (uses API credits)')
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
    print(f"LLM Enabled: {args.llm}")
    print(f"Dry Run: {args.dry_run}")
    print("=" * 80)
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    try:
        conn = get_db_connection()
        print("   ✅ Connected")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        print("\nMake sure Docker is running: docker-compose up -d")
        sys.exit(1)
    
    try:
        # Get project root for taxonomy
        project_root = Path(__file__).parent.parent.parent
        taxonomy_file = project_root / "data" / "taxonomy" / "taxonomy.json"
        
        with open(taxonomy_file) as f:
            taxonomy = json.load(f)
        
        # Load rules
        print("\n📚 Loading rules from database...")
        rules = load_rules_from_db(conn)
        print(f"   ✅ Loaded {len(rules)} active rules")
        
        # Parse CSV
        print(f"\n📄 Parsing CSV file...")
        parsed_txns = parse_chase_csv(csv_path, args.csv_type, args.account_id)
        
        # Create orchestrator
        print(f"\n🧠 Initializing categorization engine...")
        review_threshold = float(os.getenv('REVIEW_THRESHOLD', '0.80'))
        enable_llm_default = os.getenv('ENABLE_LLM', 'false').lower() == 'true'

        # Use CLI flag to override, otherwise use .env setting
        enable_llm = args.llm if hasattr(args, 'llm') else enable_llm_default
        
        orchestrator = CategorizationOrchestrator(
            taxonomy=taxonomy,
            rules=rules,
            review_threshold=review_threshold,
            enable_llm=enable_llm
        )
        print("   ✅ Ready")
        
        # Convert to Transaction objects
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
        
        # Categorize
        categorized = orchestrator.categorize_batch(transactions)
        
        # Print stats
        orchestrator.print_stats()
        
        # Show sample
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
        
        # Insert or dry run
        if args.dry_run:
            print(f"\n🔍 DRY RUN - Not inserting into database")
        else:
            print(f"\n💾 Inserting into database...")
            
            # Convert back to dicts
            txn_dicts = []
            for txn in categorized:
                # Match by unique transaction signature instead of index
                orig_txn = next(
                    t for t in parsed_txns
                    if t['description_raw'] == txn.description_raw
                    and t['txn_date'] == txn.txn_date
                    and abs(float(t['amount']) - txn.amount) < 0.01
                    and t['source_row_hash'] not in [td['source_row_hash'] for td in txn_dicts]  # Prevent duplicates
                )
                
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
        
        # Review queue summary
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
