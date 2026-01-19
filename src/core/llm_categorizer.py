"""
LLM Categorizer

Uses Claude API to suggest categories for unknown merchants.
Only used as fallback when no rule matches.
"""
import os
import json
import anthropic
from typing import Dict, Optional


class LLMCategorizer:
    """
    Categorizes transactions using Claude API
    """
    
    def __init__(self, taxonomy: Dict, api_key: Optional[str] = None):
        """
        Args:
            taxonomy: Taxonomy dict with categories and subcategories
            api_key: Anthropic API key (or read from ANTHROPIC_API_KEY env var)
        """
        self.taxonomy = taxonomy
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        
        if not self.api_key:
            print("⚠️  Warning: No ANTHROPIC_API_KEY found. LLM categorization disabled.")
            self.enabled = False
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)
            self.enabled = True
        
        # Build taxonomy string for prompt
        self.taxonomy_str = self._build_taxonomy_string()
    
    def _build_taxonomy_string(self) -> str:
        """Build a concise taxonomy string for the prompt"""
        lines = []
        for cat in self.taxonomy['categories']:
            subcats = ', '.join(cat['subcategories'])
            lines.append(f"- {cat['name']}: {subcats}")
        return '\n'.join(lines)
    
    def categorize(self,
                   merchant_norm: str,
                   merchant_detail: Optional[str],
                   description_raw: str,
                   amount: float,
                   direction: str) -> Optional[Dict]:
        """
        Suggest category using LLM
        
        Args:
            merchant_norm: Normalized merchant name
            merchant_detail: Additional merchant detail (if any)
            description_raw: Original transaction description
            amount: Transaction amount
            direction: 'debit' or 'credit'
            
        Returns:
            Dict with category, subcategory, confidence, rationale
            or None if LLM is disabled or fails
        """
        if not self.enabled:
            return None
        
        # Build transaction description for LLM
        txn_desc = f"Merchant: {merchant_norm}"
        if merchant_detail:
            txn_desc += f" ({merchant_detail})"
        txn_desc += f"\nDescription: {description_raw}"
        txn_desc += f"\nAmount: ${abs(amount):.2f}"
        txn_desc += f"\nType: {'Expense' if direction == 'debit' else 'Income/Credit'}"
        
        # Build prompt
        prompt = f"""You are a transaction categorization assistant. Given a transaction, suggest the most appropriate category and subcategory.

TAXONOMY:
{self.taxonomy_str}

TRANSACTION:
{txn_desc}

Respond with ONLY a JSON object (no markdown, no explanations):
{{
  "category": "Category Name",
  "subcategory": "Subcategory Name",
  "confidence": 0.85,
  "rationale": "Brief 1-sentence explanation"
}}

Rules:
- Choose ONLY from the taxonomy above
- confidence must be between 0.0 and 1.0
- If uncertain, use lower confidence
- rationale should be max 15 words"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                temperature=0.0,  # Deterministic
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            # Parse response
            response_text = message.content[0].text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('\n', 1)[1]
                response_text = response_text.rsplit('\n', 1)[0]
            
            result = json.loads(response_text)
            
            # Validate fields
            required = ['category', 'subcategory', 'confidence', 'rationale']
            if not all(k in result for k in required):
                print(f"⚠️  LLM response missing required fields: {result}")
                return None
            
            # Validate confidence
            result['confidence'] = max(0.0, min(1.0, float(result['confidence'])))
            
            # Validate category exists in taxonomy
            cat_exists = any(c['name'] == result['category'] for c in self.taxonomy['categories'])
            if not cat_exists:
                print(f"⚠️  LLM suggested invalid category: {result['category']}")
                return None
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"⚠️  LLM response not valid JSON: {response_text}")
            return None
        except Exception as e:
            print(f"⚠️  LLM categorization failed: {e}")
            return None
    
    def categorize_batch(self, transactions: list) -> list:
        """
        Categorize multiple transactions in one API call
        
        Args:
            transactions: List of transaction dicts
            
        Returns:
            List of categorization results (same order as input)
        """
        if not self.enabled:
            return [None] * len(transactions)
        
        # Build batch prompt
        txn_list = []
        for i, txn in enumerate(transactions):
            merchant = txn['merchant_norm']
            if txn.get('merchant_detail'):
                merchant += f" ({txn['merchant_detail']})"
            
            txn_str = f"{i+1}. {merchant} - ${abs(txn['amount']):.2f}"
            txn_list.append(txn_str)
        
        prompt = f"""Categorize these transactions. Respond with ONLY a JSON array:

TAXONOMY:
{self.taxonomy_str}

TRANSACTIONS:
{chr(10).join(txn_list)}

Response format (JSON array only, no markdown):
[
  {{"txn": 1, "category": "...", "subcategory": "...", "confidence": 0.85, "rationale": "..."}},
  {{"txn": 2, "category": "...", "subcategory": "...", "confidence": 0.90, "rationale": "..."}}
]

Rules:
- Choose ONLY from taxonomy above
- Include ALL transactions
- confidence 0.0-1.0
- rationale max 15 words"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                temperature=0.0,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            response_text = message.content[0].text.strip()
            
            # Remove markdown
            if response_text.startswith('```'):
                response_text = response_text.split('\n', 1)[1]
                response_text = response_text.rsplit('\n', 1)[0]
            
            results = json.loads(response_text)
            
            # Sort by txn number and return
            results.sort(key=lambda x: x.get('txn', 999))
            return results
            
        except Exception as e:
            print(f"⚠️  Batch LLM categorization failed: {e}")
            return [None] * len(transactions)


def test_llm_categorizer():
    """Test the LLM categorizer"""
    # Load taxonomy
    import json
    from pathlib import Path
    
    taxonomy_file = Path(__file__).parent.parent / "data" / "taxonomy.json"
    with open(taxonomy_file) as f:
        taxonomy = json.load(f)
    
    # Create categorizer
    categorizer = LLMCategorizer(taxonomy)
    
    if not categorizer.enabled:
        print("❌ LLM categorization not enabled (no API key)")
        return
    
    print("Testing LLM Categorizer")
    print("=" * 80)
    
    # Test cases
    test_cases = [
        {
            'merchant_norm': 'UNKNOWN COFFEE SHOP',
            'merchant_detail': None,
            'description_raw': 'UNKNOWN COFFEE SHOP BROOKLYN NY',
            'amount': -5.50,
            'direction': 'debit',
        },
        {
            'merchant_norm': 'SQ',
            'merchant_detail': 'JOES PIZZA',
            'description_raw': 'SQ *JOES PIZZA',
            'amount': -18.00,
            'direction': 'debit',
        },
    ]
    
    for txn in test_cases:
        print(f"\nTransaction: {txn['merchant_norm']}", end='')
        if txn['merchant_detail']:
            print(f" ({txn['merchant_detail']})", end='')
        print(f" - ${abs(txn['amount']):.2f}")
        
        result = categorizer.categorize(**txn)
        
        if result:
            print(f"  → {result['category']} / {result['subcategory']}")
            print(f"     Confidence: {result['confidence']:.0%}")
            print(f"     Rationale: {result['rationale']}")
        else:
            print("  → No suggestion")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_llm_categorizer()
