"""
Venmo Transaction Enrichment — funding-source ingestion.

A Venmo cashout (Standard Transfer to bank) is just the net of the balance-
affecting activity since the last transfer. Rather than guess that net with a
subset-sum of incoming credits (which can't subtract outgoing payments and can't
tell balance-funded from bank-funded ones), we read the Venmo "Funding Source" /
"Destination" columns and classify each row deterministically:

  - credit, Destination = "Venmo balance"      -> VENMO FROM income row (new)
  - debit,  Funding Source = "Venmo balance"   -> VENMO TO expense row (new;
                                                  not on the bank statement)
  - debit,  Funding Source = bank/card         -> already a bank VENMO OUTGOING
                                                  debit -> relabel it VENMO TO
  - "Standard Transfer" (-> bank)              -> the cashout: supersede the
                                                  matching bank VENMO CASHOUT

By construction sum(income) - sum(expense) ~= sum(cashouts) (residual = the
balance still sitting in Venmo), so every in-window cashout reconciles.
"""
import argparse
import hashlib
from datetime import timedelta

from budget_automation.utils.db_connection import get_db_connection

# Balance-affecting Venmo payments are not tied to a specific bank account, so
# they attach to the household checking account.
INGEST_ACCOUNT_ID = 1
VENMO_BALANCE = "Venmo balance"


def _iso(d):
    """Date/datetime -> ISO string (JSON-safe)."""
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _get_unenriched_staging(conn):
    """All unenriched Venmo staging rows (with funding-source classification)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT venmo_id, transaction_date, transaction_type, amount, direction,
               from_name, to_name, note, account_owner, funding_source, destination
        FROM venmo_transactions_raw
        WHERE enriched = FALSE
        ORDER BY transaction_datetime
        """
    )
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    for r in rows:
        r["amount"] = float(r["amount"])
    return rows


def _classify(rows):
    """Split staging rows into (income, expense, transfers, bank_out) buckets."""
    income, expense, transfers, bank_out = [], [], [], []
    for r in rows:
        ttype = (r.get("transaction_type") or "").strip()
        if ttype == "Standard Transfer":
            transfers.append(r)
        elif r["direction"] == "credit" and r.get("destination") == VENMO_BALANCE:
            income.append(r)
        elif r["direction"] == "debit" and r.get("funding_source") == VENMO_BALANCE:
            expense.append(r)
        elif r["direction"] == "debit":
            bank_out.append(r)
        # Credits not destined to the balance (instant-to-bank) already land on
        # the bank statement, so we ignore them here.
    return income, expense, transfers, bank_out


def _find_unused(conn, merchant_norm, direction, pay_date, amount, used, window_days):
    """Find the nearest bank txn (same merchant/direction/amount, within a date
    window) not already claimed by another match."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT txn_id FROM transactions
        WHERE merchant_norm = %s AND direction = %s AND amount = %s
          AND txn_date BETWEEN %s AND %s
        ORDER BY ABS(txn_date - %s)
        """,
        (
            merchant_norm, direction, amount,
            pay_date - timedelta(days=window_days),
            pay_date + timedelta(days=window_days),
            pay_date,
        ),
    )
    ids = [row[0] for row in cur.fetchall()]
    cur.close()
    for tid in ids:
        if tid not in used:
            return tid
    return None


def build_venmo_enrichment_plan(conn):
    """
    Read-only enrichment plan (funding-source ingestion). Writes nothing.

    Returns { totals, rows: [{kind, key, ...}] } where kind is one of
    income | expense | supersede | relabel.
    """
    income, expense, transfers, bank_out = _classify(_get_unenriched_staging(conn))

    rows = []
    inc_amt = exp_amt = 0.0

    for r in income:
        inc_amt += r["amount"]
        rows.append({
            "kind": "income", "key": f"income:{r['venmo_id']}",
            "date": _iso(r["transaction_date"]), "amount": r["amount"],
            "from_name": r["from_name"], "note": r["note"],
            "venmo_account": r["account_owner"],
        })
    for r in expense:
        exp_amt += r["amount"]
        rows.append({
            "kind": "expense", "key": f"expense:{r['venmo_id']}",
            "date": _iso(r["transaction_date"]), "amount": r["amount"],
            "to_name": r["to_name"], "note": r["note"],
            "venmo_account": r["account_owner"],
        })

    used_c, superseded = set(), 0
    for r in transfers:
        cid = _find_unused(conn, "VENMO CASHOUT", "credit",
                           r["transaction_date"], r["amount"], used_c, 5)
        if cid is None:
            continue
        used_c.add(cid)
        superseded += 1
        rows.append({
            "kind": "supersede", "key": f"supersede:{cid}",
            "date": _iso(r["transaction_date"]), "amount": r["amount"],
            "venmo_account": r["account_owner"], "cashout_txn_id": cid,
        })

    used_o, relabeled = set(), 0
    for r in bank_out:
        tid = _find_unused(conn, "VENMO OUTGOING", "debit",
                           r["transaction_date"], r["amount"], used_o, 3)
        if tid is None:
            continue
        used_o.add(tid)
        relabeled += 1
        rows.append({
            "kind": "relabel", "key": f"relabel:{tid}",
            "date": _iso(r["transaction_date"]), "amount": r["amount"],
            "to_name": r["to_name"], "note": r["note"],
            "venmo_account": r["account_owner"],
        })

    return {
        "totals": {
            "income_rows": len(income), "income_amount": round(inc_amt, 2),
            "expense_rows": len(expense), "expense_amount": round(exp_amt, 2),
            "cashouts_superseded": superseded,
            "outgoing_relabeled": relabeled,
            "unmatched_transfers": len(transfers) - superseded,
        },
        "rows": rows,
    }


