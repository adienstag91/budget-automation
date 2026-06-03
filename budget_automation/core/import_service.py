"""
Shared import service used by both the CLI (`budget-import`) and the web API
(`/api/import/*`).

Responsibilities:
  - Load the taxonomy from the DB (authoritative source) in the LLM-expected shape.
  - Categorize parsed CSV rows (rules -> LLM fallback -> needs-review) and return
    fully-built transaction dicts ready for insertion.
  - Detect which parsed rows are already in the DB (duplicate detection), robust to
    the dedup-hash scheme change (old rows carry old-style hashes).
  - Insert transaction dicts with UNIQUE(source_row_hash) as the backstop.

The categorization and insert logic used to live inline in `cli/import_csv.py`.
It now lives here so the API can reuse the exact same pipeline.
"""
import os
from typing import Dict, List, Optional, Tuple

from .categorization_orchestrator import (
    CategorizationOrchestrator,
    Transaction,
    load_rules_from_db,
)
from .taxonomy_db import load_taxonomy_from_db


# Columns written by an import. Kept in one place so the INSERT and the dict
# builder can't drift apart.
def _build_txn_dict(txn: Transaction, orig: Dict) -> Dict:
    """Merge a categorized Transaction with its original parsed row into the
    dict shape the INSERT expects."""
    return {
        "account_id": txn.account_id,
        "source": txn.source,
        "source_row_hash": orig["source_row_hash"],
        "txn_date": txn.txn_date,
        "post_date": txn.post_date,
        "description_raw": txn.description_raw,
        "merchant_raw": orig["merchant_raw"],
        "merchant_norm": txn.merchant_norm,
        "merchant_detail": txn.merchant_detail,
        "amount": txn.amount,
        "currency": orig.get("currency", "USD"),
        "direction": txn.direction,
        "type": txn.type,
        "is_return": txn.is_return,
        "category": txn.category,
        "subcategory": txn.subcategory,
        "category_source": txn.category_source,
        "category_confidence": txn.category_confidence,
        "needs_review": txn.needs_review,
        "notes": txn.notes,
        "memo": orig.get("memo"),
        "created_by": "import",
    }


def categorize_parsed(
    conn,
    parsed_txns: List[Dict],
    enable_llm: bool,
    review_threshold: Optional[float] = None,
) -> Tuple[List[Dict], Dict]:
    """
    Categorize a list of parsed CSV rows (output of parse_chase_csv).

    Args:
        conn: open DB connection (for rules + taxonomy)
        parsed_txns: list of parsed row dicts (must include source_row_hash,
            merchant_raw, currency, memo, plus the normalizer/amount fields)
        enable_llm: run the LLM fallback on un-ruled merchants
        review_threshold: confidence floor below which an LLM result is flagged
            for review (defaults to REVIEW_THRESHOLD env, then 0.80)

    Returns:
        (txn_dicts, stats) where txn_dicts are insert-ready dicts (one per parsed
        row, same order) and stats is the orchestrator's stats dict.
    """
    if review_threshold is None:
        review_threshold = float(os.getenv("REVIEW_THRESHOLD", "0.80"))

    taxonomy = load_taxonomy_from_db(conn)
    rules = load_rules_from_db(conn)

    orchestrator = CategorizationOrchestrator(
        taxonomy=taxonomy,
        rules=rules,
        review_threshold=review_threshold,
        enable_llm=enable_llm,
    )

    # Build Transaction objects, keeping a map from each object's identity to its
    # original parsed row. categorize_batch mutates these same objects in place
    # (it only reorders the list, never copies), so identity pairing is exact and
    # avoids any ambiguity between genuinely-identical same-day repeat charges.
    transactions = []
    orig_by_id: Dict[int, Dict] = {}
    for row in parsed_txns:
        txn = Transaction(
            txn_id=None,
            merchant_norm=row["merchant_norm"],
            merchant_detail=row.get("merchant_detail"),
            description_raw=row["description_raw"],
            amount=float(row["amount"]),
            direction=row["direction"],
            txn_date=row["txn_date"],
            post_date=row["post_date"],
            account_id=row["account_id"],
            source=row["source"],
            type=row["type"],
            is_return=row["is_return"],
        )
        orig_by_id[id(txn)] = row
        transactions.append(txn)

    categorized = orchestrator.categorize_batch(transactions)

    txn_dicts = [_build_txn_dict(txn, orig_by_id[id(txn)]) for txn in categorized]
    return txn_dicts, orchestrator.stats


