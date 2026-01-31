"""
CSV Parser for Chase Bank Exports

Handles both checking and credit card CSV formats from Chase.
"""
import csv
import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from pathlib import Path

from .merchant_normalizer import normalize_merchant

class TransactionParser:
    """Base class for parsing Chase CSV exports"""
    
    def __init__(self):
        self.transactions = []
    
    def compute_row_hash(self, row_dict: Dict[str, str], row_index: int = 0) -> str:
        """
        Compute SHA256 hash of row for deduplication.
        Uses transaction date, description, amount, AND row index.
        """
        # Create a deterministic string from key fields + row position
        hash_input = f"{row_dict.get('txn_date', '')}|{row_dict.get('description_raw', '')}|{row_dict.get('amount', '')}|{row_index}"
        return hashlib.sha256(hash_input.encode()).hexdigest()
    
    def parse_date(self, date_str: str) -> Optional[str]:
        """Parse date string to YYYY-MM-DD format"""
        if not date_str:
            return None
        
        from datetime import datetime
        
        # Try multiple date formats
        formats = [
            '%m/%d/%Y',      # 01/30/2025
            '%m/%d/%y',      # 1/30/23
            '%-m/%-d/%Y',    # 1/30/2025 (no leading zeros)
            '%-m/%-d/%y',    # 1/30/23
            '%Y-%m-%d',      # 2025-01-30
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # If 2-digit year, assume 2000s
                if dt.year < 100:
                    dt = dt.replace(year=dt.year + 2000)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        raise ValueError(f"Could not parse date: {date_str}")
    
    def parse_amount(self, amount_str: str) -> Decimal:
        """Parse amount string to Decimal"""
        if not amount_str:
            return Decimal('0.00')
        
        # Remove dollar signs, commas
        cleaned = amount_str.replace('$', '').replace(',', '').strip()
        return Decimal(cleaned)


class CheckingParser(TransactionParser):
    """Parser for Chase Checking CSV format"""
    
    # Expected columns: Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
    
    def parse(self, csv_path: Path, account_id: int = 1) -> List[Dict]:
        """
        Parse Chase checking CSV
        
        Args:
            csv_path: Path to CSV file
            account_id: Database account ID
            
        Returns:
            List of transaction dicts ready for database insertion
        """
        transactions = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for i, row in enumerate(reader):
                # Parse basic fields
                description_raw = row['Description'].strip()
                amount = self.parse_amount(row['Amount'])
                post_date = self.parse_date(row['Posting Date'])
                txn_date = post_date  # Checking doesn't have separate transaction date
                
                # Determine direction
                direction = 'credit' if amount > 0 else 'debit'
                amount = abs(amount)
                
                # Normalize merchant
                merchant_norm, merchant_detail = normalize_merchant(description_raw)
                
                # Determine if this is a return
                is_return = row['Details'].strip().upper() == 'RETURN'
                
                # Build transaction dict
                txn = {
                    'account_id': account_id,
                    'source': 'chase_checking',
                    'txn_date': txn_date,
                    'post_date': post_date,
                    'description_raw': description_raw,
                    'merchant_raw': description_raw,  # Same as description for checking
                    'merchant_norm': merchant_norm,
                    'merchant_detail': merchant_detail,
                    'amount': amount,
                    'currency': 'USD',
                    'direction': direction,
                    'type': row['Type'].strip(),
                    'is_return': is_return,
                    'memo': None,
                    'created_by': 'import',
                }
                
                # Compute hash for deduplication
                txn['source_row_hash'] = self.compute_row_hash(txn, row_index=i)
                
                transactions.append(txn)
        
        print(f"✅ Parsed {len(transactions)} transactions from checking CSV")
        return transactions


class CreditParser(TransactionParser):
    """Parser for Chase Credit Card CSV format"""
    
    # Expected columns: Transaction Date,Post Date,Description,Category,Type,Amount,Memo
    
    def parse(self, csv_path: Path, account_id: int = 2) -> List[Dict]:
        """
        Parse Chase credit card CSV
        
        Args:
            csv_path: Path to CSV file
            account_id: Database account ID
            
        Returns:
            List of transaction dicts ready for database insertion
        """
        transactions = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for i, row in enumerate(reader):
                # Parse basic fields
                description_raw = row['Description'].strip()
                amount = self.parse_amount(row['Amount'])
                txn_date = self.parse_date(row['Transaction Date'])
                post_date = self.parse_date(row['Post Date'])
                
                # Determine direction (negative = debit for credit cards)
                direction = 'credit' if amount > 0 else 'debit'
                amount = abs(amount)
                
                # Normalize merchant
                merchant_norm, merchant_detail = normalize_merchant(description_raw)
                
                # Determine if this is a return
                is_return = row['Type'].strip().upper() == 'RETURN'
                
                # Build transaction dict
                txn = {
                    'account_id': account_id,
                    'source': 'chase_credit',
                    'txn_date': txn_date,
                    'post_date': post_date,
                    'description_raw': description_raw,
                    'merchant_raw': description_raw,
                    'merchant_norm': merchant_norm,
                    'merchant_detail': merchant_detail,
                    'amount': amount,
                    'currency': 'USD',
                    'direction': direction,
                    'type': row['Type'].strip(),
                    'is_return': is_return,
                    'memo': row['Memo'].strip() if row['Memo'] else None,
                    'created_by': 'import',
                }
                
                # Compute hash for deduplication
                txn['source_row_hash'] = self.compute_row_hash(txn, row_index=i)
                
                transactions.append(txn)
        
        print(f"✅ Parsed {len(transactions)} transactions from credit CSV")
        return transactions


def parse_chase_csv(csv_path: Path, csv_type: str = 'auto', account_id: Optional[int] = None) -> List[Dict]:
    """
    Parse a Chase CSV file (auto-detects type or uses specified type)
    
    Args:
        csv_path: Path to CSV file
        csv_type: 'checking', 'credit', or 'auto' (default)
        account_id: Optional account ID (defaults: 1 for checking, 2 for credit)
        
    Returns:
        List of parsed transaction dicts
    """
    csv_path = Path(csv_path)
    
    # Auto-detect CSV type if not specified
    if csv_type == 'auto':
        with open(csv_path, 'r', encoding='utf-8') as f:
            header = f.readline().strip()
            if 'Transaction Date,Post Date,Description,Category,Type,Amount,Memo' in header:
                csv_type = 'credit'
            elif 'Details,Posting Date,Description,Amount,Type,Balance' in header:
                csv_type = 'checking'
            else:
                raise ValueError(f"Unknown CSV format. Header: {header}")
    
    # Set default account_id if not provided
    if account_id is None:
        account_id = 1 if csv_type == 'checking' else 2
    
    # Parse based on type
    if csv_type == 'checking':
        parser = CheckingParser()
        return parser.parse(csv_path, account_id)
    elif csv_type == 'credit':
        parser = CreditParser()
        return parser.parse(csv_path, account_id)
    else:
        raise ValueError(f"Unknown CSV type: {csv_type}")


def test_parsers():
    """Test the parsers with sample files"""
    import sys
    
    # Check if test files exist
    test_dir = Path(__file__).parent.parent / "mnt" / "user-data" / "uploads"
    
    checking_file = test_dir / "checking_1225.CSV"
    credit_file = test_dir / "credit_1225.CSV"
    
    if not checking_file.exists():
        checking_file = Path("/mnt/user-data/uploads/checking_1225.CSV")
    
    if not credit_file.exists():
        credit_file = Path("/mnt/user-data/uploads/credit_1225.CSV")
    
    print("Testing Chase CSV Parsers")
    print("=" * 80)
    
    # Test checking parser
    if checking_file.exists():
        print(f"\n📁 Parsing checking CSV: {checking_file}")
        checking_txns = parse_chase_csv(checking_file, 'auto')
        print(f"   First transaction: {checking_txns[0]['description_raw'][:50]}")
        print(f"   Merchant norm: {checking_txns[0]['merchant_norm']}")
        if checking_txns[0]['merchant_detail']:
            print(f"   Merchant detail: {checking_txns[0]['merchant_detail']}")
    else:
        print(f"\n⚠️  Checking CSV not found: {checking_file}")
    
    # Test credit parser
    if credit_file.exists():
        print(f"\n📁 Parsing credit CSV: {credit_file}")
        credit_txns = parse_chase_csv(credit_file, 'auto')
        print(f"   First transaction: {credit_txns[0]['description_raw'][:50]}")
        print(f"   Merchant norm: {credit_txns[0]['merchant_norm']}")
        if credit_txns[0]['merchant_detail']:
            print(f"   Merchant detail: {credit_txns[0]['merchant_detail']}")
    else:
        print(f"\n⚠️  Credit CSV not found: {credit_file}")
    
    print("\n" + "=" * 80)
    print("✅ Parser tests complete")


if __name__ == "__main__":
    test_parsers()
