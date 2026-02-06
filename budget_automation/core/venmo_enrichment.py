"""
Venmo Transaction Enrichment - ELT Architecture

Reads from venmo_transactions_raw staging table and:
1. Expands VENMO CASHOUT into detailed VENMO FROM transactions
2. Enriches VENMO OUTGOING with VENMO TO details (who/why)
"""
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from itertools import combinations

from budget_automation.utils.db_connection import get_db_connection


def get_unenriched_income_payments(conn):
    """
    Get Venmo income payments (credits) from staging table that haven't been enriched
    
    Returns list of income payments (money received)
    """
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            venmo_id,
            transaction_datetime,
            amount,
            direction,
            from_name,
            to_name,
            note,
            account_owner
        FROM venmo_transactions_raw
        WHERE enriched = FALSE
          AND direction = 'credit'
        ORDER BY transaction_datetime
    """)
    
    rows = cursor.fetchall()
    cursor.close()
    
    income_payments = []
    for row in rows:
        income_payments.append({
            'venmo_id': row[0],
            'date': row[1].date() if hasattr(row[1], 'date') else row[1],
            'amount': float(row[2]),
            'direction': row[3],
            'from_name': row[4],
            'to_name': row[5],
            'note': row[6],
            'account_owner': row[7]
        })
    
    return income_payments


def get_unenriched_outgoing_payments(conn):
    """
    Get Venmo outgoing payments (debits) from staging table that haven't been enriched
    
    Returns list of outgoing payments (money sent)
    """
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            venmo_id,
            transaction_datetime,
            amount,
            direction,
            from_name,
            to_name,
            note,
            account_owner
        FROM venmo_transactions_raw
        WHERE enriched = FALSE
          AND direction = 'debit'
        ORDER BY transaction_datetime
    """)
    
    rows = cursor.fetchall()
    cursor.close()
    
    outgoing_payments = []
    for row in rows:
        outgoing_payments.append({
            'venmo_id': row[0],
            'date': row[1].date() if hasattr(row[1], 'date') else row[1],
            'amount': float(row[2]),
            'direction': row[3],
            'from_name': row[4],
            'to_name': row[5],
            'note': row[6],
            'account_owner': row[7]
        })
    
    return outgoing_payments


def find_subset_sum(payments: List[Dict], target: float, tolerance: float = 0.02) -> Optional[List[Dict]]:
    """
    Find a subset of payments that sum to target amount (within tolerance)
    
    Used for matching multiple income payments to a single cashout
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
        
        # Try all subsets (works for small n < 20)
        if n <= 20:
            for r in range(1, n + 1):
                for combo in combinations(range(n), r):
                    combo_sum = sum(payment_cents[i][0] for i in combo)
                    if combo_sum == adjusted_target:
                        return [payment_cents[i][1] for i in combo]
    
    return None


def find_cashout_matches(conn, income_payments: List[Dict]) -> List[Dict]:
    """
    Find VENMO CASHOUT transactions and match them to income payments
    
    Returns list of expansions with cashout info and matched income payments
    """
    if not income_payments:
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
            account_id,
            source
        FROM transactions
        WHERE merchant_norm = 'VENMO CASHOUT'
          AND direction = 'credit'
          AND txn_date >= %s
          AND txn_date <= %s
        ORDER BY txn_date, amount
    """, (min_venmo_date, max_venmo_date))
    
    cashouts = cursor.fetchall()
    cursor.close()
    
    if not cashouts:
        return []
    
    print(f"\n🔄 Found {len(cashouts)} VENMO CASHOUT transactions")
    print(f"   Matching to income payments (14-day lookback)...")
    
    # Group income payments by account owner
    income_by_account = {}
    for payment in income_payments:
        account = payment.get('account_owner', 'unknown')
        if account not in income_by_account:
            income_by_account[account] = []
        income_by_account[account].append(payment)
    
    print(f"   Venmo accounts: {', '.join(income_by_account.keys())}")
    
    expansions = []
    used_income_by_account = {account: set() for account in income_by_account.keys()}
    
    for cashout in cashouts:
        txn_id, txn_date, post_date, amount, account_id, source = cashout
        amount = float(amount)
        
        print(f"\n💰 Cashout: ${amount:.2f} on {txn_date}")
        
        # Try to match against each Venmo account
        best_match = None
        best_account = None
        
        for account_name, account_income in income_by_account.items():
            # Look back 14 days before cashout
            cashout_datetime = datetime.combine(txn_date, datetime.min.time())
            start_date = (cashout_datetime - timedelta(days=14)).date()
            
            # Get unused income payments in date range
            candidate_payments = []
            for income in sorted(account_income, key=lambda x: x['date']):
                income_id = f"{income['date']}_{income['amount']}_{income['from_name']}"
                if income_id in used_income_by_account[account_name]:
                    continue
                    
                if start_date <= income['date'] <= txn_date:
                    candidate_payments.append(income)
            
            if not candidate_payments:
                continue
            
            # Find subset that sums to cashout
            matching_income = find_subset_sum(candidate_payments, amount)
            
            if matching_income:
                best_match = matching_income
                best_account = account_name
                break
        
        if best_match:
            print(f"   ✅ Matched {len(best_match)} payments from @{best_account}")
            for inc in best_match:
                print(f"      • ${inc['amount']:.2f} from {inc['from_name']}")
                income_id = f"{inc['date']}_{inc['amount']}_{inc['from_name']}"
                used_income_by_account[best_account].add(income_id)
            
            expansions.append({
                'cashout_txn_id': txn_id,
                'cashout_date': txn_date,
                'cashout_post_date': post_date,
                'cashout_amount': amount,
                'account_id': account_id,
                'source': source,
                'income_payments': best_match,
                'venmo_account': best_account
            })
        else:
            print(f"   ⚠️  No match found")
    
    return expansions


