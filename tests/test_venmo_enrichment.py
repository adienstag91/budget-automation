"""
Tests for Venmo enrichment plan building — classification and unmatched
flagging. DB access is stubbed out (staging fetch + bank-txn matching), so
these run without a database.
"""
from datetime import date

import budget_automation.core.venmo_enrichment as ve


def _staging_row(**overrides):
    row = {
        "venmo_id": "vid1",
        "transaction_date": date(2026, 1, 20),
        "transaction_type": "Payment",
        "amount": 300.0,
        "direction": "debit",
        "from_name": "",
        "to_name": "John Smith",
        "note": "rent",
        "account_owner": "andrew",
        "funding_source": "Chase Checking",
        "destination": "",
    }
    row.update(overrides)
    return row


def test_classify_buckets():
    income = _staging_row(venmo_id="a", direction="credit",
                          destination=ve.VENMO_BALANCE, funding_source="")
    expense = _staging_row(venmo_id="b", funding_source=ve.VENMO_BALANCE)
    transfer = _staging_row(venmo_id="c", transaction_type="Standard Transfer")
    bank_funded = _staging_row(venmo_id="d")
    # Instant-to-bank credit: already on the bank statement, ignored entirely.
    instant = _staging_row(venmo_id="e", direction="credit", destination="Chase")

    inc, exp, transfers, bank_out = ve._classify(
        [income, expense, transfer, bank_funded, instant]
    )
    assert [r["venmo_id"] for r in inc] == ["a"]
    assert [r["venmo_id"] for r in exp] == ["b"]
    assert [r["venmo_id"] for r in transfers] == ["c"]
    assert [r["venmo_id"] for r in bank_out] == ["d"]


def test_plan_flags_unmatched_outgoing(monkeypatch):
    """A bank-funded debit with no VENMO OUTGOING match must surface as an
    'unmatched' row with a reason — not silently disappear from the plan."""
    staged = [_staging_row()]
    monkeypatch.setattr(ve, "_get_unenriched_staging", lambda conn: staged)
    monkeypatch.setattr(ve, "_find_unused", lambda *a, **k: None)
    monkeypatch.setattr(
        ve, "_diagnose_unmatched",
        lambda *a, **k: "nearest same-amount bank txn is 4 days away",
    )

    plan = ve.build_venmo_enrichment_plan(conn=None)

    assert plan["totals"]["unmatched_outgoing"] == 1
    assert plan["totals"]["outgoing_relabeled"] == 0
    unmatched = [r for r in plan["rows"] if r["kind"] == "unmatched"]
    assert len(unmatched) == 1
    row = unmatched[0]
    assert row["target"] == "outgoing"
    assert row["key"] == "unmatched:vid1"
    assert row["amount"] == 300.0
    assert row["to_name"] == "John Smith"
    assert "4 days away" in row["reason"]


def test_plan_flags_unmatched_transfer(monkeypatch):
    staged = [_staging_row(transaction_type="Standard Transfer")]
    monkeypatch.setattr(ve, "_get_unenriched_staging", lambda conn: staged)
    monkeypatch.setattr(ve, "_find_unused", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_diagnose_unmatched",
                        lambda *a, **k: "no bank VENMO CASHOUT of this amount found")

    plan = ve.build_venmo_enrichment_plan(conn=None)

    assert plan["totals"]["unmatched_transfers"] == 1
    unmatched = [r for r in plan["rows"] if r["kind"] == "unmatched"]
    assert len(unmatched) == 1
    assert unmatched[0]["target"] == "cashout"


def test_plan_matched_outgoing_has_no_unmatched(monkeypatch):
    staged = [_staging_row()]
    monkeypatch.setattr(ve, "_get_unenriched_staging", lambda conn: staged)
    monkeypatch.setattr(ve, "_find_unused", lambda *a, **k: 42)

    plan = ve.build_venmo_enrichment_plan(conn=None)

    assert plan["totals"]["outgoing_relabeled"] == 1
    assert plan["totals"]["unmatched_outgoing"] == 0
    kinds = [r["kind"] for r in plan["rows"]]
    assert kinds == ["relabel"]
    assert plan["rows"][0]["key"] == "relabel:42"


def test_outgoing_window_matches_cashout_window():
    """Posting lag over a holiday weekend (e.g. MLK day) can put the bank debit
    4+ days after the Venmo payment date; the old ±3-day outgoing window
    silently missed those."""
    assert ve.OUTGOING_WINDOW_DAYS == 5
    assert ve.CASHOUT_WINDOW_DAYS == 5


def test_unmatched_reason_no_candidates():
    class FakeCursor:
        description = []

        def execute(self, *a):
            pass

        def fetchall(self):
            return []

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    reason = ve._diagnose_unmatched(
        FakeConn(), "VENMO OUTGOING", "debit", date(2026, 1, 20), 300.0,
        set(), 5,
    )
    assert "no bank VENMO OUTGOING of this amount" in reason


def test_unmatched_reason_outside_window():
    class FakeCursor:
        def execute(self, *a):
            pass

        def fetchall(self):
            # Nearest same-amount txn posted 4 days after the Venmo date.
            return [(7, date(2026, 1, 24))]

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    reason = ve._diagnose_unmatched(
        FakeConn(), "VENMO OUTGOING", "debit", date(2026, 1, 20), 300.0,
        set(), 5,
    )
    assert "4 days away" in reason
    assert "±5-day" in reason


def test_unmatched_reason_all_claimed():
    class FakeCursor:
        def execute(self, *a):
            pass

        def fetchall(self):
            return [(7, date(2026, 1, 20))]

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    reason = ve._diagnose_unmatched(
        FakeConn(), "VENMO OUTGOING", "debit", date(2026, 1, 20), 300.0,
        {7}, 5,
    )
    assert "already matched" in reason
