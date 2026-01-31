"""
LLM Categorizer (Improved)

Uses Claude API to suggest categories for unknown merchants.
Features:
- Batch processing in chunks (prevents context overflow)
- Automatic retry on failures
- Better JSON parsing with fallback
- Progress indicators for large batches
"""
import os
import json
import time
import anthropic
from typing import Dict, Optional, List


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
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1])
            
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
            print(f"⚠️  LLM response not valid JSON: {e}")
            return None
        except Exception as e:
            print(f"⚠️  LLM categorization failed: {e}")
            return None
    
    def _categorize_chunk(self, transactions: list, chunk_num: int = 0, retry: int = 0) -> list:
        """
        Categorize a chunk of transactions
        
        Args:
            transactions: List of transaction dicts (max 50)
            chunk_num: Chunk number for logging
            retry: Retry attempt number
            
        Returns:
            List of categorization results
        """
        if not self.enabled or not transactions:
            return [None] * len(transactions)
        
        # Build batch prompt
        txn_list = []
        for i, txn in enumerate(transactions):
            merchant = txn['merchant_norm']
            if txn.get('merchant_detail'):
                merchant += f" ({txn['merchant_detail']})"
            
            txn_str = f"{i+1}. {merchant} - ${abs(txn['amount']):.2f}"
            txn_list.append(txn_str)
        
        prompt = f"""Categorize these {len(transactions)} transactions. Respond with ONLY a JSON array:

TAXONOMY:
{self.taxonomy_str}

TRANSACTIONS:
{chr(10).join(txn_list)}

Response format (JSON array only, no markdown, no preamble):
[
  {{"txn": 1, "category": "...", "subcategory": "...", "confidence": 0.85, "rationale": "..."}},
  {{"txn": 2, "category": "...", "subcategory": "...", "confidence": 0.90, "rationale": "..."}}
]

Rules:
- Choose ONLY from taxonomy above
- Include ALL {len(transactions)} transactions
- confidence 0.0-1.0
- rationale max 15 words
- CRITICAL: Return ONLY the JSON array, nothing else"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,  # Larger for batch responses
                temperature=0.0,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            response_text = message.content[0].text.strip()
            
            # Remove markdown code blocks
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                # Find first [ and last ]
                for i, line in enumerate(lines):
                    if '[' in line:
                        response_text = '\n'.join(lines[i:])
                        break
                for i in range(len(lines) - 1, -1, -1):
                    if ']' in lines[i]:
                        response_text = '\n'.join(response_text.split('\n')[:i+1])
                        break
            
            # Extract JSON array (handle cases where there's text before/after)
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']')
            
            if start_idx == -1 or end_idx == -1:
                raise json.JSONDecodeError("No JSON array found", response_text, 0)
            
            json_text = response_text[start_idx:end_idx + 1]
            results = json.loads(json_text)
            
            if not isinstance(results, list):
                raise ValueError(f"Expected list, got {type(results)}")
            
            # Sort by txn number and validate
            results.sort(key=lambda x: x.get('txn', 999))
            
            # Ensure we have results for all transactions
            if len(results) != len(transactions):
                print(f"⚠️  Warning: Expected {len(transactions)} results, got {len(results)}")
                # Pad with None
                while len(results) < len(transactions):
                    results.append(None)
            
            return results
            
        except json.JSONDecodeError as e:
            print(f"⚠️  Chunk {chunk_num} JSON parse error: {e}")
            
            # Retry once with smaller batch
            if retry == 0 and len(transactions) > 10:
                print(f"   🔄 Retrying chunk {chunk_num} with smaller sub-batches...")
                mid = len(transactions) // 2
                first_half = self._categorize_chunk(transactions[:mid], chunk_num, retry=1)
                second_half = self._categorize_chunk(transactions[mid:], chunk_num, retry=1)
                return first_half + second_half
            
            # If retry fails or batch too small, fall back to individual
            if retry == 1:
                print(f"   ⚠️  Falling back to individual categorization for chunk {chunk_num}")
                return [self.categorize(
                    txn['merchant_norm'],
                    txn.get('merchant_detail'),
                    txn['description_raw'],
                    txn['amount'],
                    txn['direction']
                ) for txn in transactions]
            
            return [None] * len(transactions)
            
        except Exception as e:
            print(f"⚠️  Chunk {chunk_num} failed: {e}")
            
            # Retry once
            if retry == 0:
                print(f"   🔄 Retrying chunk {chunk_num}...")
                time.sleep(1)
                return self._categorize_chunk(transactions, chunk_num, retry=1)
            
            return [None] * len(transactions)
    
    def categorize_batch(self, transactions: list, chunk_size: int = 50) -> list:
        """
        Categorize multiple transactions in batches
        
        Args:
            transactions: List of transaction dicts
            chunk_size: Number of transactions per batch (default 50)
            
        Returns:
            List of categorization results (same order as input)
        """
        if not self.enabled:
            return [None] * len(transactions)
        
        if not transactions:
            return []
        
        # Process in chunks
        results = []
        total_chunks = (len(transactions) + chunk_size - 1) // chunk_size
        
        if total_chunks > 1:
            print(f"   📦 Processing {len(transactions)} transactions in {total_chunks} batches...")
        
        for i in range(0, len(transactions), chunk_size):
            chunk = transactions[i:i + chunk_size]
            chunk_num = i // chunk_size + 1
            
            if total_chunks > 1:
                print(f"   🔄 Batch {chunk_num}/{total_chunks} ({len(chunk)} transactions)...", end='', flush=True)
            
            chunk_results = self._categorize_chunk(chunk, chunk_num)
            results.extend(chunk_results)
            
            if total_chunks > 1:
                success_count = sum(1 for r in chunk_results if r is not None)
                print(f" ✅ {success_count}/{len(chunk)} categorized")
            
            # Rate limiting: small delay between chunks
            if i + chunk_size < len(transactions):
                time.sleep(0.5)
        
        return results


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
    
    # Test single
    print("\n1. Single transaction test:")
    test_txn = {
        'merchant_norm': 'UNKNOWN COFFEE SHOP',
        'merchant_detail': None,
        'description_raw': 'UNKNOWN COFFEE SHOP BROOKLYN NY',
        'amount': -5.50,
        'direction': 'debit',
    }
    
    result = categorizer.categorize(**test_txn)
    if result:
        print(f"  → {result['category']} / {result['subcategory']}")
        print(f"     Confidence: {result['confidence']:.0%}")
        print(f"     Rationale: {result['rationale']}")
    
    # Test batch
    print("\n2. Batch test (5 transactions):")
    test_batch = [
        {'merchant_norm': 'STARBUCKS', 'merchant_detail': None, 'description_raw': 'STARBUCKS', 'amount': -5.50, 'direction': 'debit'},
        {'merchant_norm': 'UBER', 'merchant_detail': None, 'description_raw': 'UBER TRIP', 'amount': -15.00, 'direction': 'debit'},
        {'merchant_norm': 'AMAZON', 'merchant_detail': None, 'description_raw': 'AMAZON.COM', 'amount': -50.00, 'direction': 'debit'},
        {'merchant_norm': 'TRADER JOES', 'merchant_detail': None, 'description_raw': 'TRADER JOES', 'amount': -75.00, 'direction': 'debit'},
        {'merchant_norm': 'SHELL', 'merchant_detail': None, 'description_raw': 'SHELL GAS', 'amount': -40.00, 'direction': 'debit'},
    ]
    
    results = categorizer.categorize_batch(test_batch)
    for txn, result in zip(test_batch, results):
        if result:
            print(f"  {txn['merchant_norm']:<20} → {result['category']} / {result['subcategory']}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_llm_categorizer()
