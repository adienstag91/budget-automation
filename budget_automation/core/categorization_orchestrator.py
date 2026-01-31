"""
Categorization Orchestrator

The main engine that categorizes transactions using:
1. Rule matching (highest priority)
2. LLM suggestions (fallback for unknowns)
3. Manual review queue (for low confidence)
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from .rule_matcher import RuleMatcher, CategorizationResult
from .llm_categorizer import LLMCategorizer


@dataclass
class Transaction:
    """Transaction data structure"""
    txn_id: Optional[int]
    merchant_norm: str
    merchant_detail: Optional[str]
    description_raw: str
    amount: float
    direction: str
    txn_date: str
    post_date: str
    account_id: int
    source: str
    type: str
    is_return: bool
    
    # Will be filled by categorization
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tag_source: Optional[str] = None
    tag_confidence: Optional[float] = None
    needs_review: bool = False
    notes: Optional[str] = None


class CategorizationOrchestrator:
    """
    Orchestrates transaction categorization using multiple strategies
    """
    
    def __init__(self, 
                 taxonomy: Dict,
                 rules: List[Dict],
                 review_threshold: float = 0.80,
                 enable_llm: bool = True,
                 api_key: Optional[str] = None):
        """
        Args:
            taxonomy: Taxonomy dict with categories and subcategories
            rules: List of merchant rules
            review_threshold: Confidence threshold below which transactions need review
            enable_llm: Whether to use LLM for unknowns
            api_key: Anthropic API key (optional)
        """
        self.taxonomy = taxonomy
        self.review_threshold = review_threshold
        self.enable_llm = enable_llm
        
        # Initialize rule matcher
        self.rule_matcher = RuleMatcher()
        self.rule_matcher.load_rules(rules)
        
        # Initialize LLM categorizer (if enabled)
        self.llm_categorizer = None
        if enable_llm:
            self.llm_categorizer = LLMCategorizer(taxonomy, api_key)
            if not self.llm_categorizer.enabled:
                print("⚠️  LLM categorization requested but API key not found")
                self.enable_llm = True
        
        # Stats
        self.stats = {
            'total': 0,
            'rule_match': 0,
            'llm_suggest': 0,
            'needs_review': 0,
            'high_confidence': 0,
        }
    
    def categorize_transaction(self, txn: Transaction) -> Transaction:
        """
        Categorize a single transaction
        
        Args:
            txn: Transaction object
            
        Returns:
            Updated transaction with categorization
        """
        self.stats['total'] += 1
        
        # Step 1: Try rule matching
        result = self.rule_matcher.categorize(
            txn.merchant_norm,
            txn.merchant_detail,
            txn.description_raw
        )
        
        # If rule matched, use it
        if result.category != 'Uncategorized':
            txn.category = result.category
            txn.subcategory = result.subcategory
            txn.tag_source = 'rule'
            txn.tag_confidence = result.tag_confidence
            txn.needs_review = False
            txn.notes = result.rationale
            
            self.stats['rule_match'] += 1
            self.stats['high_confidence'] += 1
            return txn
        
        # Step 2: Try LLM suggestion (if enabled)
        if self.enable_llm and self.llm_categorizer:
            llm_result = self.llm_categorizer.categorize(
                txn.merchant_norm,
                txn.merchant_detail,
                txn.description_raw,
                txn.amount,
                txn.direction
            )
            
            if llm_result:
                txn.category = llm_result['category']
                txn.subcategory = llm_result['subcategory']
                txn.tag_source = 'llm'
                txn.tag_confidence = llm_result['confidence']
                txn.notes = llm_result['rationale']
                
                # Check if confidence meets threshold
                if txn.tag_confidence >= self.review_threshold:
                    txn.needs_review = False
                    self.stats['high_confidence'] += 1
                else:
                    txn.needs_review = True
                    self.stats['needs_review'] += 1
                
                self.stats['llm_suggest'] += 1
                return txn
        
        # Step 3: No match, no LLM, or LLM failed -> needs review
        txn.category = 'Uncategorized'
        txn.subcategory = 'Needs Review'
        txn.tag_source = 'none'
        txn.tag_confidence = 0.0
        txn.needs_review = True
        txn.notes = 'No matching rule or LLM suggestion'
        
        self.stats['needs_review'] += 1
        return txn
    
    def categorize_batch(self, transactions: List[Transaction]) -> List[Transaction]:
        """
        Categorize multiple transactions
        
        More efficient than calling categorize_transaction repeatedly
        because it can batch LLM calls.
        
        Args:
            transactions: List of Transaction objects
            
        Returns:
            List of categorized transactions
        """
        # First pass: try rule matching for all
        uncategorized = []
        categorized = []
        
        for txn in transactions:
            result = self.rule_matcher.categorize(
                txn.merchant_norm,
                txn.merchant_detail,
                txn.description_raw
            )
            
            if result.category != 'Uncategorized':
                # Rule matched
                txn.category = result.category
                txn.subcategory = result.subcategory
                txn.tag_source = 'rule'
                txn.tag_confidence = 1.0
                txn.needs_review = False
                txn.notes = result.rationale
                
                categorized.append(txn)
                self.stats['rule_match'] += 1
                self.stats['high_confidence'] += 1
            else:
                # No rule match
                uncategorized.append(txn)
        
        # Second pass: LLM for uncategorized (if enabled)
        if uncategorized and self.enable_llm and self.llm_categorizer:
            # Batch LLM call
            llm_results = self.llm_categorizer.categorize_batch([
                {
                    'merchant_norm': t.merchant_norm,
                    'merchant_detail': t.merchant_detail,
                    'description_raw': t.description_raw,
                    'amount': t.amount,
                    'direction': t.direction,
                }
                for t in uncategorized
            ])
            
            for txn, llm_result in zip(uncategorized, llm_results):
                if llm_result:
                    txn.category = llm_result['category']
                    txn.subcategory = llm_result['subcategory']
                    txn.tag_source = 'llm'
                    txn.tag_confidence = llm_result['confidence']
                    txn.notes = llm_result.get('rationale', 'LLM suggestion')
                    
                    if txn.tag_confidence >= self.review_threshold:
                        txn.needs_review = False
                        self.stats['high_confidence'] += 1
                    else:
                        txn.needs_review = True
                        self.stats['needs_review'] += 1
                    
                    self.stats['llm_suggest'] += 1
                else:
                    # LLM failed
                    txn.category = 'Uncategorized'
                    txn.subcategory = 'Needs Review'
                    txn.tag_source = 'none'
                    txn.tag_confidence = 0.0
                    txn.needs_review = True
                    txn.notes = 'No matching rule or LLM suggestion'
                    self.stats['needs_review'] += 1
                
                categorized.append(txn)
        else:
            # No LLM, mark all as needs review
            for txn in uncategorized:
                txn.category = 'Uncategorized'
                txn.subcategory = 'Needs Review'
                txn.tag_source = 'none'
                txn.tag_confidence = 0.0
                txn.needs_review = True
                txn.notes = 'No matching rule'
                self.stats['needs_review'] += 1
                categorized.append(txn)
        
        self.stats['total'] += len(transactions)
        return categorized
    
    def print_stats(self):
        """Print categorization statistics"""
        if self.stats['total'] == 0:
            print("No transactions categorized yet")
            return
        
        total = self.stats['total']
        
        print("\n" + "=" * 80)
        print("📊 CATEGORIZATION STATISTICS")
        print("=" * 80)
        print(f"Total transactions: {total}")
        print(f"\n✅ Categorization Results:")
        print(f"  • Rule match: {self.stats['rule_match']} ({self.stats['rule_match']/total*100:.1f}%)")
        
        if self.enable_llm:
            print(f"  • LLM suggestion: {self.stats['llm_suggest']} ({self.stats['llm_suggest']/total*100:.1f}%)")
        
        print(f"\n📋 Review Status:")
        print(f"  • High confidence (≥{self.review_threshold*100:.0f}%): {self.stats['high_confidence']} ({self.stats['high_confidence']/total*100:.1f}%)")
        print(f"  • Needs review: {self.stats['needs_review']} ({self.stats['needs_review']/total*100:.1f}%)")
        
        print("=" * 80)


def load_rules_from_db(conn) -> List[Dict]:
    """Load merchant rules from database"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT rule_id, rule_pack, priority, match_type, match_value, 
               match_detail, category, subcategory, is_active, created_by, notes
        FROM merchant_rules
        WHERE is_active = TRUE
        ORDER BY priority, rule_id
    """)
    
    rules = []
    for row in cursor.fetchall():
        rules.append({
            'rule_id': row[0],
            'rule_pack': row[1],
            'priority': row[2],
            'match_type': row[3],
            'match_value': row[4],
            'match_detail': row[5],
            'category': row[6],
            'subcategory': row[7],
            'is_active': row[8],
            'created_by': row[9],
            'notes': row[10],
        })
    
    cursor.close()
    return rules


def test_orchestrator():
    """Test the categorization orchestrator"""
    print("Testing Categorization Orchestrator")
    print("=" * 80)
    
    # Load taxonomy
    taxonomy_file = Path(__file__).parent.parent / "data" / "taxonomy.json"
    with open(taxonomy_file) as f:
        taxonomy = json.load(f)
    
    # Create some test rules
    test_rules = [
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
            'created_by': 'test',
            'notes': 'Test rule',
        },
        {
            'rule_id': 2,
            'rule_pack': 'test',
            'priority': 50,
            'match_type': 'exact',
            'match_value': 'SQ',
            'match_detail': 'BREADS BAKERY',
            'category': 'Food & Drink',
            'subcategory': 'Coffee',
            'is_active': True,
            'created_by': 'test',
            'notes': 'Test composite rule',
        },
    ]
    
    # Create orchestrator
    orchestrator = CategorizationOrchestrator(
        taxonomy=taxonomy,
        rules=test_rules,
        review_threshold=0.90,
        enable_llm=True  # Will be disabled if no API key
    )
    
    # Test transactions
    test_txns = [
        Transaction(
            txn_id=None,
            merchant_norm='AMAZON',
            merchant_detail=None,
            description_raw='AMAZON.COM*123ABC',
            amount=-25.00,
            direction='debit',
            txn_date='2025-01-15',
            post_date='2025-01-16',
            account_id=1,
            source='test',
            type='Sale',
            is_return=False,
        ),
        Transaction(
            txn_id=None,
            merchant_norm='SQ',
            merchant_detail='BREADS BAKERY',
            description_raw='SQ *BREADS BAKERY',
            amount=-8.50,
            direction='debit',
            txn_date='2025-01-15',
            post_date='2025-01-16',
            account_id=1,
            source='test',
            type='Sale',
            is_return=False,
        ),
        Transaction(
            txn_id=None,
            merchant_norm='UNKNOWN MERCHANT',
            merchant_detail=None,
            description_raw='UNKNOWN MERCHANT NYC',
            amount=-15.00,
            direction='debit',
            txn_date='2025-01-15',
            post_date='2025-01-16',
            account_id=1,
            source='test',
            type='Sale',
            is_return=False,
        ),
    ]
    
    print("\nCategorizing test transactions...")
    results = orchestrator.categorize_batch(test_txns)
    
    print("\nResults:")
    for txn in results:
        status = "✅" if not txn.needs_review else "⚠️ "
        print(f"{status} {txn.merchant_norm:<30} → {txn.category} / {txn.subcategory}")
        print(f"     Source: {txn.tag_source}, Confidence: {txn.tag_confidence:.0%}")
        if txn.notes:
            print(f"     Note: {txn.notes}")
    
    orchestrator.print_stats()


if __name__ == "__main__":
    test_orchestrator()
