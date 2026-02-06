#!/usr/bin/env python3
"""
Quick script to explore Amazon order data structure
"""
import os
from pathlib import Path
import csv

def explore_amazon_data(base_path):
    """Explore the Amazon order data structure"""
    base_path = Path(base_path).expanduser()
    
    print("=" * 80)
    print("📦 AMAZON ORDER DATA STRUCTURE")
    print("=" * 80)
    print(f"Base path: {base_path}\n")
    
    if not base_path.exists():
        print(f"❌ Path not found: {base_path}")
        return
    
    # Show directory tree
    print("📁 Directory Structure:")
    print("-" * 80)
    
    for root, dirs, files in os.walk(base_path):
        level = root.replace(str(base_path), '').count(os.sep)
        indent = ' ' * 2 * level
        folder_name = os.path.basename(root) or base_path.name
        print(f'{indent}📁 {folder_name}/')
        
        sub_indent = ' ' * 2 * (level + 1)
        for file in sorted(files):
            size = os.path.getsize(os.path.join(root, file))
            size_str = f"{size:,} bytes" if size < 1024 else f"{size/1024:.1f} KB"
            print(f'{sub_indent}📄 {file} ({size_str})')
    
    print("\n" + "=" * 80)
    print("📋 CSV FILE PREVIEWS")
    print("=" * 80)
    
    # Find and preview all CSV files
    csv_files = list(base_path.rglob("*.csv"))
    
    if not csv_files:
        print("⚠️  No CSV files found!")
        return
    
    for csv_file in csv_files:
        print(f"\n{'=' * 80}")
        print(f"📄 {csv_file.relative_to(base_path)}")
        print(f"{'=' * 80}")
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                # Read first few lines
                lines = [next(f) for _ in range(min(5, sum(1 for _ in open(csv_file))))]
                
                # Try to parse as CSV
                reader = csv.reader(lines)
                rows = list(reader)
                
                if rows:
                    print(f"\nColumns ({len(rows[0])}):")
                    for i, col in enumerate(rows[0], 1):
                        print(f"  {i}. {col}")
                    
                    if len(rows) > 1:
                        print(f"\nFirst data row (preview):")
                        for i, (col, val) in enumerate(zip(rows[0], rows[1]), 1):
                            # Truncate long values
                            val_preview = val[:50] + "..." if len(val) > 50 else val
                            print(f"  {col}: {val_preview}")
                    
                    print(f"\nTotal rows: ~{sum(1 for _ in open(csv_file, encoding='utf-8'))}")
                
        except Exception as e:
            print(f"⚠️  Could not parse: {e}")
    
    print("\n" + "=" * 80)
    print("✅ Exploration complete!")
    print("=" * 80)

if __name__ == "__main__":
    import sys
    
    path = sys.argv[1] if len(sys.argv) > 1 else "~/Downloads/Your Orders"
    explore_amazon_data(path)