def _mark_enriched(cur, venmo_id):
    cur.execute(
        "UPDATE venmo_transactions_raw SET enriched = TRUE, enriched_date = NOW()"
        " WHERE venmo_id = %s",
        (venmo_id,),
    )


def _insert_ingest(cur, r, kind):
    """Insert a balance-affecting Venmo payment as a real transaction and mark
    the staging row enriched. Does not commit."""
    vid8 = hashlib.md5(r["venmo_id"].encode()).hexdigest()[:8]
    account = r["account_owner"] or "?"
    if kind == "income":
        merchant, direction, ttype = "VENMO FROM", "credit", "Venmo Income"
        party, rel = r["from_name"] or "", "from"
        category, subcategory = "Income", "Other"
        srh = f"venmo_in_{vid8}"
    else:
        merchant, direction, ttype = "VENMO TO", "debit", "Venmo Payment"
        party, rel = r["to_name"] or "", "to"
        category, subcategory = None, None  # uncategorized -> review queue
        srh = f"venmo_out_{vid8}"

    desc = f"Venmo (@{account}) {rel} {party}"
    if r["note"]:
        desc += f": {r['note']}"
    desc = desc[:200]
    notes = f"Venmo Account: @{account} | {rel.capitalize()}: {party}"
    if r["note"]:
        notes += f" | Note: {r['note']}"

    cur.execute(
        """
        INSERT INTO transactions (
            account_id, source, source_row_hash, txn_date, post_date,
            description_raw, merchant_raw, merchant_norm, merchant_detail,
            amount, currency, direction, type, is_return,
            category, subcategory, category_source, category_confidence,
            needs_review, notes, created_by
        ) VALUES (
            %s, 'venmo_enrichment', %s, %s, %s, %s, %s, %s, %s, %s,
            'USD', %s, %s, FALSE, %s, %s, 'venmo_expanded', 0.50, TRUE,
            %s, 'venmo_enrichment'
        )
        ON CONFLICT (source_row_hash) DO NOTHING
        """,
        (
            INGEST_ACCOUNT_ID, srh, r["transaction_date"], r["transaction_date"],
            desc, desc[:64], merchant, party[:64], r["amount"], direction, ttype,
            category, subcategory, notes,
        ),
    )
    _mark_enriched(cur, r["venmo_id"])


