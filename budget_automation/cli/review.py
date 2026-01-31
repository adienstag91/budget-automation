#!/usr/bin/env python3
"""
Transaction review CLI

Interactive tool to review and categorize transactions that need manual review.
"""
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple

from budget_automation.utils.db_connection import get_db_connection


def load_taxonomy(conn) -> Dict:
    """Load taxonomy from database"""
    cursor = conn.cursor()
    
    # Get all categories with their subcategories
    cursor.execute("""
        SELECT c.category, c.display_order, 
               ARRAY_AGG(s.subcategory ORDER BY s.subcategory) as subcategories
        FROM taxonomy_categories c
        LEFT JOIN taxonomy_subcategories s ON c.category = s.category
        GROUP BY c.category, c.display_order
        ORDER BY c.display_order
    """)
    
    taxonomy = {}
    for row in cursor.fetchall():
        category = row[0]
        subcategories = row[2] if row[2] else []
        taxonomy[category] = subcategories
    
    cursor.close()
    return taxonomy


def get_transactions_needing_review(conn, limit: int = None) -> List[Dict]:
    """Get transactions that need review"""
    cursor = conn.cursor()
    
    query = """
        SELECT txn_id, merchant_norm, merchant_detail, description_raw,
               amount, direction, txn_date, category, subcategory
        FROM transactions
        WHERE needs_review = TRUE
        ORDER BY txn_date DESC, amount DESC
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query)
    
    transactions = []
    for row in cursor.fetchall():
        transactions.append({
            'txn_id': row[0],
            'merchant_norm': row[1],
            'merchant_detail': row[2],
            'description_raw': row[3],
            'amount': float(row[4]),
            'direction': row[5],
            'txn_date': row[6],
            'category': row[7],
            'subcategory': row[8],
        })
    
    cursor.close()
    return transactions


def display_transaction(txn: Dict, index: int, total: int):
    """Display transaction details"""
    print("\n" + "=" * 80)
    print(f"Transaction {index}/{total}")
    print("=" * 80)
    
    merchant = txn['merchant_norm']
    if txn['merchant_detail']:
        merchant += f" ({txn['merchant_detail']})"
    
    print(f"Merchant:     {merchant}")
    print(f"Description:  {txn['description_raw'][:60]}")
    print(f"Amount:       ${abs(txn['amount']):.2f}")
    print(f"Date:         {txn['txn_date']}")
    print(f"Current:      {txn['category']} / {txn['subcategory']}")


def display_categories(taxonomy: Dict):
    """Display available categories"""
    print("\n📂 Available Categories:")
    print("-" * 80)
    
    for i, category in enumerate(taxonomy.keys(), 1):
        print(f"{i:2d}. {category}")


def display_subcategories(category: str, subcategories: List[str]):
    """Display subcategories for a category"""
    print(f"\n📁 Subcategories for '{category}':")
    print("-" * 80)
    
    for i, subcat in enumerate(subcategories, 1):
        print(f"{i:2d}. {subcat}")


def get_user_choice(prompt: str, max_value: int, allow_skip: bool = True) -> int:
    """Get user's numeric choice"""
    while True:
        skip_text = " (or 's' to skip)" if allow_skip else ""
        user_input = input(f"\n{prompt} (1-{max_value}){skip_text}: ").strip().lower()
        
        if allow_skip and user_input == 's':
            return -1
        
        if user_input == 'q':
            return -2
        
        try:
            choice = int(user_input)
            if 1 <= choice <= max_value:
                return choice
            else:
                print(f"❌ Please enter a number between 1 and {max_value}")
        except ValueError:
            print(f"❌ Invalid input. Please enter a number.")


