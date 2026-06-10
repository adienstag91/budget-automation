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


def find_cashout_matches(conn, income_payments: List[Dict], lookback_days: int = 30) -> List[Dict]:
    """
    Find VENMO CASHOUT transactions and match them to income payments

    lookback_days controls how far before a cashout we look for funding income.
    Longer windows match more cashouts but raise the chance of a coincidental
    subset-sum that isn't the real funding.

    Returns list of expansions with cashout info and matched income payments
    """
    if not income_payments:
        return []
    
    # Determine date range of Venmo data
    venmo_dates = [p['date'] for p in income_payments]
    min_venmo_date = min(venmo_dates)
    max_venmo_date = max(venmo_dates)
    # A cashout happens AFTER the income that funds it, so consider cashouts up to
    # `lookback_days` past the latest staged income — otherwise a cashout a day
    # after the last payment is wrongly excluded. The per-cashout lookback below
    # still bounds which income can match.
    max_cashout_date = max_venmo_date + timedelta(days=lookback_days)

    cursor = conn.cursor()

    # Find VENMO CASHOUT transactions in the (forward-extended) Venmo data range
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
    """, (min_venmo_date, max_cashout_date))
    
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
            # Look back `lookback_days` before cashout
            cashout_datetime = datetime.combine(txn_date, datetime.min.time())
            start_date = (cashout_datetime - timedelta(days=lookback_days)).date()
            
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
                    category_source, category_confidence, needs_review,
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


def _iso(d):
    """Date/datetime -> ISO string (JSON-safe)."""
    return d.isoformat() if hasattr(d, 'isoformat') else str(d)


def build_venmo_enrichment_plan(conn, lookback_days: int = 30):
    """
    Read-only enrichment plan for the web preview. Writes nothing.

    Loads unenriched Venmo income + outgoing payments, runs the existing matching
    engine, and returns a unified, JSON-safe plan the UI can render and select from:

        {
          "totals": {expansions, enrich, new_rows, superseded},
          "rows": [
            {"kind":"expand","key":"expand:<cashout_txn_id>","date","amount",
             "venmo_account","income":[{amount,from_name,note}, ...]},
            {"kind":"enrich","key":"enrich:<txn_id>","date","amount",
             "venmo_account","to_name","note"}
          ]
        }
    """
    income_payments = get_unenriched_income_payments(conn)
    outgoing_payments = get_unenriched_outgoing_payments(conn)

    cashout_expansions = find_cashout_matches(conn, income_payments, lookback_days)
    outgoing_enrichments = find_outgoing_payment_matches(conn, outgoing_payments)

    rows = []
    new_rows = 0

    for exp in cashout_expansions:
        income = [
            {
                'amount': float(inc['amount']),
                'from_name': inc['from_name'],
                'note': inc['note'],
            }
            for inc in exp['income_payments']
        ]
        new_rows += len(income)
        rows.append({
            'kind': 'expand',
            'key': f"expand:{exp['cashout_txn_id']}",
            'date': _iso(exp['cashout_date']),
            'amount': float(exp['cashout_amount']),
            'venmo_account': exp['venmo_account'],
            'income': income,
        })

    for enr in outgoing_enrichments:
        p = enr['venmo_payment']
        rows.append({
            'kind': 'enrich',
            'key': f"enrich:{enr['txn_id']}",
            'date': _iso(p['date']),
            'amount': float(p['amount']),
            'venmo_account': enr['venmo_account'],
            'to_name': p['to_name'],
            'note': p['note'],
        })

    return {
        'totals': {
            'expansions': len(cashout_expansions),
            'enrich': len(outgoing_enrichments),
            'new_rows': new_rows,
            'superseded': len(cashout_expansions),
        },
        'rows': rows,
    }


def _apply_cashout_expansion_soft(conn, expansion):
    """
    Soft-supersede one cashout (exclude_from_budget = TRUE, NOT deleted) and create
    the detailed VENMO FROM rows. Does NOT commit — the caller owns the transaction.
    """
    import hashlib

    cursor = conn.cursor()

    # Soft-supersede the generic cashout instead of deleting it (reversible).
    cursor.execute(
        """
        UPDATE transactions
        SET exclude_from_budget = TRUE,
            notes = COALESCE(notes, '') || ' [superseded by Venmo enrichment]'
        WHERE txn_id = %s
        """,
        (expansion['cashout_txn_id'],),
    )

    created = 0
    for income in expansion['income_payments']:
        account = expansion['venmo_account']
        description = f"Venmo (@{account}) from {income['from_name']}"
        if income['note']:
            description += f": {income['note']}"
        description = description[:200]

        notes = f"Venmo Account: @{account} | From: {income['from_name']}"
        if income['note']:
            notes += f" | Note: {income['note']}"

        unique_str = f"{income['date']}_{income['amount']}_{income['from_name']}_{account}_{income.get('note', '')}"
        hash_suffix = hashlib.md5(unique_str.encode()).hexdigest()[:8]

        cursor.execute(
            """
            INSERT INTO transactions (
                account_id, source, source_row_hash,
                txn_date, post_date,
                description_raw, merchant_raw, merchant_norm, merchant_detail,
                amount, currency, direction, type, is_return,
                category, subcategory,
                category_source, category_confidence, needs_review,
                notes, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'USD', 'credit', 'Venmo Income', FALSE,
                'Income', 'Other', 'venmo_expanded', 0.80, TRUE,
                %s, 'venmo_enrichment'
            )
            ON CONFLICT (source_row_hash) DO NOTHING
            """,
            (
                expansion['account_id'],
                'venmo_enrichment',
                f"venmo_exp_{hash_suffix}",
                income['date'],
                expansion['cashout_post_date'],
                description[:200],
                description[:64],
                'VENMO FROM',
                income['from_name'][:64],
                income['amount'],
                notes,
            ),
        )
        created += 1

    # Mark the matched Venmo income rows as enriched.
    venmo_ids = [inc['venmo_id'] for inc in expansion['income_payments']]
    cursor.execute(
        """
        UPDATE venmo_transactions_raw
        SET enriched = TRUE, enriched_date = NOW()
        WHERE venmo_id = ANY(%s)
        """,
        (venmo_ids,),
    )
    cursor.close()
    return created


def _apply_outgoing_enrichment(conn, enr):
    """
    Relabel one VENMO OUTGOING Chase txn into VENMO TO + payee/note (in place,
    non-destructive). Does NOT commit — the caller owns the transaction.
    """
    cursor = conn.cursor()
    payment = enr['venmo_payment']
    account = enr['venmo_account']

    notes = f"Venmo Account: @{account} | To: {payment['to_name']}"
    if payment['note']:
        notes += f" | Note: {payment['note']}"

    cursor.execute(
        """
        UPDATE transactions
        SET merchant_norm = 'VENMO TO',
            merchant_detail = %s,
            notes = %s,
            created_by = 'venmo_enrichment'
        WHERE txn_id = %s
        """,
        (payment['to_name'][:64], notes, enr['txn_id']),
    )

    cursor.execute(
        """
        UPDATE venmo_transactions_raw
        SET enriched = TRUE, enriched_date = NOW()
        WHERE venmo_id = %s
        """,
        (payment['venmo_id'],),
    )
    cursor.close()


def commit_venmo_enrichment(conn, keys, lookback_days: int = 30):
    """
    Apply the selected enrichment `keys` in a single DB transaction.

    Recomputes the plan (so matching is fresh), filters to the selected keys, then:
      - "expand:<cashout_txn_id>" -> soft-supersede the cashout + create VENMO FROM rows
      - "enrich:<txn_id>"         -> relabel VENMO OUTGOING -> VENMO TO

    Rolls back the whole batch on any error.

    Returns: {"expanded_cashouts","new_rows","enriched_outgoing",
              "superseded_txns","skipped"}
    """
    selected = set(keys or [])

    income_payments = get_unenriched_income_payments(conn)
    outgoing_payments = get_unenriched_outgoing_payments(conn)
    cashout_expansions = find_cashout_matches(conn, income_payments, lookback_days)
    outgoing_enrichments = find_outgoing_payment_matches(conn, outgoing_payments)

    expand_by_key = {
        f"expand:{e['cashout_txn_id']}": e for e in cashout_expansions
    }
    enrich_by_key = {
        f"enrich:{en['txn_id']}": en for en in outgoing_enrichments
    }

    expanded_cashouts = 0
    new_rows = 0
    enriched_outgoing = 0
    skipped = 0

    try:
        for key in selected:
            if key in expand_by_key:
                new_rows += _apply_cashout_expansion_soft(conn, expand_by_key[key])
                expanded_cashouts += 1
            elif key in enrich_by_key:
                _apply_outgoing_enrichment(conn, enrich_by_key[key])
                enriched_outgoing += 1
            else:
                # No longer matchable (already enriched, or data changed).
                skipped += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        'expanded_cashouts': expanded_cashouts,
        'new_rows': new_rows,
        'enriched_outgoing': enriched_outgoing,
        'superseded_txns': expanded_cashouts,
        'skipped': skipped,
    }


def reset_venmo_enrichment(conn, dry_run=False):
    """
    Revert all Venmo enrichment back to a clean baseline so it can be re-run from
    scratch. Idempotent and reversible-by-rerun. With dry_run=True, reports the
    counts that WOULD change without writing.

    Undoes:
      - VENMO FROM income rows created by enrichment   -> deleted
      - VENMO TO relabels (created_by=venmo_enrichment) -> back to VENMO OUTGOING
      - VENMO CASHOUT soft-supersedes                   -> exclude_from_budget=FALSE
      - venmo_transactions_raw.enriched flags           -> FALSE

    Returns a summary dict (also serves as the dry-run preview).
    """
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions"
        " WHERE merchant_norm = 'VENMO FROM' AND source = 'venmo_enrichment'"
    )
    from_rows, from_sum = cur.fetchone()
    cur.execute(
        "SELECT COUNT(*) FROM transactions"
        " WHERE merchant_norm = 'VENMO TO' AND created_by = 'venmo_enrichment'"
    )
    to_rows = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM transactions"
        " WHERE merchant_norm = 'VENMO CASHOUT' AND exclude_from_budget = TRUE"
    )
    superseded = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM venmo_transactions_raw WHERE enriched = TRUE")
    staged_enriched = cur.fetchone()[0]

    summary = {
        'venmo_from_deleted': from_rows,
        'venmo_from_amount': float(from_sum),
        'venmo_to_reverted': to_rows,
        'cashouts_unsuperseded': superseded,
        'staging_reset': staged_enriched,
    }

    if dry_run:
        cur.close()
        return summary

    try:
        # 1. Drop the enrichment-created income rows.
        cur.execute(
            "DELETE FROM transactions"
            " WHERE merchant_norm = 'VENMO FROM' AND source = 'venmo_enrichment'"
        )
        # 2. Revert relabeled outgoing back to the generic form.
        cur.execute(
            "UPDATE transactions SET merchant_norm = 'VENMO OUTGOING',"
            " merchant_detail = NULL, notes = NULL"
            " WHERE merchant_norm = 'VENMO TO' AND created_by = 'venmo_enrichment'"
        )
        # 3. Un-supersede cashouts and strip the marker note.
        cur.execute(
            "UPDATE transactions SET exclude_from_budget = FALSE,"
            " notes = NULLIF(REPLACE(COALESCE(notes, ''),"
            " ' [superseded by Venmo enrichment]', ''), '')"
            " WHERE merchant_norm = 'VENMO CASHOUT' AND exclude_from_budget = TRUE"
        )
        # 4. Free all staged Venmo rows for a fresh match.
        cur.execute(
            "UPDATE venmo_transactions_raw SET enriched = FALSE, enriched_date = NULL"
            " WHERE enriched = TRUE"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    cur.close()
    return summary


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
