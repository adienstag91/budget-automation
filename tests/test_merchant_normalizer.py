"""
Tests for merchant normalization, focused on the Chase ACH-detail description
format ("ORIG CO NAME:... CO ENTRY DESCR:...") that leaks through unnormalized
and breaks Venmo enrichment matching. DB-free.
"""
from budget_automation.core.merchant_normalizer import normalize_merchant


def test_ach_venmo_cashout():
    raw = "ORIG CO NAME:VENMO CO ENTRY DESCR:CASHOUT SEC:PPD ORIG ID:5264681992"
    assert normalize_merchant(raw) == ("VENMO CASHOUT", None)


def test_ach_venmo_payment_is_outgoing():
    raw = "ORIG CO NAME:VENMO CO ENTRY DESCR:PAYMENT SEC:PPD ORIG ID:5264681992"
    assert normalize_merchant(raw) == ("VENMO OUTGOING", None)


def test_ach_general_biller_lipa():
    raw = ("ORIG CO NAME:LIPA CO ENTRY DESCR:ONLINE PAY SEC:WEB "
           "IND ID:0583802735 ORIG ID:1563585001")
    assert normalize_merchant(raw) == ("LIPA", None)


def test_ach_strips_corporate_suffix():
    raw = ("ORIG CO NAME:OLLIE PETS INC CO ENTRY DESCR:G76KGZU75A "
           "SEC:PPD ORIG ID:9186939000")
    assert normalize_merchant(raw) == ("OLLIE PETS", None)


def test_ach_lowercase_input_still_matches():
    # Descriptions are upper-cased internally, so mixed case must still work.
    raw = "orig co name:venmo co entry descr:cashout sec:ppd orig id:5264681992"
    assert normalize_merchant(raw) == ("VENMO CASHOUT", None)


def test_old_venmo_format_still_normalizes():
    # The legacy space-padded format must keep working alongside the new one.
    assert normalize_merchant(
        "VENMO            CASHOUT                    PPD ID: 5264681992"
    ) == ("VENMO CASHOUT", None)
    assert normalize_merchant(
        "VENMO            PAYMENT    1047273886351   WEB ID: 3264681992"
    ) == ("VENMO OUTGOING", None)


def test_non_ach_description_unaffected():
    # A normal description without the ACH markers is untouched by the new path.
    assert normalize_merchant("SQ *BREADS BAKERY") == ("SQ", "BREADS BAKERY")