def update_transaction(conn, txn_id: int, category: str, subcategory: str):
    """Update transaction category"""
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE transactions
        SET category = %s,
            subcategory = %s,
            needs_review = FALSE,
            tag_source = 'manual',
            tag_confidence = 1.0
        WHERE txn_id = %s
    """, (category, subcategory, txn_id))
    
    conn.commit()
    cursor.close()


def create_rule(conn, merchant_norm: str, merchant_detail: str, 
                category: str, subcategory: str, composite: bool = False):
    """Create a categorization rule"""
    cursor = conn.cursor()
    
    # Check if rule already exists
    if composite and merchant_detail:
        cursor.execute("""
            SELECT rule_id FROM merchant_rules
            WHERE match_value = %s AND match_detail = %s
        """, (merchant_norm, merchant_detail))
    else:
        cursor.execute("""
            SELECT rule_id FROM merchant_rules
            WHERE match_value = %s AND match_detail IS NULL
        """, (merchant_norm,))
    
    if cursor.fetchone():
        print(f"   ℹ️  Rule already exists for this merchant")
        cursor.close()
        return
    
    # Create new rule
    if composite and merchant_detail:
        cursor.execute("""
            INSERT INTO merchant_rules (
                rule_pack, priority, match_type, match_value, match_detail,
                category, subcategory, is_active, notes
            ) VALUES (
                'manual', 10, 'exact', %s, %s,
                %s, %s, TRUE, 'Created via review tool'
            )
        """, (merchant_norm, merchant_detail, category, subcategory))
        print(f"   ✅ Created composite rule: {merchant_norm} + {merchant_detail}")
    else:
        cursor.execute("""
            INSERT INTO merchant_rules (
                rule_pack, priority, match_type, match_value,
                category, subcategory, is_active, notes
            ) VALUES (
                'manual', 10, 'exact', %s,
                %s, %s, TRUE, 'Created via review tool'
            )
        """, (merchant_norm, category, subcategory))
        print(f"   ✅ Created rule: {merchant_norm}")
    
    conn.commit()
    cursor.close()


def main():
    """Main review function"""
    print("=" * 80)
    print("📝 TRANSACTION REVIEW")
    print("=" * 80)
    
    # Connect to database
    try:
        conn = get_db_connection()
        print("✅ Connected to database")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)
    
    try:
        # Load taxonomy
        print("📚 Loading taxonomy...")
        taxonomy = load_taxonomy(conn)
        print(f"✅ Loaded {len(taxonomy)} categories")
        
        # Get transactions needing review
        print("\n🔍 Finding transactions needing review...")
        transactions = get_transactions_needing_review(conn)
        
        if not transactions:
            print("\n🎉 No transactions need review! All categorized!")
            return
        
        print(f"✅ Found {len(transactions)} transactions needing review")
        
        # Review each transaction
        reviewed = 0
        skipped = 0
        
        for i, txn in enumerate(transactions, 1):
            display_transaction(txn, i, len(transactions))
            
            # Ask if user wants to categorize
            print("\n⚙️  Options:")
            print("   1. Categorize this transaction")
            print("   2. Skip to next")
            print("   3. Quit (save and exit)")
            
            action = input("\nChoose action (1-3): ").strip()
            
            if action == '3' or action.lower() == 'q':
                print(f"\n✅ Reviewed {reviewed} transactions, skipped {skipped}")
                break
            
            if action == '2' or action.lower() == 's':
                skipped += 1
                continue
            
            if action != '1':
                print("❌ Invalid choice, skipping...")
                skipped += 1
                continue
            
            # Show categories
            display_categories(taxonomy)
            
            # Get category choice
            categories_list = list(taxonomy.keys())
            cat_choice = get_user_choice("Select category", len(categories_list))
            
            if cat_choice == -2:  # Quit
                break
            if cat_choice == -1:  # Skip
                skipped += 1
                continue
            
            category = categories_list[cat_choice - 1]
            subcategories = taxonomy[category]
            
            # Show subcategories
            display_subcategories(category, subcategories)
            
            # Get subcategory choice
            subcat_choice = get_user_choice("Select subcategory", len(subcategories))
            
            if subcat_choice == -2:  # Quit
                break
            if subcat_choice == -1:  # Skip
                skipped += 1
                continue
            
            subcategory = subcategories[subcat_choice - 1]
            
            # Ask if should create rule
            print(f"\n💡 Categorize '{txn['merchant_norm']}' as {category} / {subcategory}")
            
            create_rule_choice = input("Create rule for future transactions? (y/n): ").strip().lower()
            
            # If merchant has detail (Square, Zelle, etc.), ask if composite rule
            composite = False
            if create_rule_choice == 'y' and txn['merchant_detail']:
                print(f"\n   Merchant detail found: {txn['merchant_detail']}")
                composite_choice = input(f"   Create rule for '{txn['merchant_norm']}' only or '{txn['merchant_norm']} + {txn['merchant_detail']}'? (simple/composite): ").strip().lower()
                composite = composite_choice == 'composite' or composite_choice == 'c'
            
            # Update transaction
            print("\n💾 Saving...")
            update_transaction(conn, txn['txn_id'], category, subcategory)
            print(f"   ✅ Updated transaction")
            
            # Create rule if requested
            if create_rule_choice == 'y':
                create_rule(conn, txn['merchant_norm'], txn['merchant_detail'], 
                          category, subcategory, composite)
            
            reviewed += 1
        
        # Summary
        print("\n" + "=" * 80)
        print("📊 REVIEW SUMMARY")
        print("=" * 80)
        print(f"✅ Categorized: {reviewed}")
        print(f"⏭️  Skipped: {skipped}")
        
        # Check remaining
        remaining = get_transactions_needing_review(conn)
        if remaining:
            print(f"⚠️  Still need review: {len(remaining)}")
        else:
            print(f"🎉 All transactions categorized!")
        
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
