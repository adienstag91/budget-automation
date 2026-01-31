"""
Venmo Transaction Enrichment

Matches Venmo CSV data with Chase transactions to add recipient/note details.
Then uses LLM to suggest better categories based on enriched data.
"""
import csv
import re
from datetime import datetime
from typing import Dict, List, Optional
import os

from budget_automation.utils.db_connection import get_db_connection


def parse_venmo_amount(amount_str: str) -> tuple[float, str]:
    """
    Parse Venmo amount string like '- $3,700.00' or '+ $300.00'
    
    Returns:
        (amount, direction) where direction is 'debit' or 'credit'
    """
    # Remove spaces, dollar sign, commas
    cleaned = amount_str.replace(' ', '').replace('$', '').replace(',', '')
    
    # Determine direction
    if cleaned.startswith('-'):
        direction = 'debit'
        cleaned = cleaned[1:].strip()
    elif cleaned.startswith('+'):
        direction = 'credit'
        cleaned = cleaned[1:].strip()
    else:
        # Assume negative is debit
        direction = 'debit' if '-' in cleaned else 'credit'
        cleaned = cleaned.replace('-', '').replace('+', '').strip()
    
    amount = float(cleaned)
    return amount, direction


def parse_venmo_csv(csv_path: str, account_name: Optional[str] = None) -> List[Dict]:
    """
    Parse Venmo statement CSV
    
    Venmo CSVs have an unusual format:
    - Row 1-2: Headers/titles
    - Row 3: Column names (with leading empty column)
    - Row 4: Empty row
    - Row 5+: Actual data
    
    Args:
        csv_path: Path to Venmo CSV file
        account_name: Name to identify this Venmo account (e.g., "Andrew", "Amanda")
    
    Returns list of dicts with:
        - date: transaction date
        - amount: absolute amount
        - direction: 'debit' or 'credit'
        - type: Payment, Standard Transfer, etc.
        - note: transaction note
        - from_name: sender name
        - to_name: recipient name
        - account_name: which Venmo account this is from
    """
    # Try to extract account name from CSV if not provided
    if not account_name:
        # Look for account name in first line like "Account Statement - (@Andrew-Dienstag)"
        with open(csv_path, 'r', encoding='utf-8') as f:
            first_line = f.readline()
            import re
            match = re.search(r'@([^)]+)', first_line)
            if match:
                account_name = match.group(1).split('-')[0]  # Extract first name
    
    transactions = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        # Skip first 2 rows (title rows)
        next(f)
        next(f)
        
        # Read the header row (row 3)
        reader = csv.DictReader(f)
        
        for row in reader:
            # Skip empty rows or rows without datetime
            if not row.get('Datetime') or not row['Datetime'].strip():
                continue
            
            # Skip rows without amounts
            if not row.get('Amount (total)') or not row['Amount (total)'].strip():
                continue
            
            try:
                # Parse datetime to date
                datetime_str = row['Datetime'].strip()
                txn_date = datetime.fromisoformat(datetime_str.replace('Z', '+00:00')).date()
                
                # Parse amount
                amount, direction = parse_venmo_amount(row['Amount (total)'])
                
                # Extract fields
                txn = {
                    'date': txn_date.strftime('%Y-%m-%d'),
                    'amount': amount,
                    'direction': direction,
                    'type': row.get('Type', '').strip(),
                    'note': row.get('Note', '').strip(),
                    'from_name': row.get('From', '').strip(),
                    'to_name': row.get('To', '').strip(),
                    'account_owner': account_name,
                }
                
                transactions.append(txn)
            except Exception as e:
                # Skip malformed rows
                print(f"⚠️  Skipping malformed row: {e}")
                continue
    
    return transactions


