"""
Rule Matcher Engine

Matches transactions against merchant rules with support for:
- Simple rules (merchant_norm only)
- Composite rules (merchant_norm + merchant_detail, e.g., "SQ" + "BREADS BAKERY")
- Multiple match types: exact, contains, startswith, regex
- Priority-based rule selection
"""
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class CategorizationResult:
    """Result of categorization attempt"""
    category: Optional[str]
    subcategory: Optional[str]
    tag_source: str  # 'rule', 'llm', 'manual'
    tag_confidence: float  # 0.0 to 1.0
    needs_review: bool
    matched_rule_id: Optional[int] = None
    rationale: Optional[str] = None


class RuleMatcher:
    """
    Matches transactions against merchant rules
    """
    
    def __init__(self):
        self.rules = []
        self.stats = {
            'matches': 0,
            'no_match': 0,
            'by_rule_type': {},
        }
    
    def load_rules(self, rules: List[Dict]):
        """
        Load rules from database or list
        
        Expected dict structure:
        {
            'rule_id': int,
            'rule_pack': str,
            'priority': int,
            'match_type': str,  # 'exact', 'contains', 'startswith', 'regex'
            'match_value': str,  # merchant_norm to match
            'match_detail': str (optional),  # merchant_detail to match
            'category': str,
            'subcategory': str,
            'is_active': bool,
        }
        """
        # Filter active rules and sort by priority (lower = higher priority)
        self.rules = [r for r in rules if r.get('is_active', True)]
        self.rules.sort(key=lambda x: (x['priority'], x['rule_id']))
        
        print(f"✅ Loaded {len(self.rules)} active rules")
    
    def match_rule(self, rule: Dict, merchant_norm: str, merchant_detail: Optional[str]) -> bool:
        """
        Check if a rule matches the given merchant info
        
        Args:
            rule: Rule dictionary
            merchant_norm: Normalized merchant name
            merchant_detail: Additional merchant detail (for SQ, TST, Zelle, etc.)
            
        Returns:
            True if rule matches
        """
        match_type = rule['match_type']
        match_value = rule['match_value'].upper()
        merchant_norm = merchant_norm.upper()
        
        # First: Check if merchant_norm matches
        norm_matches = False
        
        if match_type == 'exact':
            norm_matches = merchant_norm == match_value
        elif match_type == 'contains':
            norm_matches = match_value in merchant_norm
        elif match_type == 'startswith':
            norm_matches = merchant_norm.startswith(match_value)
        elif match_type == 'regex':
            try:
                norm_matches = bool(re.search(match_value, merchant_norm))
            except re.error:
                print(f"⚠️  Invalid regex in rule {rule.get('rule_id')}: {match_value}")
                norm_matches = False
        
        if not norm_matches:
            return False
        
        # Second: If rule has match_detail, check merchant_detail
        if rule.get('match_detail'):
            if not merchant_detail:
                return False  # Rule requires detail but transaction has none
            
            match_detail = rule['match_detail'].upper()
            detail_upper = merchant_detail.upper()
            
            # For detail matching, use 'contains' logic (more flexible)
            return match_detail in detail_upper or detail_upper in match_detail
        
        # No detail requirement, norm match is sufficient
        return True
    
    def categorize(self, 
                   merchant_norm: str, 
                   merchant_detail: Optional[str] = None,
                   description_raw: Optional[str] = None) -> CategorizationResult:
        """
        Categorize a transaction using rules
        
        Args:
            merchant_norm: Normalized merchant name
            merchant_detail: Optional additional detail (payee, business name)
            description_raw: Original description (for context)
            
        Returns:
            CategorizationResult with category info or None
        """
        # Try to find a matching rule
        for rule in self.rules:
            if self.match_rule(rule, merchant_norm, merchant_detail):
                self.stats['matches'] += 1
                self.stats['by_rule_type'][rule.get('rule_pack', 'unknown')] = \
                    self.stats['by_rule_type'].get(rule.get('rule_pack', 'unknown'), 0) + 1
                
                # Build rationale
                rationale = f"Matched rule {rule['rule_id']}"
                if merchant_detail:
                    rationale += f" (detail: {merchant_detail})"
                
                return CategorizationResult(
                    category=rule['category'],
                    subcategory=rule['subcategory'],
                    tag_source='rule',
                    tag_confidence=1.0,  # Rules are 100% confident
                    needs_review=False,
                    matched_rule_id=rule['rule_id'],
                    rationale=rationale,
                )
        
        # No rule matched
        self.stats['no_match'] += 1
        return CategorizationResult(
            category='Uncategorized',
            subcategory='Needs Review',
            tag_source='none',
            tag_confidence=0.0,
            needs_review=True,
            rationale='No matching rule found',
        )
    
    def print_stats(self):
        """Print matching statistics"""
        total = self.stats['matches'] + self.stats['no_match']
        if total == 0:
            print("No transactions processed yet")
            return
        
        print("\n" + "=" * 80)
        print("📊 RULE MATCHER STATISTICS")
        print("=" * 80)
        print(f"Total transactions: {total}")
        print(f"  ✅ Matched: {self.stats['matches']} ({self.stats['matches']/total*100:.1f}%)")
        print(f"  ❌ No match: {self.stats['no_match']} ({self.stats['no_match']/total*100:.1f}%)")
        
        if self.stats['by_rule_type']:
            print(f"\nMatches by rule pack:")
            for pack, count in sorted(self.stats['by_rule_type'].items(), 
                                     key=lambda x: x[1], reverse=True):
                print(f"  • {pack}: {count}")
        print("=" * 80)


