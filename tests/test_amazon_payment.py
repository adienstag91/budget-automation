"""
Tests for Amazon payment-source labeling helpers.

These cover the pure functions that derive a transaction's payment source from
Amazon's own "Payment Instrument Type" (preferred) and the card-match fallback.
They're DB-free, so they run without a database or API key.
"""
from budget_automation.core.amazon_enrichment import (
    classify_payment_instrument,
    derive_payment_source,
    build_payment_note,
)


def test_classify_gift_card():
    assert classify_payment_instrument("Amazon Gift Card") == ("gift_card", "Amazon Gift Card")
    assert classify_payment_instrument("Gift Card Balance") == ("gift_card", "Gift Card Balance")


def test_classify_card():
    assert classify_payment_instrument("Visa - 1234") == ("card", "Visa - 1234")
    assert classify_payment_instrument("MasterCard") == ("card", "MasterCard")


def test_classify_blank_is_unknown():
    assert classify_payment_instrument("") == ("unknown", None)
    assert classify_payment_instrument("   ") == ("unknown", None)
    assert classify_payment_instrument(None) == ("unknown", None)


def test_derive_prefers_amazon_instrument_over_match():
    # Amazon says gift card — that wins even if (unusually) a card charge matched.
    order = {"payment_instrument": "Amazon Gift Card"}
    assert derive_payment_source(order, {"txn_id": 1}) == ("gift_card", "Amazon Gift Card")


def test_derive_card_instrument():
    order = {"payment_instrument": "Visa - 1234"}
    assert derive_payment_source(order, None) == ("credit_card", "Visa - 1234")


def test_derive_falls_back_to_match_when_amazon_blank():
    order = {"payment_instrument": None}
    assert derive_payment_source(order, {"txn_id": 5}) == ("credit_card", None)
    assert derive_payment_source(order, None) == ("unknown", None)


def test_payment_note_variants():
    order = {"order_id": "111-222"}
    item = {"asin": "B0TEST", "quantity": 2}

    assert build_payment_note(order, item, "gift_card", "Amazon Gift Card", None) == (
        "Order: 111-222 | ASIN: B0TEST | Qty: 2 | Paid via Amazon Gift Card"
    )
    # Card per Amazon, but no matching bank charge found — note flags that.
    assert build_payment_note(order, item, "credit_card", "Visa - 1234", None) == (
        "Order: 111-222 | ASIN: B0TEST | Qty: 2 | Paid via Visa - 1234 (no matching card charge found)"
    )
    # Matched card charge, Amazon gave no instrument label.
    assert build_payment_note(order, item, "credit_card", None, {"txn_id": 5}) == (
        "Order: 111-222 | ASIN: B0TEST | Qty: 2 | Paid via credit card"
    )
    assert build_payment_note(order, item, "unknown", None, None) == (
        "Order: 111-222 | ASIN: B0TEST | Qty: 2 | Payment method unknown"
    )
