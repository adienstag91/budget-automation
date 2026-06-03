#!/usr/bin/env python3
"""
Transaction import CLI

Imports transactions from Chase CSV files.
"""
import argparse
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

from budget_automation.utils.db_connection import get_db_connection
from budget_automation.core.csv_parser import parse_chase_csv
from budget_automation.core.import_service import (
    categorize_parsed,
    insert_transactions,
)


# Load environment variables
load_dotenv()


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
        # Parse CSV
        print(f"\n📄 Parsing CSV file...")
        parsed_txns = parse_chase_csv(csv_path, args.csv_type, args.account_id)

        # Resolve LLM setting: CLI flag overrides .env default.
        enable_llm_default = os.getenv('ENABLE_LLM', 'false').lower() == 'true'
        enable_llm = args.llm if hasattr(args, 'llm') else enable_llm_default

        # Categorize via the shared import service (rules -> LLM -> needs-review).
        # Taxonomy + rules are loaded from the DB inside the service.
        print(f"\n🏷️  Categorizing {len(parsed_txns)} transactions...")
        txn_dicts, stats = categorize_parsed(conn, parsed_txns, enable_llm=enable_llm)

        # Show sample
        print(f"\n📋 Sample Results (first 10):")
        for i, txn in enumerate(txn_dicts[:10], 1):
            status = "✅" if not txn['needs_review'] else "⚠️ "
            merchant = txn['merchant_norm']
            if txn['merchant_detail']:
                merchant += f" ({txn['merchant_detail']})"
            print(f"{status} {i:2d}. {merchant:<40} → {txn['category']} / {txn['subcategory']}")
            conf = txn['category_confidence'] or 0.0
            print(f"       ${abs(float(txn['amount'])):>7.2f}  {txn['category_source']:<8}  {conf:.0%}")

        if len(txn_dicts) > 10:
            print(f"       ... and {len(txn_dicts) - 10} more")

        # Insert or dry run
        if args.dry_run:
            print(f"\n🔍 DRY RUN - Not inserting into database")
        else:
            print(f"\n💾 Inserting into database...")
            inserted, duplicates, errors = insert_transactions(conn, txn_dicts)

            print(f"   ✅ Inserted: {inserted}")
            if duplicates > 0:
                print(f"   ⏭️  Skipped (duplicates): {duplicates}")
            if errors > 0:
                print(f"   ❌ Errors: {errors}")

        # Review queue summary
        needs_review = [t for t in txn_dicts if t['needs_review']]
        if needs_review:
            print(f"\n⚠️  {len(needs_review)} transactions need review:")
            for txn in needs_review[:5]:
                merchant = txn['merchant_norm']
                if txn['merchant_detail']:
                    merchant += f" ({txn['merchant_detail']})"
                print(f"   • {merchant:<50} ${abs(float(txn['amount'])):>7.2f}")
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
