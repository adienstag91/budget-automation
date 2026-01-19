"""
Learning Engine - Extract categorization patterns from historical data

Analyzes Budget_-_Data.csv to build high-confidence merchant rules.
"""
import csv
import html
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json

from merchant_normalizer import normalize_merchant


class MerchantPatternLearner:
    """
    Learns categorization patterns from historical transaction data
    """
    
    def __init__(self, min_occurrences: int = 3, min_consistency: float = 0.90):
        """
        Args:
            min_occurrences: Minimum times a merchant must appear to create a rule
            min_consistency: Minimum % of times merchant gets same category (0.90 = 90%)
        """
        self.min_occurrences = min_occurrences
        self.min_consistency = min_consistency
        
        # Storage for analysis
        self.merchant_categories = defaultdict(list)  # merchant_norm -> [(category, subcategory), ...]
        self.merchant_descriptions = defaultdict(set)  # merchant_norm -> {raw descriptions}
        self.category_stats = Counter()  # category -> count
        self.subcategory_stats = Counter()  # (category, subcategory) -> count
        
        # Results
        self.high_confidence_rules = []
        self.medium_confidence_rules = []
        self.conflicts = []
    
    def parse_historical_data(self, csv_path: Path) -> List[Dict]:
        """
        Parse the Budget_-_Data.csv file
        
        Expected columns: Transaction Date,Post Date,Description,Category,Sub Category,Type,Amount,Year,Month Number,Month
        """
        transactions = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                description = html.unescape(row['Description'].strip())
                category = row['Category'].strip()
                subcategory = row['Sub Category'].strip()
                
                # Skip empty categories
                if not category or category == 'Category':
                    continue
                
                # Normalize merchant
                merchant_norm, merchant_detail = normalize_merchant(description)
                
                txn = {
                    'description_raw': description,
                    'merchant_norm': merchant_norm,
                    'merchant_detail': merchant_detail,
                    'category': category,
                    'subcategory': subcategory,
                    'type': row['Type'].strip() if row['Type'] else None,
                    'amount': float(row['Amount']) if row['Amount'] else 0.0,
                }
                
                transactions.append(txn)
        
        print(f"✅ Loaded {len(transactions)} historical transactions")
        return transactions
    
    def analyze_patterns(self, transactions: List[Dict]):
        """
        Analyze transactions to find patterns
        """
        print("\n📊 Analyzing patterns...")
        
        for txn in transactions:
            merchant = txn['merchant_norm']
            category = txn['category']
            subcategory = txn['subcategory']
            
            # Track merchant->category mappings
            self.merchant_categories[merchant].append((category, subcategory))
            
            # Track raw descriptions for reference
            self.merchant_descriptions[merchant].add(txn['description_raw'])
            
            # Track overall category usage
            self.category_stats[category] += 1
            self.subcategory_stats[(category, subcategory)] += 1
        
        print(f"   Found {len(self.merchant_categories)} unique merchants")
        print(f"   Found {len(self.category_stats)} categories")
        print(f"   Found {len(self.subcategory_stats)} category/subcategory pairs")
    
    def generate_rules(self):
        """
        Generate high-confidence rules from patterns
        """
        print("\n🔧 Generating rules...")
        
        # Manual overrides for specific known cases
        manual_overrides = {
            'EAST PARK BEVERAGE': ('Food & Drink', 'Alcohol'),  # No longer vaping
        }
        
        for merchant, categories in self.merchant_categories.items():
            # Check for manual override first
            if merchant in manual_overrides:
                override_cat, override_subcat = manual_overrides[merchant]
                total = len(categories)
                
                self.high_confidence_rules.append({
                    'merchant_norm': merchant,
                    'category': override_cat,
                    'subcategory': override_subcat,
                    'occurrences': total,
                    'consistency': 1.0,  # Manual override = 100%
                    'sample_descriptions': list(self.merchant_descriptions[merchant])[:3],
                })
                continue
            
            # Count occurrences
            total = len(categories)
            
            # Skip if not enough data
            if total < self.min_occurrences:
                continue
            
            # Count category frequencies
            category_counts = Counter(categories)
            most_common_cat, count = category_counts.most_common(1)[0]
            consistency = count / total
            
            # Determine rule type
            rule = {
                'merchant_norm': merchant,
                'category': most_common_cat[0],
                'subcategory': most_common_cat[1],
                'occurrences': total,
                'consistency': consistency,
                'sample_descriptions': list(self.merchant_descriptions[merchant])[:3],
            }
            
            if consistency >= self.min_consistency:
                # High confidence rule
                self.high_confidence_rules.append(rule)
            elif consistency >= 0.70:
                # Medium confidence (70-90%)
                self.medium_confidence_rules.append(rule)
            else:
                # Conflict - merchant categorized inconsistently
                all_cats = [f"{cat}→{subcat} ({ct})" for (cat, subcat), ct in category_counts.most_common()]
                self.conflicts.append({
                    **rule,
                    'all_categories': all_cats,
                })
        
        # Sort by occurrences (most frequent first)
        self.high_confidence_rules.sort(key=lambda x: x['occurrences'], reverse=True)
        self.medium_confidence_rules.sort(key=lambda x: x['occurrences'], reverse=True)
        self.conflicts.sort(key=lambda x: x['occurrences'], reverse=True)
        
        print(f"   ✅ {len(self.high_confidence_rules)} high-confidence rules (≥{self.min_consistency*100:.0f}% consistency)")
        print(f"   ⚠️  {len(self.medium_confidence_rules)} medium-confidence rules (70-90% consistency)")
        print(f"   ❌ {len(self.conflicts)} conflicts (merchants with inconsistent categorization)")
    
    def export_rules_to_sql(self, output_path: Path, rule_pack: str = 'learned'):
        """
        Export high-confidence rules as SQL INSERT statements
        
        Args:
            output_path: Path to output SQL file
            rule_pack: Rule pack name (default: 'learned')
        """
        with open(output_path, 'w') as f:
            f.write("-- Auto-generated merchant rules from historical data\n")
            f.write("-- Generated by learning engine\n\n")
            
            f.write(f"-- High-confidence rules ({len(self.high_confidence_rules)} rules)\n")
            f.write("INSERT INTO merchant_rules (rule_pack, priority, match_type, match_value, category, subcategory, is_active, created_by, notes)\n")
            f.write("VALUES\n")
            
            for i, rule in enumerate(self.high_confidence_rules):
                merchant = rule['merchant_norm'].replace("'", "''")  # Escape single quotes
                category = rule['category'].replace("'", "''")
                subcategory = rule['subcategory'].replace("'", "''")
                notes = f"{rule['occurrences']} occurrences, {rule['consistency']*100:.1f}% consistency"
                
                comma = "," if i < len(self.high_confidence_rules) - 1 else ";"
                
                f.write(f"  ('{rule_pack}', 100, 'exact', '{merchant}', '{category}', '{subcategory}', TRUE, 'learned', '{notes}'){comma}\n")
            
            f.write("\n")
        
        print(f"✅ Exported rules to {output_path}")
    
    def export_rules_to_json(self, output_path: Path):
        """
        Export all analysis results to JSON for review
        """
        data = {
            'high_confidence_rules': self.high_confidence_rules,
            'medium_confidence_rules': self.medium_confidence_rules,
            'conflicts': self.conflicts,
            'category_stats': dict(self.category_stats),
            'parameters': {
                'min_occurrences': self.min_occurrences,
                'min_consistency': self.min_consistency,
            }
        }
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Exported analysis to {output_path}")
    
    def print_summary(self):
        """Print a summary of the analysis"""
        print("\n" + "=" * 80)
        print("📈 LEARNING ENGINE SUMMARY")
        print("=" * 80)
        
        print(f"\n✅ HIGH-CONFIDENCE RULES ({len(self.high_confidence_rules)}):")
        print(f"   These merchants are categorized consistently (≥{self.min_consistency*100:.0f}%)")
        for rule in self.high_confidence_rules[:10]:
            print(f"   • {rule['merchant_norm']:<30} → {rule['category']:>20} / {rule['subcategory']:<20} ({rule['occurrences']} times, {rule['consistency']*100:.0f}%)")
        if len(self.high_confidence_rules) > 10:
            print(f"   ... and {len(self.high_confidence_rules) - 10} more")
        
        if self.medium_confidence_rules:
            print(f"\n⚠️  MEDIUM-CONFIDENCE RULES ({len(self.medium_confidence_rules)}):")
            print(f"   These merchants have some inconsistency (70-90%)")
            for rule in self.medium_confidence_rules[:5]:
                print(f"   • {rule['merchant_norm']:<30} → {rule['category']:>20} / {rule['subcategory']:<20} ({rule['occurrences']} times, {rule['consistency']*100:.0f}%)")
            if len(self.medium_confidence_rules) > 5:
                print(f"   ... and {len(self.medium_confidence_rules) - 5} more")
        
        if self.conflicts:
            print(f"\n❌ CONFLICTS ({len(self.conflicts)}):")
            print(f"   These merchants are categorized inconsistently (<70%)")
            for conflict in self.conflicts[:5]:
                print(f"   • {conflict['merchant_norm']:<30} ({conflict['occurrences']} times)")
                print(f"     Categories: {', '.join(conflict['all_categories'])}")
            if len(self.conflicts) > 5:
                print(f"   ... and {len(self.conflicts) - 5} more")
        
        print("\n" + "=" * 80)


