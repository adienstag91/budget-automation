#!/usr/bin/env python3
"""
Database initialization script

Sets up the budget database with schema, taxonomy, and rules.
"""
import json
import sys
from pathlib import Path

from budget_automation.utils.db_connection import get_db_connection


def run_sql_file(conn, sql_file: Path, description: str):
    """Execute a SQL file"""
    print(f"\n📄 {description}")
    print(f"   File: {sql_file}")
    
    with open(sql_file, 'r') as f:
        sql = f.read()
    
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        conn.commit()
        print(f"   ✅ Success")
    except Exception as e:
        conn.rollback()
        print(f"   ❌ Error: {e}")
        raise
    finally:
        cursor.close()


def load_taxonomy(conn, taxonomy_file: Path):
    """Load taxonomy from JSON into database"""
    print(f"\n📚 Loading taxonomy from {taxonomy_file}")
    
    with open(taxonomy_file, 'r') as f:
        taxonomy = json.load(f)
    
    cursor = conn.cursor()
    
    try:
        # Clear existing taxonomy
        cursor.execute("DELETE FROM taxonomy_categories")
        
        # Insert categories and subcategories
        for cat in taxonomy['categories']:
            cursor.execute("""
                INSERT INTO taxonomy_categories (category, display_order, is_income, is_transfer)
                VALUES (%s, %s, %s, %s)
            """, (cat['name'], cat['display_order'], cat['is_income'], cat['is_transfer']))
            
            for subcat in cat['subcategories']:
                cursor.execute("""
                    INSERT INTO taxonomy_subcategories (category, subcategory)
                    VALUES (%s, %s)
                """, (cat['name'], subcat))
        
        conn.commit()
        
        # Print summary
        cursor.execute("SELECT COUNT(*) FROM taxonomy_categories")
        cat_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM taxonomy_subcategories")
        subcat_count = cursor.fetchone()[0]
        
        print(f"   ✅ Loaded {cat_count} categories, {subcat_count} subcategories")
        
    except Exception as e:
        conn.rollback()
        print(f"   ❌ Error: {e}")
        raise
    finally:
        cursor.close()


def create_default_accounts(conn):
    """Create default Chase accounts"""
    print(f"\n🏦 Creating default accounts")
    
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM accounts")
        if cursor.fetchone()[0] > 0:
            print(f"   ⚠️  Accounts already exist, skipping")
            return
        
        accounts = [
            ('Chase Checking', 'checking', 'Chase', True),
            ('Chase Sapphire Credit', 'credit', 'Chase', True),
        ]
        
        cursor.executemany("""
            INSERT INTO accounts (account_name, account_type, institution, is_active)
            VALUES (%s, %s, %s, %s)
        """, accounts)
        
        conn.commit()
        print(f"   ✅ Created {len(accounts)} accounts")
        
    except Exception as e:
        conn.rollback()
        print(f"   ❌ Error: {e}")
        raise
    finally:
        cursor.close()


def print_summary(conn):
    """Print database summary"""
    cursor = conn.cursor()
    
    print("\n" + "=" * 80)
    print("📊 DATABASE SUMMARY")
    print("=" * 80)
    
    cursor.execute("SELECT COUNT(*) FROM taxonomy_categories")
    print(f"Categories: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM taxonomy_subcategories")
    print(f"Subcategories: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM accounts")
    print(f"Accounts: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT rule_pack, COUNT(*) FROM merchant_rules GROUP BY rule_pack ORDER BY rule_pack")
    print(f"\nMerchant Rules:")
    for pack, count in cursor.fetchall():
        cursor.execute("""
            SELECT COUNT(*) FROM merchant_rules 
            WHERE rule_pack = %s AND match_detail IS NOT NULL
        """, (pack,))
        composite_count = cursor.fetchone()[0]
        print(f"  • {pack}: {count} rules ({composite_count} composite)")
    
    cursor.execute("SELECT COUNT(*) FROM merchant_rules")
    print(f"  Total: {cursor.fetchone()[0]} rules")
    
    cursor.execute("SELECT COUNT(*) FROM transactions")
    print(f"\nTransactions: {cursor.fetchone()[0]}")
    
    print("=" * 80)
    
    cursor.close()


def main():
    """Main initialization function"""
    print("=" * 80)
    print("🚀 BUDGET DATABASE INITIALIZATION")
    print("=" * 80)
    
    # Get project root
    project_root = Path(__file__).parent.parent.parent
    
    # Paths
    schema_file = project_root / "budget_automation" / "db" / "db_schema.sql"
    taxonomy_file = project_root / "data" / "taxonomy" / "taxonomy.json"
    learned_rules_file = project_root / "data" / "rules" / "learned_rules.sql"
    manual_rules_file = project_root / "data" / "rules" / "manual_rules.sql"
    
    # Check files exist
    required_files = [schema_file, taxonomy_file, learned_rules_file, manual_rules_file]
    missing = [f for f in required_files if not f.exists()]
    if missing:
        print(f"\n❌ Missing required files:")
        for f in missing:
            print(f"   • {f}")
        sys.exit(1)
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    try:
        conn = get_db_connection()
        print("   ✅ Connected")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        print("\nMake sure Docker is running:")
        print("   docker-compose up -d")
        sys.exit(1)
    
    try:
        # 1. Create schema
        run_sql_file(conn, schema_file, "Creating database schema")
        
        # 2. Load taxonomy
        load_taxonomy(conn, taxonomy_file)
        
        # 3. Create accounts
        create_default_accounts(conn)
        
        # 4. Load learned rules
        run_sql_file(conn, learned_rules_file, "Loading learned rules (from historical data)")
        
        # 5. Load manual rules
        run_sql_file(conn, manual_rules_file, "Loading manual rules (high-priority)")
        
        # 6. Print summary
        print_summary(conn)
        
        print("\n✅ Database initialization complete!")
        print("\nNext steps:")
        print("  1. Import transactions: budget-import /path/to/chase.csv")
        print("  2. Or use: python -m budget_automation.cli.import_csv /path/to/chase.csv")
        
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