def existing_hashes_for(conn, hashes: List[str]) -> set:
    """Return the subset of `hashes` already present in transactions."""
    if not hashes:
        return set()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT source_row_hash FROM transactions WHERE source_row_hash = ANY(%s)",
        (list(hashes),),
    )
    found = {r[0] for r in cursor.fetchall()}
    cursor.close()
    return found


def content_key(txn_date, description_raw, amount, account_id) -> str:
    """
    Build the dedup content key, normalizing the amount to a fixed 2-decimal
    string so DB Decimal ("35.00") and parsed/float ("35.0") forms compare equal.
    Used by both the DB-side count and the preview-side occurrence numbering so
    they agree exactly.
    """
    amt = f"{float(amount):.2f}"
    return f"{txn_date}|{description_raw}|{amt}|{account_id}"


def existing_content_keys(conn, account_ids: List[int]) -> Dict[str, int]:
    """
    Build a content-key -> count map for transactions already in the DB on the
    given accounts.

    The count lets the preview decide how many occurrences of a repeated charge
    already exist, so a re-import of the same statement is recognized as
    duplicate even when the stored hash is the old-style (pre-fix) hash.
    """
    if not account_ids:
        return {}
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT txn_date, description_raw, amount, account_id, COUNT(*)
        FROM transactions
        WHERE account_id = ANY(%s)
        GROUP BY txn_date, description_raw, amount, account_id
        """,
        (list(account_ids),),
    )
    counts: Dict[str, int] = {}
    for txn_date, description_raw, amount, account_id, cnt in cursor.fetchall():
        key = content_key(txn_date, description_raw, amount, account_id)
        counts[key] = cnt
    cursor.close()
    return counts


def insert_transactions(conn, transactions: List[Dict]) -> Tuple[int, int, int]:
    """
    Insert transaction dicts into the DB, deduplicating on the UNIQUE
    source_row_hash. Commits per row (matches the prior CLI behavior so a single
    bad row never rolls back a whole import).

    Returns: (inserted, duplicates, errors)
    """
    cursor = conn.cursor()
    inserted = 0
    duplicates = 0
    errors = 0

    for txn in transactions:
        try:
            cursor.execute(
                """
                INSERT INTO transactions (
                    account_id, source, source_row_hash,
                    txn_date, post_date,
                    description_raw, merchant_raw, merchant_norm, merchant_detail,
                    amount, currency, direction, type, is_return,
                    category, subcategory,
                    category_source, category_confidence, needs_review,
                    notes, memo, created_by
                )
                VALUES (
                    %(account_id)s, %(source)s, %(source_row_hash)s,
                    %(txn_date)s, %(post_date)s,
                    %(description_raw)s, %(merchant_raw)s, %(merchant_norm)s, %(merchant_detail)s,
                    %(amount)s, %(currency)s, %(direction)s, %(type)s, %(is_return)s,
                    %(category)s, %(subcategory)s,
                    %(category_source)s, %(category_confidence)s, %(needs_review)s,
                    %(notes)s, %(memo)s, %(created_by)s
                )
                """,
                txn,
            )
            conn.commit()
            inserted += 1
        except Exception as e:
            conn.rollback()
            msg = str(e).lower()
            if "duplicate key" in msg or "unique" in msg:
                duplicates += 1
            else:
                errors += 1
    cursor.close()
    return inserted, duplicates, errors