def main():
    """Main function - run the learning engine"""
    # Paths
    historical_csv = Path("/mnt/user-data/uploads/Budget_-_Data.csv")
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    
    rules_sql = output_dir / "learned_rules.sql"
    analysis_json = output_dir / "learned_analysis.json"
    
    print("🧠 BUDGET AUTOMATION - LEARNING ENGINE")
    print("=" * 80)
    print(f"📁 Historical data: {historical_csv}")
    print(f"📊 Output: {rules_sql}")
    print("=" * 80)
    
    # Initialize learner
    learner = MerchantPatternLearner(
        min_occurrences=3,     # Must appear at least 3 times
        min_consistency=0.90   # Must be consistent 90% of the time
    )
    
    # Load and analyze historical data
    transactions = learner.parse_historical_data(historical_csv)
    learner.analyze_patterns(transactions)
    learner.generate_rules()
    
    # Export results
    learner.export_rules_to_sql(rules_sql, rule_pack='learned')
    learner.export_rules_to_json(analysis_json)
    
    # Print summary
    learner.print_summary()
    
    print("\n✅ Done! Review the learned rules and conflicts.")
    print(f"   SQL rules: {rules_sql}")
    print(f"   Full analysis: {analysis_json}")


if __name__ == "__main__":
    main()