def match_venmo_to_chase(venmo_txns: List[Dict], conn) -> List[Dict]:
    """
    Match Venmo transactions to Chase transactions by date, amount, direction
    
    Returns list of matches: {venmo_txn, chase_txn_id, match_confidence}
    """
    matches = []
    
    cursor = conn.cursor()
    
    for venmo_txn in venmo_txns:
        # Skip transfers (these are Venmo → Bank, not actual payments)
        if venmo_txn['type'] == 'Standard Transfer':
            continue
        
        try:
            # Allow ±1 day for date matching (Venmo send date vs Chase post date)
            from datetime import datetime, timedelta
            venmo_date = datetime.strptime(venmo_txn['date'], '%Y-%m-%d')
            date_min = (venmo_date - timedelta(days=1)).strftime('%Y-%m-%d')
            date_max = (venmo_date + timedelta(days=1)).strftime('%Y-%m-%d')
            
            # Find matching Chase transaction within date range
            cursor.execute("""
                SELECT txn_id, description_raw, merchant_norm, amount, direction, notes, txn_date
                FROM transactions
                WHERE txn_date BETWEEN %s AND %s
                  AND ABS(amount - %s) < 0.01
                  AND direction = %s
                  AND (merchant_norm LIKE '%%VENMO%%' OR description_raw LIKE '%%VENMO%%')
                ORDER BY ABS(amount - %s), ABS(txn_date - %s::date)
                LIMIT 1
            """, (date_min, date_max, venmo_txn['amount'], venmo_txn['direction'], 
                  venmo_txn['amount'], venmo_txn['date']))
            
            result = cursor.fetchone()
            
            if result:
                match = {
                    'venmo_txn': venmo_txn,
                    'chase_txn_id': result[0],
                    'chase_description': result[1],
                    'chase_merchant': result[2],
                    'chase_amount': float(result[3]),
                    'chase_direction': result[4],
                    'current_notes': result[5],
                    'chase_date': result[6],
                    'match_confidence': 'high' if str(result[6]) == venmo_txn['date'] else 'medium'
                }
                matches.append(match)
            else:
                # No match found
                print(f"⚠️  No match for Venmo txn: {venmo_txn['date']} ${venmo_txn['amount']:.2f} {venmo_txn['direction']} - {venmo_txn['note'][:40] if venmo_txn['note'] else '(no note)'}")
        
        except Exception as e:
            print(f"❌ Error matching transaction: {venmo_txn}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    cursor.close()
    return matches


def find_subset_sum(payments: List[Dict], target: float, tolerance: float = 0.01) -> Optional[List[Dict]]:
    """
    Find a subset of payments that sums to target amount (within tolerance)
    
    Uses dynamic programming approach to solve the subset sum problem.
    
    Args:
        payments: List of payment dicts with 'amount' field
        target: Target sum to match
        tolerance: Acceptable difference (default $0.01)
    
    Returns:
        List of payments that sum to target, or None if no solution found
    """
    if not payments:
        return None
    
    # Convert to cents to avoid floating point issues
    target_cents = int(round(target * 100))
    tolerance_cents = int(round(tolerance * 100))
    payment_cents = [(int(round(p['amount'] * 100)), p) for p in payments]
    
    n = len(payment_cents)
    
    # Try to find exact match or within tolerance
    for target_offset in range(-tolerance_cents, tolerance_cents + 1):
        adjusted_target = target_cents + target_offset
        
        if adjusted_target < 0:
            continue
        
        # DP table: dp[i][s] = list of payment indices that sum to s using first i payments
        # We'll use a simpler approach: try all subsets (works for small n < 20)
        if n <= 20:
            # Brute force for small sets
            from itertools import combinations
            
            for r in range(1, n + 1):
                for combo in combinations(range(n), r):
                    combo_sum = sum(payment_cents[i][0] for i in combo)
                    if combo_sum == adjusted_target:
                        return [payment_cents[i][1] for i in combo]
        else:
            # For larger sets, use DP (more complex, skipping for now)
            # In practice, we won't have >20 payments in a 7-day window
            pass
    
    return None


def expand_cashouts(income_payments: List[Dict], conn, enable_llm: bool = False):
    """
    Replace generic VENMO CASHOUT transactions with individual income transactions
    
    Strategy:
    1. Find all VENMO CASHOUT transactions in Chase
    2. For each cashout, find Venmo income payments that happened before it
    3. Delete the generic cashout transaction
    4. Create individual transactions for each Venmo income payment
    """
    if not income_payments:
        print("\n⚠️  No Venmo income payments provided")
        return []
    
    # Determine date range of Venmo data
    venmo_dates = [p['date'] for p in income_payments]
    min_venmo_date = min(venmo_dates)
    max_venmo_date = max(venmo_dates)
    
    cursor = conn.cursor()
    
    # Find VENMO CASHOUT transactions within the Venmo data date range
    cursor.execute("""
        SELECT 
            txn_id,
            txn_date,
            post_date,
            amount,
            direction,
            description_raw,
            account_id,
            source
        FROM transactions
        WHERE merchant_norm = 'VENMO CASHOUT'
          AND direction = 'credit'
          AND txn_date >= %s
          AND txn_date <= %s
        ORDER BY txn_date, amount  -- Process chronologically!
    """, (min_venmo_date, max_venmo_date))
    
    cashouts = cursor.fetchall()
    
    if not cashouts:
        print(f"\n⚠️  No VENMO CASHOUT transactions found between {min_venmo_date} and {max_venmo_date}")
        return []
    
    print(f"\n🔄 Found {len(cashouts)} VENMO CASHOUT transactions to expand (within Venmo data date range)...")
    print(f"   Processing chronologically per account (14-day lookback window)...")
    
    # Group income payments by account owner
    income_by_account = {}
    for payment in income_payments:
        account = payment.get('account_owner', 'unknown')
        if account not in income_by_account:
            income_by_account[account] = []
        income_by_account[account].append(payment)
    
    print(f"   Accounts found: {', '.join(income_by_account.keys())}")
    
    expansions = []
    used_income_by_account = {account: set() for account in income_by_account.keys()}  # Track per account
    
    for cashout in cashouts:  # Already sorted chronologically by SQL
        txn_id, txn_date, post_date, amount, direction, description, account_id, source = cashout
        
        # Convert Decimal to float for comparison
        amount = float(amount)
        
        print(f"\n💰 Cashout: ${amount:.2f} on {txn_date}")
        
        # Try to match this cashout against each account's income pool
        best_match = None
        best_account = None
        
        for account_name, account_income in income_by_account.items():
            # Find Venmo income payments from THIS account that could be part of this cashout
            # Look for income payments within 14 days before the cashout
            from datetime import datetime, timedelta
            cashout_date = datetime.strptime(str(txn_date), '%Y-%m-%d')
            start_date = (cashout_date - timedelta(days=14)).strftime('%Y-%m-%d')
            
            # Get all income payments in the date range (not yet used) from this account
            candidate_payments = []
            for income in sorted(account_income, key=lambda x: x['date']):
                # Skip income payments already matched to other cashouts IN THIS ACCOUNT
                income_id = f"{income['date']}_{income['amount']}_{income['from_name']}"
                if income_id in used_income_by_account[account_name]:
                    continue
                    
                if start_date <= income['date'] <= str(txn_date):
                    candidate_payments.append(income)
            
            if not candidate_payments:
                continue  # Try next account
            
            # Try to find a subset that sums to the cashout amount
            matching_income = find_subset_sum(candidate_payments, amount)
            
            if matching_income:
                # Found a match for this account!
                best_match = matching_income
                best_account = account_name
                break  # Stop trying other accounts
        
        # Apply the best match if found
        if best_match:
            print(f"   ✅ Matched {len(best_match)} Venmo income payments from @{best_account}:")
            for inc in best_match:
                print(f"      • ${inc['amount']:.2f} from {inc['from_name']} - {inc['note'][:50] if inc['note'] else '(no note)'}")
                # Mark this income payment as used IN THIS ACCOUNT
                income_id = f"{inc['date']}_{inc['amount']}_{inc['from_name']}"
                used_income_by_account[best_account].add(income_id)
            
            expansions.append({
                'cashout_txn_id': txn_id,
                'cashout_date': txn_date,
                'cashout_amount': amount,
                'account_id': account_id,
                'source': source,
                'income_payments': best_match,
                'venmo_account': best_account
            })
        else:
            # No account had a matching combination
            print(f"   ⚠️  Could not find combination that equals ${amount:.2f} across any account")
    
    cursor.close()
    
    if not expansions:
        print(f"\n⚠️  No cashouts could be matched to income payments")
        print(f"   Tip: Make sure your Venmo CSV covers the same time period as the cashouts")
        return []
    
    print(f"\n✅ Ready to expand {len(expansions)} cashouts into {sum(len(e['income_payments']) for e in expansions)} transactions")
    
    return expansions


def apply_expansions(expansions: List[Dict], conn, enable_llm: bool = False):
    """
    Actually delete cashouts and create individual income transactions
    """
    cursor = conn.cursor()
    
    print(f"\n📝 Applying expansions...")
    
    created_count = 0
    deleted_count = 0
    
    for expansion in expansions:
        # Delete the cashout transaction
        cursor.execute("""
            DELETE FROM transactions
            WHERE txn_id = %s
        """, (expansion['cashout_txn_id'],))
        deleted_count += 1
        
        print(f"\n🗑️  Deleted cashout: ${expansion['cashout_amount']:.2f}")
        
        # Create individual transactions for each income payment
        for income in expansion['income_payments']:
            # Build enriched description with account info
            account = expansion.get('venmo_account', 'Unknown')
            description = f"Venmo (@{account}) from {income['from_name']}"
            if income['note']:
                description += f": {income['note']}"
            
            # Truncate description to fit VARCHAR(200) limit
            description = description[:200]
            
            # Build notes with account info
            notes = f"Venmo Account: @{account} | From: {income['from_name']}"
            if income['note']:
                notes += f" | Note: {income['note']}"
            
            # Insert new transaction
            import hashlib
            
            # Create a short, unique hash for source_row_hash
            unique_str = f"{income['date']}_{income['amount']}_{income['from_name']}_{account}_{income.get('note', '')}"
            hash_suffix = hashlib.md5(unique_str.encode()).hexdigest()[:8]  # 8-char hash
            
            cursor.execute("""
                INSERT INTO transactions (
                    account_id,
                    source,
                    source_row_hash,
                    txn_date,
                    post_date,
                    description_raw,
                    merchant_raw,
                    merchant_norm,
                    merchant_detail,
                    amount,
                    currency,
                    direction,
                    type,
                    is_return,
                    category,
                    subcategory,
                    tag_source,
                    tag_confidence,
                    needs_review,
                    notes,
                    created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'USD', 'credit', 'Venmo Income', FALSE,
                    'Income', 'Other', 'venmo_expanded', 0.80, TRUE,
                    %s, 'venmo_enrichment'
                )
            """, (
                expansion['account_id'],
                expansion['source'],
                f"venmo_exp_{hash_suffix}",  # Short hash!
                income['date'],
                expansion['cashout_date'],  # Use cashout post date
                description[:200],  # description_raw - VARCHAR(200)
                description[:64],   # merchant_raw - VARCHAR(64)
                'VENMO FROM',
                income['from_name'][:64],  # merchant_detail - VARCHAR(64)
                income['amount'],
                notes  # Use the notes variable we built
            ))
            
            created_count += 1
            print(f"   ✅ Created: ${income['amount']:.2f} from {income['from_name']} (@{account})")
    
    conn.commit()
    cursor.close()
    
    print(f"\n✅ Expansion complete!")
    print(f"   Deleted: {deleted_count} cashout transactions")
    print(f"   Created: {created_count} individual income transactions")
    print(f"   All marked as needs_review=TRUE for categorization")


def enrich_transactions(matches: List[Dict], conn, enable_llm: bool = False):
    """
    Update Chase transactions with Venmo note/recipient data
    
    Optionally uses LLM to suggest better categories based on enriched data
    """
    cursor = conn.cursor()
    
    print(f"\n🔄 Enriching {len(matches)} transactions...")
    
    for match in matches:
        venmo = match['venmo_txn']
        chase_id = match['chase_txn_id']
        
        # Build enriched note
        parts = []
        
        if venmo['note']:
            parts.append(f"Note: {venmo['note']}")
        
        if venmo['direction'] == 'debit' and venmo['to_name']:
            parts.append(f"To: {venmo['to_name']}")
        elif venmo['direction'] == 'credit' and venmo['from_name']:
            parts.append(f"From: {venmo['from_name']}")
        
        enriched_note = " | ".join(parts)
        
        # Update notes field
        cursor.execute("""
            UPDATE transactions
            SET notes = %s
            WHERE txn_id = %s
        """, (enriched_note, chase_id))
        
        print(f"  ✅ {match['chase_description'][:30]:<30} → {enriched_note}")
    
    conn.commit()
    cursor.close()
    
    print(f"\n✅ Enriched {len(matches)} transactions!")
    
    # Optionally suggest better categories with LLM
    if enable_llm:
        print("\n🤖 Running LLM to suggest better categories based on enriched data...")
        suggest_categories_with_llm(matches, conn)


def suggest_categories_with_llm(matches: List[Dict], conn):
    """
    Use LLM to suggest categories for enriched Venmo transactions
    """
    from budget_automation.core.llm_categorizer import LLMCategorizer
    import json
    from pathlib import Path
    
    # Load taxonomy
    taxonomy_file = Path(__file__).parent / "budget_automation" / "data" / "taxonomy.json"
    with open(taxonomy_file) as f:
        taxonomy = json.load(f)
    
    categorizer = LLMCategorizer(taxonomy)
    
    if not categorizer.enabled:
        print("⚠️  LLM not enabled, skipping category suggestions")
        return
    
    cursor = conn.cursor()
    
    for match in matches:
        venmo = match['venmo_txn']
        chase_id = match['chase_txn_id']
        
        # Build enhanced description for LLM
        description = f"Venmo payment: {venmo['note']}"
        if venmo['direction'] == 'debit':
            description += f" to {venmo['to_name']}"
        else:
            description += f" from {venmo['from_name']}"
        
        # Get LLM suggestion
        result = categorizer.categorize(
            merchant_norm='VENMO',
            merchant_detail=venmo['to_name'] if venmo['direction'] == 'debit' else venmo['from_name'],
            description_raw=description,
            amount=venmo['amount'],
            direction=venmo['direction']
        )
        
        if result and result['confidence'] >= 0.85:
            # Update category
            cursor.execute("""
                UPDATE transactions
                SET category = %s,
                    subcategory = %s,
                    tag_source = 'llm_enriched',
                    tag_confidence = %s,
                    needs_review = FALSE
                WHERE txn_id = %s
            """, (result['category'], result['subcategory'], result['confidence'], chase_id))
            
            print(f"  💡 {venmo['note'][:40]:<40} → {result['category']} / {result['subcategory']} ({result['confidence']:.0%})")
    
    conn.commit()
    cursor.close()


def main():
    """Main enrichment workflow"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='Enrich Chase Venmo transactions with Venmo CSV data')
    parser.add_argument('venmo_csv', nargs='+', help='Path to Venmo statement CSV(s) - can specify multiple files')
    parser.add_argument('--llm', action='store_true', help='Use LLM to suggest categories after enrichment')
    parser.add_argument('--expand', action='store_true', help='Expand VENMO CASHOUT transfers into individual income transactions')
    parser.add_argument('--dry-run', action='store_true', help='Show matches without updating database')
    
    args = parser.parse_args()
    
    # Support multiple CSV files
    venmo_csvs = args.venmo_csv if isinstance(args.venmo_csv, list) else [args.venmo_csv]
    
    print("=" * 80)
    print("💰 VENMO TRANSACTION ENRICHMENT")
    print("=" * 80)
    print(f"Venmo CSV(s): {', '.join(venmo_csvs)}")
    print(f"LLM Enabled: {args.llm}")
    print(f"Expand Cashouts: {args.expand}")
    print(f"Dry Run: {args.dry_run}")
    print("=" * 80)
    
    # Parse all Venmo CSVs
    print(f"\n📄 Parsing {len(venmo_csvs)} Venmo CSV(s)...")
    all_venmo_txns = []
    for csv_file in venmo_csvs:
        txns = parse_venmo_csv(csv_file)
        all_venmo_txns.extend(txns)
        print(f"   ✅ {csv_file}: {len(txns)} transactions")
    
    print(f"✅ Total: {len(all_venmo_txns)} Venmo transactions")
    
    # Filter to payments and income
    payments = [t for t in all_venmo_txns if t['type'] == 'Payment']
    transfers = [t for t in all_venmo_txns if t['type'] == 'Standard Transfer']
    income_payments = [t for t in payments if t['direction'] == 'credit']
    outgoing_payments = [t for t in payments if t['direction'] == 'debit']
    
    print(f"   ({len(outgoing_payments)} outgoing, {len(income_payments)} incoming, {len(transfers)} transfers)")
    
    # Connect to database
    print("\n🔌 Connecting to database...")
    conn = get_db_connection()
    print("✅ Connected")
    
    # Match to Chase transactions
    print("\n🔍 Matching Venmo payments to Chase transactions...")
    matches = match_venmo_to_chase(outgoing_payments, conn)
    print(f"✅ Matched {len(matches)} / {len(outgoing_payments)} outgoing payments")
    
    # Expand cashouts if requested
    expansions = []
    if args.expand and income_payments:
        print("\n" + "=" * 80)
        print("🔄 EXPANDING VENMO CASHOUTS")
        print("=" * 80)
        expansions = expand_cashouts(income_payments, conn, enable_llm=args.llm)
    
    if not matches and not expansions:
        print("\n⚠️  No matches or expansions found!")
        conn.close()
        return
    
    # Show preview of enrichment
    if matches:
        print("\n" + "=" * 80)
        print("PREVIEW OF PAYMENT ENRICHMENT")
        print("=" * 80)
        for i, match in enumerate(matches[:5], 1):
            venmo = match['venmo_txn']
            print(f"\n{i}. Chase: {match['chase_description']}")
            print(f"   Amount: ${venmo['amount']:.2f} ({venmo['direction']})")
            print(f"   Venmo Note: {venmo['note']}")
            if venmo['to_name']:
                print(f"   To: {venmo['to_name']}")
            if venmo['from_name']:
                print(f"   From: {venmo['from_name']}")
        
        if len(matches) > 5:
            print(f"\n... and {len(matches) - 5} more")
    
    # Show preview of expansions
    if expansions:
        print("\n" + "=" * 80)
        print("PREVIEW OF CASHOUT EXPANSIONS")
        print("=" * 80)
        for i, exp in enumerate(expansions[:3], 1):
            account = exp.get('venmo_account', 'Unknown')
            print(f"\n{i}. Cashout: ${exp['cashout_amount']:.2f} on {exp['cashout_date']} (@{account})")
            print(f"   Will be replaced with {len(exp['income_payments'])} transactions:")
            for inc in exp['income_payments']:
                print(f"      • ${inc['amount']:.2f} from {inc['from_name']} - {inc['note'][:40] if inc['note'] else '(no note)'}")
        
        if len(expansions) > 3:
            print(f"\n... and {len(expansions) - 3} more cashouts")
    
    # Execute or dry run
    if args.dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN - No changes made")
        print("=" * 80)
    else:
        # Confirm
        print("\n" + "=" * 80)
        total_changes = len(matches) + sum(len(e['income_payments']) for e in expansions) + len(expansions)
        response = input(f"Apply {len(matches)} enrichments and {len(expansions)} expansions ({total_changes} total changes)? (y/n): ")
        if response.lower() == 'y':
            if matches:
                enrich_transactions(matches, conn, enable_llm=args.llm)
            if expansions:
                apply_expansions(expansions, conn, enable_llm=args.llm)
        else:
            print("❌ Cancelled")
    
    conn.close()


if __name__ == "__main__":
    main()
