"""
Merchant Normalization Module

Converts raw bank descriptions into clean, normalized merchant names
for consistent rule matching and analytics.
"""
import re
from typing import Tuple, Optional

# Common noise patterns to strip
NOISE_PATTERNS = [
    r'\s+\d{10,}',  # Long numeric IDs
    r'\s+WEB ID:\s*\d+',  # Web IDs
    r'\s+PPD ID:\s*\d+',  # ACH PPD IDs
    r'\s+#\d+',  # Trailing numbers like "#123"
    r'\*+',  # Asterisks
    r'&gt;|&lt;|&amp;',  # HTML entities
    r'\s+[A-Z]{2}\s+\d{2}/\d{2}',  # State codes with dates
    r'https?://\S+',  # URLs
]

# Patterns for common internal transactions
INTERNAL_PATTERNS = {
    r'^CHASE.*AUTOPAY': 'CHASE CREDIT CARD PAYMENT',
    r'^CHASE.*PAYMENT': 'CHASE CREDIT CARD PAYMENT',
    r'^VENMO\s+PAYMENT': 'VENMO OUTGOING',
    r'^VENMO\s+CASHOUT': 'VENMO CASHOUT',
    r'^ZELLE PAYMENT TO\s+(.+)': 'ZELLE TO',  # Special: extract payee
    r'^ZELLE PAYMENT FROM\s+(.+)': 'ZELLE FROM',  # Special: extract payer
    r'^INTEREST PAYMENT': 'BANK INTEREST',
    r'^ATM WITHDRAWAL': 'ATM WITHDRAWAL',
    r'^WIRE TRANSFER': 'WIRE TRANSFER',
    r'^ACH TRANSFER': 'ACH TRANSFER',
    r'^ONLINE TRANSFER': 'ONLINE TRANSFER',
    r'^CHECK\s+\d+': 'CHECK PAYMENT',
    r'^DEPOSIT': 'DEPOSIT',
    r'^REMOTE.*DEPOSIT': 'REMOTE DEPOSIT',
}

# Known merchant aliases (normalize to canonical name)
MERCHANT_ALIASES = {
    # Amazon
    r'AMZN.*MKTP': 'AMAZON',
    r'AMAZON.*MKTP': 'AMAZON',
    r'AMAZON\.COM': 'AMAZON',
    
    # Costco
    r'COSTCO\s+WHSE': 'COSTCO',
    r'COSTCO\s+GAS': 'COSTCO GAS',
    
    # Grocery stores
    r'STOP\s*&?\s*SHOP': 'STOP & SHOP',
    r'TRADER\s+JOE': 'TRADER JOES',
    r'KEY\s+FOOD': 'KEY FOOD',
    
    # Restaurants & delivery
    r'DOORDASH': 'DOORDASH',
    r'DD\s*\*': 'DOORDASH',
    r'GRUBHUB': 'GRUBHUB',
    r'UBER\s+EATS': 'UBER EATS',
    r'UBER.*TRIP': 'UBER',
    r'LYFT': 'LYFT',
    
    # Pharmacies
    r'CVS.*PHARMACY': 'CVS',
    r'WALGREENS': 'WALGREENS',
    
    # Gas stations
    r'EXXON': 'EXXON',
    r'SHELL': 'SHELL',
    r'BP\s+': 'BP',
    
    # Transit
    r'MTA\s*\*?\s*NYCT': 'MTA SUBWAY',
    r'MTA\s*\*?\s*LIRR': 'MTA LIRR',
}

