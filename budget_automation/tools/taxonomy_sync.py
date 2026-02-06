"""
Taxonomy Sync Tool

Syncs taxonomy.json file with the database taxonomy_subcategories table.
Ensures the database foreign key constraints match your taxonomy definitions.
"""
import json
from pathlib import Path
import argparse

from budget_automation.utils.db_connection import get_db_connection


def load_taxonomy_from_file(taxonomy_path):
    """Load and parse taxonomy.json"""
    with open(taxonomy_path) as f:
        raw_data = json.load(f)
    
    # Extract categories from wrapper structure
    if isinstance(raw_data, dict) and 'categories' in raw_data:
        raw_taxonomy = raw_data['categories']
    else:
        raw_taxonomy = raw_data
    
    # Build flat list of (category, subcategory) tuples
    taxonomy_pairs = []
    
    # Handle list format
    if isinstance(raw_taxonomy, list):
        for item in raw_taxonomy:
            if isinstance(item, dict):
                cat_name = item.get('category', item.get('name', ''))
                subcats = item.get('subcategories', item.get('subcats', []))
                
                for subcat in subcats:
                    if isinstance(subcat, dict):
                        subcat_name = subcat.get('name', subcat.get('subcategory', ''))
                    else:
                        subcat_name = str(subcat)
                    
                    if cat_name and subcat_name:
                        taxonomy_pairs.append((cat_name, subcat_name))
    
    # Handle dict format
    elif isinstance(raw_taxonomy, dict):
        for category, subcats in raw_taxonomy.items():
            if isinstance(subcats, list):
                for subcat in subcats:
                    if isinstance(subcat, dict):
                        subcat_name = subcat.get('name', subcat.get('subcategory', ''))
                    else:
                        subcat_name = str(subcat)
                    
                    if subcat_name:
                        taxonomy_pairs.append((category, subcat_name))
    
    return set(taxonomy_pairs)


def load_taxonomy_from_db(conn):
    """Load taxonomy from database"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, subcategory
        FROM taxonomy_subcategories
        ORDER BY category, subcategory
    """)
    
    db_taxonomy = set(cursor.fetchall())
    cursor.close()
    
    return db_taxonomy