def create_manual_rules() -> List[Dict]:
    """
    Create manual rules for specific cases (Zelle, East Park, etc.)
    
    Returns list of rule dicts ready to be added to database
    """
    rules = []
    rule_id = 1000  # Start at 1000 to not conflict with learned rules
    
    # Zelle rules (composite rules using merchant_detail)
    rules.append({
        'rule_id': rule_id,
        'rule_pack': 'manual',
        'priority': 10,  # Higher priority than learned rules
        'match_type': 'exact',
        'match_value': 'ZELLE TO',
        'match_detail': 'DEVI DAYCARE',
        'category': 'Baby',
        'subcategory': 'Daycare',
        'is_active': True,
        'created_by': 'manual',
        'notes': 'Daycare payments via Zelle',
    })
    rule_id += 1
    
    rules.append({
        'rule_id': rule_id,
        'rule_pack': 'manual',
        'priority': 10,
        'match_type': 'exact',
        'match_value': 'ZELLE FROM',
        'match_detail': 'ROBERT DIENSTAG',
        'category': 'Income',
        'subcategory': 'Family Support',
        'is_active': True,
        'created_by': 'manual',
        'notes': 'Weekly support from father',
    })
    rule_id += 1
    
    # East Park Beverage - exclusively alcohol
    rules.append({
        'rule_id': rule_id,
        'rule_pack': 'manual',
        'priority': 10,
        'match_type': 'exact',
        'match_value': 'EAST PARK BEVERAGE',
        'match_detail': None,
        'category': 'Food & Drink',
        'subcategory': 'Alcohol',
        'is_active': True,
        'created_by': 'manual',
        'notes': 'Alcohol purchases (no longer buying vape products)',
    })
    rule_id += 1
    
    # More manual overrides can be added here...
    
    return rules


def export_manual_rules_to_sql(output_path: str):
    """Export manual rules to SQL file"""
    rules = create_manual_rules()
    
    with open(output_path, 'w') as f:
        f.write("-- Manual high-priority rules\n")
        f.write("-- These override learned rules for specific cases\n\n")
        f.write("INSERT INTO merchant_rules (rule_pack, priority, match_type, match_value, match_detail, category, subcategory, is_active, created_by, notes)\n")
        f.write("VALUES\n")
        
        for i, rule in enumerate(rules):
            match_value = rule['match_value'].replace("'", "''")
            if rule['match_detail']:
                match_detail = f"'{rule['match_detail'].replace(chr(39), chr(39)+chr(39))}'"
            else:
                match_detail = 'NULL'
            category = rule['category'].replace("'", "''")
            subcategory = rule['subcategory'].replace("'", "''")
            notes = rule['notes'].replace("'", "''")
            
            comma = "," if i < len(rules) - 1 else ";"
            
            f.write(f"  ('{rule['rule_pack']}', {rule['priority']}, '{rule['match_type']}', '{match_value}', {match_detail}, '{category}', '{subcategory}', TRUE, '{rule['created_by']}', '{notes}'){comma}\n")
    
    print(f"✅ Exported {len(rules)} manual rules to {output_path}")


def test_rule_matcher():
    """Test the rule matcher with sample data"""
    print("Testing Rule Matcher")
    print("=" * 80)
    
    # Create test rules
    test_rules = [
        # Simple rule
        {
            'rule_id': 1,
            'rule_pack': 'test',
            'priority': 100,
            'match_type': 'exact',
            'match_value': 'AMAZON',
            'match_detail': None,
            'category': 'Shopping',
            'subcategory': 'Amazon',
            'is_active': True,
        },
        # Composite rule (SQ + business name)
        {
            'rule_id': 2,
            'rule_pack': 'test',
            'priority': 50,  # Higher priority
            'match_type': 'exact',
            'match_value': 'SQ',
            'match_detail': 'BREADS BAKERY',
            'category': 'Food & Drink',
            'subcategory': 'Coffee',
            'is_active': True,
        },
        # Zelle composite rule
        {
            'rule_id': 3,
            'rule_pack': 'test',
            'priority': 10,
            'match_type': 'exact',
            'match_value': 'ZELLE TO',
            'match_detail': 'DEVI DAYCARE',
            'category': 'Baby',
            'subcategory': 'Daycare',
            'is_active': True,
        },
    ]
    
    matcher = RuleMatcher()
    matcher.load_rules(test_rules)
    
    # Test cases
    test_cases = [
        # (merchant_norm, merchant_detail, expected_category)
        ('AMAZON', None, 'Shopping'),
        ('SQ', 'BREADS BAKERY', 'Food & Drink'),
        ('SQ', 'UNKNOWN BUSINESS', 'Uncategorized'),  # No rule for this SQ business
        ('ZELLE TO', 'DEVI DAYCARE', 'Baby'),
        ('ZELLE TO', 'SOMEONE ELSE', 'Uncategorized'),  # No rule for this payee
        ('UNKNOWN MERCHANT', None, 'Uncategorized'),
    ]
    
    print("\nTest Results:")
    for merchant_norm, merchant_detail, expected in test_cases:
        result = matcher.categorize(merchant_norm, merchant_detail)
        status = "✅" if result.category == expected else "❌"
        detail_str = f" + {merchant_detail}" if merchant_detail else ""
        print(f"{status} {merchant_norm}{detail_str:<30} → {result.category} / {result.subcategory}")
    
    matcher.print_stats()


if __name__ == "__main__":
    # Test the matcher
    test_rule_matcher()
    
    # Export manual rules
    import sys
    from pathlib import Path
    
    output_path = Path(__file__).parent.parent / "data" / "manual_rules.sql"
    export_manual_rules_to_sql(str(output_path))
