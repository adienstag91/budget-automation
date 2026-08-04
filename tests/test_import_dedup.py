"""
Tests for import duplicate flagging — the exact/possible/new classification that
catches re-import duplicates the bank reworded (e.g. Chase re-exporting
"ORIG CO NAME:LIPA ..." as "LIPA ONLINE PAY WEB ID: ..."). DB-free: exercises
the pure flag_duplicates() over hand-built count maps.
"""
from datetime import date

from budget_automation.core.import_service import (
    content_key,
    weak_key,
    flag_duplicates,
)

D = date(2026, 7, 1)


def _row(desc, amount, hash_, direction="debit", account_id=1, txn_date=D):
    return {
        "txn_date": txn_date,
        "description_raw": desc,
        "amount": amount,
        "account_id": account_id,
        "direction": direction,
        "source_row_hash": hash_,
    }


def test_exact_hash_duplicate():
    rows = [_row("LIPA", 368.41, "h1")]
    flags = flag_duplicates(rows, {"h1"}, {}, {})
    assert flags == [{"is_duplicate": True, "possible_duplicate": False}]


def test_content_key_occurrence_duplicate():
    # Old-hash-scheme row: hash not stored, but content key already present.
    rows = [_row("SUBWAY", 2.90, "hx")]
    db_content = {content_key(D, "SUBWAY", 2.90, 1): 1}
    db_weak = {weak_key(D, 2.90, 1, "debit"): 1}
    flags = flag_duplicates(rows, set(), db_content, db_weak)
    assert flags[0]["is_duplicate"] is True
    assert flags[0]["possible_duplicate"] is False


def test_possible_duplicate_reworded_description():
    # DB holds the same charge under a different description (LIPA case).
    db_content = {content_key(D, "ORIG CO NAME:LIPA ...", 368.41, 1): 1}
    db_weak = {weak_key(D, 368.41, 1, "debit"): 1}
    rows = [_row("LIPA ONLINE PAY WEB ID:", 368.41, "hnew")]
    flags = flag_duplicates(rows, set(), db_content, db_weak)
    assert flags[0]["is_duplicate"] is False
    assert flags[0]["possible_duplicate"] is True


def test_legit_same_day_repeat_first_import_not_flagged():
    # Two identical subway trips, nothing in the DB yet -> both new, no flags.
    rows = [_row("SUBWAY", 2.90, "h1"), _row("SUBWAY", 2.90, "h2")]
    flags = flag_duplicates(rows, set(), {}, {})
    assert flags == [
        {"is_duplicate": False, "possible_duplicate": False},
        {"is_duplicate": False, "possible_duplicate": False},
    ]


def test_charge_and_credit_pair_not_flagged():
    # A $40.79 debit (Uber) exists; the matching $40.79 travel *credit* must not
    # be flagged — different direction, so a different weak key.
    db_content = {content_key(D, "UBER", 40.79, 2): 1}
    db_weak = {weak_key(D, 40.79, 2, "debit"): 1}
    rows = [_row("TRAVEL CREDIT", 40.79, "hc", direction="credit", account_id=2)]
    flags = flag_duplicates(rows, set(), db_content, db_weak)
    assert flags[0]["is_duplicate"] is False
    assert flags[0]["possible_duplicate"] is False


def test_new_beyond_weak_capacity_not_flagged():
    # DB has one row for this weak key. Two non-exact incoming rows share it:
    # the first claims the slot (possible dup), the second is genuinely new.
    db_content = {content_key(D, "A", 50.0, 1): 1}
    db_weak = {weak_key(D, 50.0, 1, "debit"): 1}
    rows = [_row("B", 50.0, "hb"), _row("C", 50.0, "hc")]
    flags = flag_duplicates(rows, set(), db_content, db_weak)
    assert flags[0]["possible_duplicate"] is True
    assert flags[1]["possible_duplicate"] is False
    assert flags[1]["is_duplicate"] is False


def test_exact_match_consumes_weak_slot_before_possible():
    # DB has one "SUB" row. Incoming: the exact same "SUB" plus a reworded
    # "SUBWAY". The exact match claims the only slot, so the reworded row is new
    # (not a possible dup) — the DB genuinely holds just one.
    db_content = {content_key(D, "SUB", 2.90, 1): 1}
    db_weak = {weak_key(D, 2.90, 1, "debit"): 1}
    rows = [_row("SUB", 2.90, "h1"), _row("SUBWAY", 2.90, "h2")]
    flags = flag_duplicates(rows, set(), db_content, db_weak)
    assert flags[0]["is_duplicate"] is True
    assert flags[1]["is_duplicate"] is False
    assert flags[1]["possible_duplicate"] is False