def find_outgoing_payment_matches(conn, outgoing_payments: List[Dict]) -> List[Dict]:
    """
    Find VENMO OUTGOING transactions and match them to outgoing payment details
    
    Returns list of enrichments with Chase transaction and Venmo details
    """
    if not outgoing_payments:
        return []
    
    # Determine date range
    venmo_dates = [p['date'] for p in outgoing_payments]
    min_venmo_date = min(venmo_dates)
    max_venmo_date = max(venmo_dates)
    
    cursor = conn.cursor()
    
    # Find VENMO OUTGOING transactions (generic Chase transactions)
    cursor.execute("""
        SELECT 
            txn_id,
            txn_date,
            amount,
            description_raw
        FROM transactions
        WHERE merchant_norm = 'VENMO OUTGOING'
          AND direction = 'debit'
          AND txn_date >= %s
          AND txn_date <= %s
        ORDER BY txn_date, amount
    """, (min_venmo_date, max_venmo_date))
    
    outgoing_txns = cursor.fetchall()
    cursor.close()
    
    if not outgoing_txns:
        return []
    
    print(f"\n🔄 Found {len(outgoing_txns)} VENMO OUTGOING transactions")
    print(f"   Matching to outgoing payment details (±3 day window)...")
    
    # Group by account
    payments_by_account = {}
    for payment in outgoing_payments:
        account = payment.get('account_owner', 'unknown')
        if account not in payments_by_account:
            payments_by_account[account] = []
        payments_by_account[account].append(payment)
    
    enrichments = []
    used_payments_by_account = {account: set() for account in payments_by_account.keys()}
    
    for txn in outgoing_txns:
        txn_id, txn_date, amount, description = txn
        amount = float(amount)
        
        print(f"\n💸 Outgoing: ${amount:.2f} on {txn_date}")
        
        # Try to match against each account
        best_match = None
        best_account = None
        
        for account_name, account_payments in payments_by_account.items():
            # Look for payment within ±3 days
            for payment in account_payments:
                payment_id = f"{payment['date']}_{payment['amount']}_{payment['to_name']}"
                if payment_id in used_payments_by_account[account_name]:
                    continue
                
                # Check date (±3 days) and amount (within $0.02)
                date_diff = abs((payment['date'] - txn_date).days)
                amount_diff = abs(payment['amount'] - amount)
                
                if date_diff <= 3 and amount_diff < 0.02:
                    best_match = payment
                    best_account = account_name
                    break
            
            if best_match:
                break
        
        if best_match:
            print(f"   ✅ Matched to @{best_account}: To {best_match['to_name']}")
            payment_id = f"{best_match['date']}_{best_match['amount']}_{best_match['to_name']}"
            used_payments_by_account[best_account].add(payment_id)
            
            enrichments.append({
                'txn_id': txn_id,
                'venmo_payment': best_match,
                'venmo_account': best_account
            })
        else:
            print(f"   ⚠️  No match found")
    
    return enrichments