def commit_venmo_enrichment(conn, keys):
    """
    Apply the selected enrichment `keys` in a single transaction. Recomputes the
    classification + matching, then applies only the selected keys.

    Returns {"income_created","expense_created","cashouts_superseded",
             "outgoing_relabeled","skipped"}.
    """
    selected = set(keys or [])
    income, expense, transfers, bank_out = _classify(_get_unenriched_staging(conn))

    income_by = {f"income:{r['venmo_id']}": r for r in income}
    expense_by = {f"expense:{r['venmo_id']}": r for r in expense}

    used_c, transfer_by = set(), {}
    for r in transfers:
        cid = _find_unused(conn, "VENMO CASHOUT", "credit",
                           r["transaction_date"], r["amount"], used_c, 5)
        if cid is None:
            continue
        used_c.add(cid)
        transfer_by[f"supersede:{cid}"] = (cid, r["venmo_id"])

    used_o, relabel_by = set(), {}
    for r in bank_out:
        tid = _find_unused(conn, "VENMO OUTGOING", "debit",
                           r["transaction_date"], r["amount"], used_o, 3)
        if tid is None:
            continue
        used_o.add(tid)
        relabel_by[f"relabel:{tid}"] = (tid, r)

    res = {"income_created": 0, "expense_created": 0, "cashouts_superseded": 0,
           "outgoing_relabeled": 0, "skipped": 0}
    cur = conn.cursor()
    try:
        for key in selected:
            if key in income_by:
                _insert_ingest(cur, income_by[key], "income")
                res["income_created"] += 1
            elif key in expense_by:
                _insert_ingest(cur, expense_by[key], "expense")
                res["expense_created"] += 1
            elif key in transfer_by:
                cid, vid = transfer_by[key]
                cur.execute(
                    "UPDATE transactions SET exclude_from_budget = TRUE,"
                    " notes = COALESCE(notes, '') || ' [superseded by Venmo enrichment]'"
                    " WHERE txn_id = %s",
                    (cid,),
                )
                _mark_enriched(cur, vid)
                res["cashouts_superseded"] += 1
            elif key in relabel_by:
                tid, r = relabel_by[key]
                account = r["account_owner"] or "?"
                notes = f"Venmo Account: @{account} | To: {r['to_name']}"
                if r["note"]:
                    notes += f" | Note: {r['note']}"
                cur.execute(
                    "UPDATE transactions SET merchant_norm = 'VENMO TO',"
                    " merchant_detail = %s, notes = %s, created_by = 'venmo_enrichment'"
                    " WHERE txn_id = %s",
                    ((r["to_name"] or "")[:64], notes, tid),
                )
                _mark_enriched(cur, r["venmo_id"])
                res["outgoing_relabeled"] += 1
            else:
                res["skipped"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    cur.close()
    return res


def reset_venmo_enrichment(conn, dry_run=False):
    """
    Revert all Venmo enrichment to a clean baseline so it can be re-run from
    scratch. With dry_run=True, reports counts without writing.

    Undoes:
      - ingested VENMO FROM / VENMO TO rows (source = 'venmo_enrichment') -> deleted
      - relabeled bank VENMO OUTGOING (source <> enrichment) -> back to VENMO OUTGOING
      - VENMO CASHOUT soft-supersedes -> exclude_from_budget = FALSE
      - venmo_transactions_raw.enriched flags -> FALSE
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions"
        " WHERE source = 'venmo_enrichment'"
    )
    ingested, ingested_amt = cur.fetchone()
    cur.execute(
        "SELECT COUNT(*) FROM transactions WHERE merchant_norm = 'VENMO TO'"
        " AND source <> 'venmo_enrichment' AND created_by = 'venmo_enrichment'"
    )
    relabeled = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM transactions"
        " WHERE merchant_norm = 'VENMO CASHOUT' AND exclude_from_budget = TRUE"
    )
    superseded = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM venmo_transactions_raw WHERE enriched = TRUE")
    staged = cur.fetchone()[0]

    summary = {
        "ingested_deleted": ingested,
        "ingested_amount": float(ingested_amt),
        "relabels_reverted": relabeled,
        "cashouts_unsuperseded": superseded,
        "staging_reset": staged,
    }
    if dry_run:
        cur.close()
        return summary

    try:
        cur.execute("DELETE FROM transactions WHERE source = 'venmo_enrichment'")
        cur.execute(
            "UPDATE transactions SET merchant_norm = 'VENMO OUTGOING',"
            " merchant_detail = NULL, notes = NULL"
            " WHERE merchant_norm = 'VENMO TO' AND source <> 'venmo_enrichment'"
            " AND created_by = 'venmo_enrichment'"
        )
        cur.execute(
            "UPDATE transactions SET exclude_from_budget = FALSE,"
            " notes = NULLIF(REPLACE(COALESCE(notes, ''),"
            " ' [superseded by Venmo enrichment]', ''), '')"
            " WHERE merchant_norm = 'VENMO CASHOUT' AND exclude_from_budget = TRUE"
        )
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


def main():
    """Dev CLI: preview the plan, or --commit-all to apply everything."""
    parser = argparse.ArgumentParser(description="Venmo enrichment (funding-source)")
    parser.add_argument("--commit-all", action="store_true", help="Apply the whole plan")
    parser.add_argument("--reset", action="store_true", help="Reset enrichment")
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        if args.reset:
            print(reset_venmo_enrichment(conn))
            return 0
        plan = build_venmo_enrichment_plan(conn)
        print("Totals:", plan["totals"])
        for r in plan["rows"]:
            print(" ", r["kind"], r["key"], r.get("amount"))
        if args.commit_all:
            res = commit_venmo_enrichment(conn, [r["key"] for r in plan["rows"]])
            print("Committed:", res)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    exit(main())
