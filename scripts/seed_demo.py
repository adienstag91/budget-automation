#!/usr/bin/env python3
"""
Seed the database with synthetic demo data.

This powers the public demo and local-dev / Claude-Code-on-the-web sessions:
realistic-looking spending that is entirely fake, so the app can be shown off
(and developed against) without exposing any real finances.

Run AFTER `budget-init` (it needs the taxonomy + accounts in place):

    APP_MODE=demo python -m scripts.seed_demo

Safety: this DELETES all rows in `transactions` before inserting synthetic
ones, so it refuses to run unless APP_MODE=demo (or --force is passed). That
makes it impossible to wipe the real production DB by accident — production
runs with APP_MODE=real.
"""
import argparse
import hashlib
import os
import random
import sys
from datetime import date, timedelta

from budget_automation.utils.db_connection import get_db_connection

# Deterministic output so the demo looks the same on every reseed.
SEED = 42
MONTHS = 14            # how many months of history to generate
TXNS_PER_MONTH = (45, 70)

# Merchant pools keyed by a coarse "kind". Categories are matched to a kind by
# keyword (see kind_for_category), so this works regardless of the exact
# taxonomy names in the DB. Each entry: (description_raw, merchant_norm, lo, hi).
MERCHANT_KINDS = {
    "groceries": [
        ("WHOLE FOODS MKT", "WHOLE FOODS", 25, 180),
        ("TRADER JOE'S", "TRADER JOES", 20, 120),
        ("SAFEWAY #1423", "SAFEWAY", 15, 140),
        ("COSTCO WHSE", "COSTCO", 60, 320),
    ],
    "dining": [
        ("SQ *BREADS BAKERY", "SQ", 6, 40),
        ("TST* THE LOCAL DINER", "TST", 18, 90),
        ("CHIPOTLE 1180", "CHIPOTLE", 9, 35),
        ("STARBUCKS STORE 227", "STARBUCKS", 4, 18),
        ("DOORDASH*RAMEN HOUSE", "DOORDASH", 20, 65),
    ],
    "shopping": [
        ("AMZN Mktp US*A12B3", "AMAZON", 8, 220),
        ("TARGET 00012345", "TARGET", 12, 160),
        ("BEST BUY #482", "BEST BUY", 25, 600),
    ],
    "transport": [
        ("MTA*NYCT PAYGO", "MTA SUBWAY", 2, 35),
        ("UBER *TRIP", "UBER", 8, 55),
        ("SHELL OIL 5742", "SHELL", 30, 85),
        ("EXXONMOBIL 99231", "EXXON", 30, 90),
    ],
    "utilities": [
        ("CON EDISON UTILITY", "CON EDISON", 60, 240),
        ("VERIZON WIRELESS", "VERIZON", 70, 160),
        ("SPECTRUM INTERNET", "SPECTRUM", 50, 110),
    ],
    "entertainment": [
        ("NETFLIX.COM", "NETFLIX", 15, 23),
        ("SPOTIFY USA", "SPOTIFY", 11, 17),
        ("AMC ONLINE 6042", "AMC", 14, 60),
    ],
    "health": [
        ("CVS/PHARMACY #04102", "CVS", 8, 90),
        ("SQ *EQUINOX", "SQ", 40, 220),
    ],
    "income": [
        ("DIRECT DEP PAYROLL ACME CORP", "ACME PAYROLL", 2800, 3600),
        ("ZELLE TRANSFER CONF# 1842", "ZELLE FROM", 40, 400),
    ],
    "generic": [
        ("SQ *MISC VENDOR", "SQ", 10, 120),
        ("PAYPAL *MERCHANT", "PAYPAL", 10, 200),
    ],
}

KEYWORDS = [
    ("groceries", ("grocer", "food", "supermarket")),
    ("dining", ("dining", "restaurant", "coffee", "drink", "bar", "takeout")),
    ("shopping", ("shop", "amazon", "cloth", "merch", "home", "electronic")),
    ("transport", ("transport", "gas", "fuel", "auto", "transit", "subway", "car", "ride")),
    ("utilities", ("utilit", "phone", "internet", "electric", "cable", "bill")),
    ("entertainment", ("entertain", "stream", "movie", "music", "subscription")),
    ("health", ("health", "medical", "pharmac", "fitness", "gym", "doctor")),
]


def kind_for_category(category: str, is_income: bool) -> str:
    if is_income:
        return "income"
    name = category.lower()
    for kind, words in KEYWORDS:
        if any(w in name for w in words):
            return kind
    return "generic"


def row_hash(txn_date: date, description: str, amount: float, account_id: int) -> str:
    raw = f"{txn_date.isoformat()}|{description}|{amount:.2f}|{account_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def fetch_taxonomy(cur):
    cur.execute("SELECT category, is_income FROM taxonomy_categories ORDER BY category")
    cats = cur.fetchall()
    cur.execute("SELECT category, subcategory FROM taxonomy_subcategories")
    subs: dict[str, list[str]] = {}
    for category, subcategory in cur.fetchall():
        subs.setdefault(category, []).append(subcategory)
    return cats, subs