def apply_cashout_expansions(conn, expansions: List[Dict], dry_run: bool = False):
    """
    Delete cashouts and create detailed VENMO FROM transactions
    """
    if not expansions:
        return
    
    if dry_run:
        print(f"\n🔍 DRY RUN - Would expand {len(expansions)} cashouts:")
        for exp in expansions:
            print(f"\n   Delete: ${exp['cashout_amount']:.2f} cashout")
            print(f"   Create {len(exp['income_payments'])} VENMO FROM transactions:")
            for inc in exp['income_payments']:
                print(f"      • ${inc['amount']:.2f} from {inc['from_name']} (@{exp['venmo_account']})")
        return
    
    cursor = conn.cursor()
    
    print(f"\n📝 Expanding {len(expansions)} cashouts...")
    
    created_count = 0
    deleted_count = 0
    
    for expansion in expansions:
        # Delete the cashout
        cursor.execute("DELETE FROM transactions WHERE txn_id = %s", 
                      (expansion['cashout_txn_id'],))
        deleted_count += 1
        
        # Create individual VENMO FROM transactions
        for income in expansion['income_payments']:
            account = expansion['venmo_account']
            description = f"Venmo (@{account}) from {income['from_name']}"
            if income['note']:
                description += f": {income['note']}"
            description = description[:200]
            
            notes = f"Venmo Account: @{account} | From: {income['from_name']}"
            if income['note']:
                notes += f" | Note: {income['note']}"
            
            import hashlib
            unique_str = f"{income['date']}_{income['amount']}_{income['from_name']}_{account}_{income.get('note', '')}"
            hash_suffix = hashlib.md5(unique_str.encode()).hexdigest()[:8]
            
            cursor.execute("""
                INSERT INTO transactions (
                    account_id, source, source_row_hash,
                    txn_date, post_date,
                    description_raw, merchant_raw, merchant_norm, merchant_detail,
                    amount, currency, direction, type, is_return,
                    category, subcategory,
                    tag_source, tag_confidence, needs_review,
                    notes, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'USD', 'credit', 'Venmo Income', FALSE,
                    'Income', 'Other', 'venmo_expanded', 0.80, TRUE,
                    %s, 'venmo_enrichment'
                )
            """, (
                expansion['account_id'],
                'venmo_enrichment',
                f"venmo_exp_{hash_suffix}",
                income['date'],
                expansion['cashout_post_date'],
                description[:200],
                description[:64],
                'VENMO FROM',  # New naming!
                income['from_name'][:64],
                income['amount'],
                notes
            ))
            
            created_count += 1
        
        # Mark Venmo data as enriched
        venmo_ids = [inc['venmo_id'] for inc in expansion['income_payments']]
        cursor.execute("""
            UPDATE venmo_transactions_raw
            SET enriched = TRUE, enriched_date = NOW()
            WHERE venmo_id = ANY(%s)
        """, (venmo_ids,))
    
    conn.commit()
    cursor.close()
    
    print(f"   ✅ Deleted {deleted_count} cashouts")
    print(f"   ✅ Created {created_count} VENMO FROM transactions")


def apply_outgoing_enrichments(conn, enrichments: List[Dict], dry_run: bool = False):
    """
    Enrich VENMO OUTGOING transactions with details (who/why)
    """
    if not enrichments:
        return
    
    if dry_run:
        print(f"\n🔍 DRY RUN - Would enrich {len(enrichments)} outgoing payments:")
        for enr in enrichments:
            payment = enr['venmo_payment']
            print(f"\n   Enrich: ${payment['amount']:.2f}")
            print(f"      Set merchant_norm: VENMO TO")
            print(f"      Set merchant_detail: {payment['to_name']}")
            print(f"      Add note: {payment['note'][:50] if payment['note'] else '(no note)'}")
        return
    
    cursor = conn.cursor()
    
    print(f"\n📝 Enriching {len(enrichments)} outgoing payments...")
    
    for enr in enrichments:
        payment = enr['venmo_payment']
        account = enr['venmo_account']
        
        notes = f"Venmo Account: @{account} | To: {payment['to_name']}"
        if payment['note']:
            notes += f" | Note: {payment['note']}"
        
        cursor.execute("""
            UPDATE transactions
            SET 
                merchant_norm = 'VENMO TO',
                merchant_detail = %s,
                notes = %s,
                created_by = 'venmo_enrichment'
            WHERE txn_id = %s
        """, (
            payment['to_name'][:64],
            notes,
            enr['txn_id']
        ))
        
        # Mark Venmo data as enriched
        cursor.execute("""
            UPDATE venmo_transactions_raw
            SET enriched = TRUE, enriched_date = NOW()
            WHERE venmo_id = %s
        """, (payment['venmo_id'],))
    
    conn.commit()
    cursor.close()
    
    print(f"   ✅ Enriched {len(enrichments)} transactions")


