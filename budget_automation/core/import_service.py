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


def weak_key(txn_date, amount, account_id, direction) -> str:
    """
    A looser dedup key than content_key: date + amount + account + direction,
    IGNORING the description. Two rows share a weak key when they're the same
    money movement on the same day/account/direction even if the bank worded the
    description differently across exports. Used to catch re-import duplicates
    that slip past the description-sensitive hash — e.g. Chase re-exporting
    "ORIG CO NAME:LIPA ..." as "LIPA ONLINE PAY WEB ID: ...".
    """
    amt = f"{float(amount):.2f}"
    return f"{txn_date}|{amt}|{account_id}|{direction}"


def existing_weak_keys(conn, account_ids: List[int]) -> Dict[str, int]:
    """weak_key -> count of existing transactions on the given accounts."""
    if not account_ids:
        return {}
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT txn_date, amount, account_id, direction, COUNT(*)
        FROM transactions
        WHERE account_id = ANY(%s)
        GROUP BY txn_date, amount, account_id, direction
        """,
        (list(account_ids),),
    )
    counts: Dict[str, int] = {}
    for txn_date, amount, account_id, direction, cnt in cursor.fetchall():
        counts[weak_key(txn_date, amount, account_id, direction)] = cnt
    cursor.close()
    return counts


def flag_duplicates(txn_dicts, stored_hashes, db_content_counts, db_weak_counts):
    """
    Classify each parsed row as an exact duplicate, a *possible* duplicate, or
    new. Pure function over precomputed DB maps, so it's unit-testable with no DB.

    - **exact** (`is_duplicate`): hash already stored, or the DB already holds at
      least as many rows with this exact content key as this row's occurrence
      (handles identical same-day repeats and old-style hashes).
    - **possible** (`possible_duplicate`): NOT an exact match, but an existing
      transaction shares this row's weak key (date + amount + account +
      direction) and wasn't already claimed by an exact match — i.e. the same
      charge the bank reworded across exports (LIPA/OLLIE/Venmo). Surfaced, not
      auto-dropped: legitimate same-day repeats keep identical descriptions so
      they match exactly and never reach this branch; the false-positive case
      (two genuinely different charges sharing date/amount/account/direction) is
      rare and recoverable — the user just re-checks the row.

    Returns a list (input order) of {"is_duplicate": bool,
    "possible_duplicate": bool}.
    """
    seen_content: Dict[str, int] = {}
    weak_consumed: Dict[str, int] = {}
    out = []
    for t in txn_dicts:
        ck = content_key(
            t["txn_date"], t["description_raw"], t["amount"], t["account_id"]
        )
        seen_content[ck] = seen_content.get(ck, 0) + 1
        occ = seen_content[ck]

        is_dup = (
            t["source_row_hash"] in stored_hashes
            or db_content_counts.get(ck, 0) >= occ
        )

        wk = weak_key(t["txn_date"], t["amount"], t["account_id"], t["direction"])
        used = weak_consumed.get(wk, 0)
        possible = False
        if not is_dup and used < db_weak_counts.get(wk, 0):
            # An existing row shares this weak key but no exact match claimed it,
            # so it's very likely the same charge reworded by the bank.
            possible = True
        # Both exact and possible dups consume a weak slot, so exact matches are
        # never re-counted as possibles and vice-versa.
        weak_consumed[wk] = used + 1

        out.append({"is_duplicate": is_dup, "possible_duplicate": possible})
    return out


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