def sync_taxonomy(taxonomy_path, dry_run=False, remove_orphans=False):
    """
    Sync taxonomy.json with database
    
    Args:
        taxonomy_path: Path to taxonomy.json file
        dry_run: If True, show what would change without making changes
        remove_orphans: If True, remove DB entries not in taxonomy.json
    """
    print("=" * 80)
    print("🔄 TAXONOMY SYNC")
    print("=" * 80)
    print(f"Taxonomy file: {taxonomy_path}")
    print(f"Dry run: {dry_run}")
    print(f"Remove orphans: {remove_orphans}")
    print("=" * 80)
    
    # Load taxonomy from file
    print("\n📄 Loading taxonomy.json...")
    file_taxonomy = load_taxonomy_from_file(taxonomy_path)
    print(f"✅ Found {len(file_taxonomy)} category/subcategory pairs in file")
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    conn = get_db_connection()
    print("✅ Connected")
    
    # Load taxonomy from database
    print("\n📊 Loading taxonomy from database...")
    db_taxonomy = load_taxonomy_from_db(conn)
    print(f"✅ Found {len(db_taxonomy)} pairs in database")
    
    # Calculate differences
    print("\n🔍 Analyzing differences...")
    
    to_add = file_taxonomy - db_taxonomy
    to_remove = db_taxonomy - file_taxonomy if remove_orphans else set()
    
    print(f"\n📊 Summary:")
    print(f"  • To add to DB: {len(to_add)}")
    print(f"  • To remove from DB: {len(to_remove)}")
    print(f"  • Already in sync: {len(file_taxonomy & db_taxonomy)}")
    
    if not to_add and not to_remove:
        print("\n✅ Database is already in sync with taxonomy.json!")
        conn.close()
        return
    
    # Show what will change
    if to_add:
        print("\n➕ ADDING TO DATABASE:")
        for category, subcategory in sorted(to_add):
            print(f"   • {category} / {subcategory}")
    
    if to_remove:
        print("\n➖ REMOVING FROM DATABASE:")
        for category, subcategory in sorted(to_remove):
            print(f"   • {category} / {subcategory}")
    
    # Execute changes
    if dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN - No changes made")
        print("=" * 80)
    else:
        # Confirm if interactive
        import sys
        if sys.stdout.isatty():
            print("\n" + "=" * 80)
            response = input(f"Apply {len(to_add) + len(to_remove)} changes? (y/n): ")
            if response.lower() != 'y':
                print("❌ Cancelled")
                conn.close()
                return
        
        cursor = conn.cursor()
        
        # Add new entries
        if to_add:
            print(f"\n➕ Adding {len(to_add)} entries...")
            
            # First, ensure all categories exist in taxonomy_categories table
            categories_to_add = set(category for category, _ in to_add)
            
            print(f"   Ensuring {len(categories_to_add)} categories exist...")
            
            # Get current max display_order
            cursor.execute("SELECT COALESCE(MAX(display_order), 0) FROM taxonomy_categories")
            max_order = cursor.fetchone()[0]
            
            for i, category in enumerate(sorted(categories_to_add), 1):
                cursor.execute("""
                    INSERT INTO taxonomy_categories (category, display_order)
                    VALUES (%s, %s)
                    ON CONFLICT (category) DO NOTHING
                """, (category, max_order + i))
            
            # Then add subcategories
            print(f"   Adding {len(to_add)} subcategories...")
            for category, subcategory in to_add:
                cursor.execute("""
                    INSERT INTO taxonomy_subcategories (category, subcategory)
                    VALUES (%s, %s)
                    ON CONFLICT (category, subcategory) DO NOTHING
                """, (category, subcategory))
            print("✅ Added successfully")
        
        # Remove orphaned entries
        if to_remove:
            print(f"\n➖ Removing {len(to_remove)} entries...")
            for category, subcategory in to_remove:
                # Check if any transactions use this
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions
                    WHERE category = %s AND subcategory = %s
                """, (category, subcategory))
                
                count = cursor.fetchone()[0]
                
                if count > 0:
                    print(f"   ⚠️  Skipping {category}/{subcategory} - used by {count} transactions")
                else:
                    cursor.execute("""
                        DELETE FROM taxonomy_subcategories
                        WHERE category = %s AND subcategory = %s
                    """, (category, subcategory))
                    print(f"   ✅ Removed {category}/{subcategory}")
        
        conn.commit()
        cursor.close()
        
        print("\n" + "=" * 80)
        print("✅ Sync complete!")
        print("=" * 80)
    
    conn.close()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Sync taxonomy.json with database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - see what would change
  python taxonomy_sync.py --dry-run
  
  # Apply changes (add missing entries)
  python taxonomy_sync.py
  
  # Also remove DB entries not in taxonomy.json
  python taxonomy_sync.py --remove-orphans
  
  # Custom taxonomy file location
  python taxonomy_sync.py --file /path/to/taxonomy.json
        """
    )
    
    parser.add_argument(
        '--file',
        default='data/taxonomy/taxonomy.json',
        help='Path to taxonomy.json file (default: data/taxonomy/taxonomy.json)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would change without making changes'
    )
    
    parser.add_argument(
        '--remove-orphans',
        action='store_true',
        help='Remove database entries not present in taxonomy.json (skips if used by transactions)'
    )
    
    args = parser.parse_args()
    
    # Resolve file path
    taxonomy_path = Path(args.file)
    if not taxonomy_path.exists():
        print(f"❌ Error: Taxonomy file not found: {taxonomy_path}")
        return 1
    
    sync_taxonomy(taxonomy_path, dry_run=args.dry_run, remove_orphans=args.remove_orphans)
    
    return 0


if __name__ == "__main__":
    exit(main())