def normalize_merchant(raw_description: str) -> Tuple[str, Optional[str]]:
    """
    Normalize a raw bank description into a clean merchant name.
    
    Args:
        raw_description: Raw description from bank CSV
        
    Returns:
        Tuple of (merchant_norm, merchant_detail)
        - merchant_norm: Normalized merchant name for rule matching
        - merchant_detail: Additional detail (e.g., specific SQ merchant, Zelle payee)
    """
    if not raw_description:
        return "UNKNOWN", None
    
    # Start with uppercase and strip
    text = raw_description.upper().strip()
    merchant_detail = None
    
    # Step 1: Check for POS systems FIRST (before noise removal strips asterisks)
    pos_patterns = {
        r'SQ\s*\*\s*(.+)': 'SQ',
        r'TST\s*\*\s*(.+)': 'TST', 
        r'SP\s+(.+)': 'SP',
    }
    for pattern, replacement in pos_patterns.items():
        match = re.search(pattern, text)
        if match and match.groups():
            merchant_detail = match.group(1).strip()
            # Clean up the merchant detail (remove trailing numbers/noise)
            merchant_detail = re.sub(r'\s+\d{10,}$', '', merchant_detail).strip()
            merchant_detail = re.sub(r'\s+', ' ', merchant_detail).strip()
            return replacement, merchant_detail
    
    # Step 2: Check for internal transaction patterns
    for pattern, replacement in INTERNAL_PATTERNS.items():
        match = re.match(pattern, text)
        if match:
            # Special handling for Zelle (extract payee/payer)
            if 'ZELLE' in replacement:
                if match.groups():
                    payee = match.group(1).strip()
                    # Remove trailing numeric IDs
                    payee = re.sub(r'\s+\d{10,}$', '', payee).strip()
                    return replacement, payee
            return replacement, None
    
    # Step 3: Strip noise patterns
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, '', text)
    
    # Step 4: Apply merchant aliases
    for pattern, replacement in MERCHANT_ALIASES.items():
        match = re.search(pattern, text)
        if match:
            # Special handling for POS systems (extract merchant name)
            if replacement in ['SQ', 'TST', 'SP'] and match.groups():
                merchant_detail = match.group(1).strip()
                # Clean up the merchant detail
                merchant_detail = re.sub(r'\s+', ' ', merchant_detail).strip()
            return replacement, merchant_detail
    
    # Step 5: General cleanup
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing location codes (e.g., "STORE #123" -> "STORE")
    text = re.sub(r'\s+#\s*\d+$', '', text)
    
    # Remove common suffixes
    suffixes = [' INC', ' LLC', ' LTD', ' CO', ' CORP']
    for suffix in suffixes:
        if text.endswith(suffix):
            text = text[:-len(suffix)].strip()
    
    # Step 6: Validate result
    if not text or len(text) < 2:
        return "UNKNOWN", None
    
    return text, merchant_detail

def extract_merchant_from_credit(description: str) -> Tuple[str, Optional[str]]:
    """
    Extract merchant from credit card description.
    Credit card descriptions are usually cleaner than checking.
    """
    return normalize_merchant(description)

def extract_merchant_from_checking(description: str) -> Tuple[str, Optional[str]]:
    """
    Extract merchant from checking account description.
    Checking descriptions often have more metadata.
    """
    return normalize_merchant(description)

def test_normalization():
    """Test cases for merchant normalization"""
    test_cases = [
        # Amazon
        ("AMZN Mktp US*UE1F70L13", "AMAZON", None),
        ("Amazon.com*4309A8OT3", "AMAZON", None),
        ("AMAZON MKTPL*BI3HN3KZ2", "AMAZON", None),
        
        # Zelle
        ("Zelle payment to Devi Daycare  27420707612", "ZELLE TO", "DEVI DAYCARE"),
        ("Zelle payment from ROBERT DIENSTAG 27420737226", "ZELLE FROM", "ROBERT DIENSTAG"),
        
        # Venmo
        ("VENMO            PAYMENT    1047273886351   WEB ID: 3264681992", "VENMO OUTGOING", None),
        ("VENMO            CASHOUT                    PPD ID: 5264681992", "VENMO CASHOUT", None),
        
        # Square merchants
        ("SQ *BREADS BAKERY", "SQ", "BREADS BAKERY"),
        ("TST* Long Island Bagel Ca", "TST", "LONG ISLAND BAGEL CA"),
        
        # Groceries
        ("STOP & SHOP 2582", "STOP & SHOP", None),
        ("TRADER JOE'S #552 QPS", "TRADER JOES", None),
        ("COSTCO WHSE #1215", "COSTCO", None),
        ("COSTCO GAS #1215", "COSTCO GAS", None),
        
        # Transit
        ("MTA*LIRR ETIX TICKET", "MTA LIRR", None),
        ("MTA*NYCT PAYGO", "MTA SUBWAY", None),
        
        # Uber/Lyft
        ("UBER   TRIP", "UBER", None),
        ("LYFT   *RIDE TUE 10PM", "LYFT", None),
        
        # Internal
        ("CHASE CREDIT CRD AUTOPAY                    PPD ID: 4760039224", "CHASE CREDIT CARD PAYMENT", None),
        ("INTEREST PAYMENT", "BANK INTEREST", None),
    ]
    
    print("Testing merchant normalization...")
    print("=" * 80)
    
    passed = 0
    failed = 0
    
    for raw, expected_merchant, expected_detail in test_cases:
        merchant, detail = normalize_merchant(raw)
        
        if merchant == expected_merchant and detail == expected_detail:
            passed += 1
            status = "✅"
        else:
            failed += 1
            status = "❌"
        
        print(f"{status} {raw[:50]:<50} -> {merchant:<25} | {detail}")
        if merchant != expected_merchant or detail != expected_detail:
            print(f"   Expected: {expected_merchant:<25} | {expected_detail}")
    
    print("=" * 80)
    print(f"Passed: {passed}/{len(test_cases)}, Failed: {failed}/{len(test_cases)}")

if __name__ == "__main__":
    test_normalization()
