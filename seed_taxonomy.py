"""
Seed taxonomy from taxonomy.json into the database
"""
import json
import psycopg2
from pathlib import Path

def load_taxonomy(db_conn, taxonomy_file):
    """Load taxonomy from JSON file into database"""
    
    with open(taxonomy_file, 'r') as f:
        taxonomy = json.load(f)
    
    cursor = db_conn.cursor()
    
    try:
        # Clear existing taxonomy (cascades to subcategories)
        cursor.execute("DELETE FROM taxonomy_categories")
        
        # Insert categories and subcategories
        for cat in taxonomy['categories']:
            # Insert category
            cursor.execute("""
                INSERT INTO taxonomy_categories (category, display_order, is_income, is_transfer)
                VALUES (%s, %s, %s, %s)
            """, (
                cat['name'],
                cat['display_order'],
                cat['is_income'],
                cat['is_transfer']
            ))
            
            # Insert subcategories
            for subcat in cat['subcategories']:
                cursor.execute("""
                    INSERT INTO taxonomy_subcategories (category, subcategory)
                    VALUES (%s, %s)
                """, (cat['name'], subcat))
        
        db_conn.commit()
        print(f"✅ Loaded {len(taxonomy['categories'])} categories with their subcategories")
        
        # Print summary
        cursor.execute("SELECT COUNT(*) FROM taxonomy_categories")
        cat_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM taxonomy_subcategories")
        subcat_count = cursor.fetchone()[0]
        
        print(f"   {cat_count} categories, {subcat_count} subcategories")
        
    except Exception as e:
        db_conn.rollback()
        print(f"❌ Error loading taxonomy: {e}")
        raise
    finally:
        cursor.close()

def main():
    """Main function"""
    # Database connection
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="budget_db",
        user="budget_user",
        password="budget_password_local_dev"
    )
    
    # Path to taxonomy file
    taxonomy_file = Path(__file__).parent.parent / "data" / "taxonomy.json"
    
    print(f"Loading taxonomy from: {taxonomy_file}")
    load_taxonomy(conn, taxonomy_file)
    
    conn.close()
    print("✅ Done!")

if __name__ == "__main__":
    main()