def ensure_accounts(cur):
    cur.execute("SELECT account_id, account_type FROM accounts ORDER BY account_id")
    rows = cur.fetchall()
    if rows:
        return rows
    cur.executemany(
        "INSERT INTO accounts (account_name, account_type, institution, is_active)"
        " VALUES (%s, %s, %s, %s)",
        [
            ("Chase Checking", "checking", "Chase", True),
            ("Chase Sapphire Credit", "credit", "Chase", True),
        ],
    )
    cur.execute("SELECT account_id, account_type FROM accounts ORDER BY account_id")
    return cur.fetchall()


def generate(cats, subs, accounts, rng):
    """Yield transaction dicts spanning the last MONTHS months."""
    income_cats = [c for c, is_income in cats if is_income]
    expense_cats = [c for c, is_income in cats if not is_income]
    if not expense_cats:  # taxonomy with only income? fall back to all
        expense_cats = [c for c, _ in cats]

    credit_acct = next((a for a, t in accounts if t == "credit"), accounts[0][0])
    checking_acct = next((a for a, t in accounts if t == "checking"), accounts[0][0])

    today = date.today()
    first = today.replace(day=1)
    for m in range(MONTHS):
        # Walk backwards month by month.
        year = first.year
        month = first.month - m
        while month <= 0:
            month += 12
            year -= 1
        month_start = date(year, month, 1)

        # One or two paychecks per month (income).
        for c in income_cats[:1] or [None]:
            if c is None:
                break
            for payday in (1, 15):
                desc, norm, lo, hi = MERCHANT_KINDS["income"][0]
                amount = round(rng.uniform(lo, hi), 2)
                yield dict(
                    account_id=checking_acct, source="manual",
                    txn_date=month_start.replace(day=payday),
                    description=desc, merchant_norm=norm, amount=amount,
                    direction="credit", category=c,
                    subcategory=(subs.get(c) or [None])[0],
                )

        n = rng.randint(*TXNS_PER_MONTH)
        for _ in range(n):
            category = rng.choice(expense_cats)
            is_income = False
            kind = kind_for_category(category, is_income)
            desc, norm, lo, hi = rng.choice(MERCHANT_KINDS.get(kind, MERCHANT_KINDS["generic"]))
            amount = round(rng.uniform(lo, hi), 2)
            day = rng.randint(1, 28)
            sub_list = subs.get(category) or [None]
            yield dict(
                account_id=credit_acct, source="manual",
                txn_date=month_start.replace(day=day),
                description=desc, merchant_norm=norm, amount=amount,
                direction="debit", category=category,
                subcategory=rng.choice(sub_list),
            )


def main():
    parser = argparse.ArgumentParser(description="Seed synthetic demo data.")
    parser.add_argument("--force", action="store_true",
                        help="seed even when APP_MODE is not 'demo' (use with care)")
    args = parser.parse_args()

    if os.getenv("APP_MODE") != "demo" and not args.force:
        print("Refusing to seed: APP_MODE is not 'demo'.")
        print("This DELETES all transactions. Set APP_MODE=demo, or pass --force "
              "if you really mean to seed this database.")
        sys.exit(1)

    rng = random.Random(SEED)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cats, subs = fetch_taxonomy(cur)
        if not cats:
            print("No taxonomy found. Run `budget-init` first.")
            sys.exit(1)
        accounts = ensure_accounts(cur)

        cur.execute("DELETE FROM transactions")

        rows = list(generate(cats, subs, accounts, rng))
        inserted = 0
        for r in rows:
            needs_review = rng.random() < 0.06  # a few land in the review queue
            conf = round(rng.uniform(0.90, 1.0), 2)
            h = row_hash(r["txn_date"], r["description"], r["amount"], r["account_id"])
            cur.execute(
                """
                INSERT INTO transactions
                    (account_id, source, source_row_hash, txn_date, post_date,
                     description_raw, merchant_raw, merchant_norm, amount,
                     direction, type, category, subcategory, category_source,
                     category_confidence, needs_review)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_row_hash) DO NOTHING
                """,
                (
                    r["account_id"], r["source"], h, r["txn_date"], r["txn_date"],
                    r["description"], None, r["merchant_norm"], r["amount"],
                    r["direction"], "Sale", r["category"], r["subcategory"],
                    "rule", conf, needs_review,
                ),
            )
            inserted += cur.rowcount

        conn.commit()
        print(f"✅ Seeded {inserted} synthetic transactions across {MONTHS} months "
              f"({len(cats)} categories, {len(accounts)} accounts).")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