def enrich_venmo_transactions(dry_run: bool = False, enable_llm: bool = False):
    """
    Main enrichment process
    """
    print("=" * 80)
    print("💸 VENMO TRANSACTION ENRICHMENT")
    print("=" * 80)
    print(f"Dry Run: {dry_run}")
    if enable_llm:
        print(f"LLM: Enabled (placeholder - not yet implemented)")
    print("=" * 80)
    
    # Connect
    print("\n🔌 Connecting to database...")
    conn = get_db_connection()
    print("✅ Connected")
    
    # Get data from staging table
    print("\n📥 Loading unenriched Venmo data...")
    income_payments = get_unenriched_income_payments(conn)
    outgoing_payments = get_unenriched_outgoing_payments(conn)
    
    print(f"✅ Found {len(income_payments)} income payments")
    print(f"✅ Found {len(outgoing_payments)} outgoing payments")
    
    if not income_payments and not outgoing_payments:
        print("\n⚠️  No unenriched Venmo data found")
        print("   Have you imported Venmo CSVs?")
        print("   Run: python budget_automation/core/venmo_import.py <csv_files>")
        conn.close()
        return
    
    # Summary by account
    if income_payments or outgoing_payments:
        print(f"\n📊 Summary by account:")
        
        if income_payments:
            by_account = {}
            for p in income_payments:
                account = p['account_owner']
                by_account.setdefault(account, []).append(p)
            for account, payments in by_account.items():
                total = sum(p['amount'] for p in payments)
                print(f"  • @{account}: {len(payments)} income (${total:.2f})")
        
        if outgoing_payments:
            by_account = {}
            for p in outgoing_payments:
                account = p['account_owner']
                by_account.setdefault(account, []).append(p)
            for account, payments in by_account.items():
                total = sum(p['amount'] for p in payments)
                print(f"  • @{account}: {len(payments)} outgoing (${total:.2f})")
    
    # Find matches
    cashout_expansions = find_cashout_matches(conn, income_payments)
    outgoing_enrichments = find_outgoing_payment_matches(conn, outgoing_payments)
    
    if not cashout_expansions and not outgoing_enrichments:
        print("\n⚠️  No matches found!")
        conn.close()
        return
    
    # Summary
    total_income_txns = sum(len(e['income_payments']) for e in cashout_expansions)
    print(f"\n✅ Ready to process:")
    if cashout_expansions:
        print(f"  • Expand {len(cashout_expansions)} cashouts → {total_income_txns} VENMO FROM transactions")
    if outgoing_enrichments:
        print(f"  • Enrich {len(outgoing_enrichments)} VENMO OUTGOING → VENMO TO transactions")
    
    # Execute
    if dry_run:
        apply_cashout_expansions(conn, cashout_expansions, dry_run=True)
        apply_outgoing_enrichments(conn, outgoing_enrichments, dry_run=True)
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE - No changes made")
        print("=" * 80)
    else:
        print(f"\n" + "=" * 80)
        response = input(f"Apply enrichments? (y/n): ")
        
        if response.lower() != 'y':
            print("❌ Cancelled")
            conn.close()
            return
        
        apply_cashout_expansions(conn, cashout_expansions, dry_run=False)
        apply_outgoing_enrichments(conn, outgoing_enrichments, dry_run=False)
        
        print("\n" + "=" * 80)
        print("✅ ENRICHMENT COMPLETE!")
        print("=" * 80)
        print(f"\n💡 Next: Review in dashboard")
        print(f"   streamlit run budget_automation/dashboard.py")
    
    conn.close()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Enrich Venmo transactions from staging table',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - preview changes
  python budget_automation/core/venmo_enrichment.py --dry-run
  
  # Expand cashouts and enrich outgoing payments
  python budget_automation/core/venmo_enrichment.py --expand
  
  # With LLM categorization (placeholder - not yet implemented)
  python budget_automation/core/venmo_enrichment.py --expand --llm
        """
    )
    
    parser.add_argument(
        '--expand',
        action='store_true',
        help='Actually apply enrichments (required to make changes)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )
    
    parser.add_argument(
        '--llm',
        action='store_true',
        help='Enable LLM categorization (placeholder - not yet implemented)'
    )
    
    args = parser.parse_args()
    
    # Require either dry-run or expand
    if not args.dry_run and not args.expand:
        print("❌ Error: Must specify either --dry-run or --expand")
        print("   Use --dry-run to preview")
        print("   Use --expand to apply enrichments")
        return 1
    
    enrich_venmo_transactions(dry_run=args.dry_run, enable_llm=args.llm)
    
    return 0


if __name__ == "__main__":
    exit(main())
