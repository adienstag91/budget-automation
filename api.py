"""
FastAPI Backend for Budget Pivot Table

This exposes your PostgreSQL data as REST API endpoints that 
your Lovable frontend can consume.

Run with: uvicorn api:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, Query, Body, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, date
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
import os
import tempfile

# Load .env so the API process has ANTHROPIC_API_KEY (LLM categorization) and
# DB_* regardless of how uvicorn was launched. Without this, LLMCategorizer
# silently disables and imports categorize 0 transactions via the LLM.
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Budget Pivot API", version="1.0.0")

# Enable CORS for your frontend (Lovable will need this)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your Lovable domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5433),
        database=os.getenv("DB_NAME", "budget_db"),
        user=os.getenv("DB_USER", "budget_user"),
        password=os.getenv("DB_PASSWORD", "budget_password_local_dev")
    )


# Response models
class MonthData(BaseModel):
    month: str
    amount: float
    transaction_count: int


class SubcategoryData(BaseModel):
    subcategory: str
    monthly_data: dict[str, float]  # month -> amount
    total: float


class CategoryData(BaseModel):
    category: str
    monthly_data: dict[str, float]  # month -> amount
    total: float
    subcategories: Optional[List[SubcategoryData]] = None


class TransactionData(BaseModel):
    txn_id: int
    txn_date: str
    merchant_norm: str
    merchant_detail: Optional[str]
    description_raw: str
    amount: float
    category: str
    subcategory: str
    notes: Optional[str]


class PivotResponse(BaseModel):
    months: List[str]  # Ordered list of months (oldest to newest)
    categories: List[CategoryData]
    grand_totals: dict[str, float]  # month -> total


# ===== Taxonomy management request bodies =====
class CategoryCreate(BaseModel):
    category: str
    is_income: bool = False
    is_transfer: bool = False


class CategoryUpdate(BaseModel):
    new_category: Optional[str] = None
    is_income: Optional[bool] = None
    is_transfer: Optional[bool] = None
    display_order: Optional[int] = None


class CategoryMerge(BaseModel):
    into: str


class SubcategoryCreate(BaseModel):
    category: str
    subcategory: str


class SubcategoryUpdate(BaseModel):
    category: str          # current parent
    subcategory: str       # current name
    new_category: Optional[str] = None      # move to another parent
    new_subcategory: Optional[str] = None    # rename


class SubcategoryMerge(BaseModel):
    category: str          # source parent
    subcategory: str       # source name
    into_subcategory: str
    into_category: Optional[str] = None      # defaults to source parent


class SubcategoryRef(BaseModel):
    category: str
    subcategory: str


@app.get("/")
def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "Budget Pivot API is running",
        "endpoints": {
            "pivot": "/api/pivot",
            "transactions": "/api/transactions",
            "categories": "/api/categories"
        }
    }


@app.get("/api/pivot", response_model=PivotResponse)
def get_pivot_data(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    include_subcategories: bool = Query(False, description="Include subcategory breakdown"),
    months_limit: int = Query(12, description="Number of recent months to include"),
    view: str = Query("spending", description="spending | income | everything"),
):
    """
    Get pivot table data with categories and monthly spending.

    `view` controls what's counted (cells are NET, so refunds offset spending):
      - spending (default): real spending — drops income, transfers/payments
        (incl. credit-card payments) and exclude_from_budget txns. Both
        directions kept so refunds net against the category. Outflows positive.
      - income: inflows into is_income categories (exclude_from_budget dropped).
        Inflows positive.
      - everything: every transaction, both directions, no flag filtering.
        Net per category (outflows positive, inflows negative) = cash flow.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Build query for category-level data. LEFT JOIN the taxonomy so we can
        # honor the per-category is_income / is_transfer flags.
        #
        # Each cell is a NET amount so refunds offset spending. The sign points
        # the natural direction positive per view:
        #   - income: inflows positive  -> credit - debit
        #   - spending / everything: outflows positive -> debit - credit
        if view == "income":
            net_expr = ("COALESCE(SUM(t.amount) FILTER (WHERE t.direction = 'credit'), 0)"
                        " - COALESCE(SUM(t.amount) FILTER (WHERE t.direction = 'debit'), 0)")
        else:
            net_expr = ("COALESCE(SUM(t.amount) FILTER (WHERE t.direction = 'debit'), 0)"
                        " - COALESCE(SUM(t.amount) FILTER (WHERE t.direction = 'credit'), 0)")

        query = f"""
            WITH monthly_spending AS (
                SELECT
                    DATE_TRUNC('month', t.txn_date) AS month,
                    t.category,
                    t.subcategory,
                    {net_expr} AS total_spent,
                    COUNT(*) AS transaction_count
                FROM transactions t
                LEFT JOIN taxonomy_categories tc ON tc.category = t.category
                WHERE t.category IS NOT NULL
                    AND t.category != ''
        """

        if view == "income":
            # Inflows into income categories; honor the budget-exclusion flag.
            query += """
                    AND t.direction = 'credit'
                    AND COALESCE(tc.is_income, FALSE) = TRUE
                    AND COALESCE(t.exclude_from_budget, FALSE) = FALSE
            """
        elif view == "everything":
            # Truly everything: income + all outflows, both directions, no flag
            # filtering. Net per cell (outflows minus inflows).
            pass
        else:
            # Default "spending": real spending — drop income & transfers/payments
            # (incl. credit-card payments) and anything excluded from the budget.
            # Both directions kept so refunds net against spending.
            query += """
                    AND COALESCE(tc.is_income, FALSE) = FALSE
                    AND COALESCE(tc.is_transfer, FALSE) = FALSE
                    AND COALESCE(t.exclude_from_budget, FALSE) = FALSE
            """

        params = []
        if start_date:
            query += " AND t.txn_date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND t.txn_date <= %s"
            params.append(end_date)
        
        query += """
                GROUP BY
                    DATE_TRUNC('month', t.txn_date),
                    t.category,
                    t.subcategory
            )
            SELECT
                TO_CHAR(month, 'YYYY-MM') as month,
                category,
                COALESCE(subcategory, 'Uncategorized') as subcategory,
                total_spent,
                transaction_count
            FROM monthly_spending
            ORDER BY month ASC, category ASC, subcategory ASC
        """
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Process data into structured format
        months_set = set()
        category_map = {}  # category -> {month -> amount}
        subcategory_map = {}  # category -> subcategory -> {month -> amount}
        
        for row in rows:
            month = row['month']
            category = row['category']
            subcategory = row['subcategory']
            amount = float(row['total_spent'])
            
            months_set.add(month)
            
            # Category-level aggregation
            if category not in category_map:
                category_map[category] = {}
            if month not in category_map[category]:
                category_map[category][month] = 0
            category_map[category][month] += amount
            
            # Subcategory-level data
            if include_subcategories:
                if category not in subcategory_map:
                    subcategory_map[category] = {}
                if subcategory not in subcategory_map[category]:
                    subcategory_map[category][subcategory] = {}
                subcategory_map[category][subcategory][month] = amount
        
        # Sort months (oldest to newest)
        sorted_months = sorted(list(months_set))
        
        # Limit to recent months if specified
        if months_limit and len(sorted_months) > months_limit:
            sorted_months = sorted_months[-months_limit:]
        
        # Build response
        categories = []
        grand_totals = {month: 0.0 for month in sorted_months}
        
        for category, monthly_data in category_map.items():
            # Filter to only included months
            filtered_monthly = {m: monthly_data.get(m, 0.0) for m in sorted_months}
            total = sum(filtered_monthly.values())

            # Hide categories with no activity in the visible window / current
            # view (e.g. data only outside the month range, or excluded by the
            # view filter). Mirrors the subcategory empty-row hiding on the
            # frontend so empty rows don't reappear.
            if total == 0:
                continue

            # Update grand totals
            for month, amount in filtered_monthly.items():
                grand_totals[month] += amount

            category_obj = CategoryData(
                category=category,
                monthly_data=filtered_monthly,
                total=total
            )
            
            # Add subcategories if requested
            if include_subcategories and category in subcategory_map:
                subcategories = []
                for subcat, subcat_monthly in subcategory_map[category].items():
                    filtered_subcat_monthly = {m: subcat_monthly.get(m, 0.0) for m in sorted_months}
                    subcat_total = sum(filtered_subcat_monthly.values())
                    
                    subcategories.append(SubcategoryData(
                        subcategory=subcat,
                        monthly_data=filtered_subcat_monthly,
                        total=subcat_total
                    ))
                
                # Sort subcategories by total (descending)
                subcategories.sort(key=lambda x: x.total, reverse=True)
                category_obj.subcategories = subcategories
            
            categories.append(category_obj)
        
        # Sort categories by most recent month spending (descending)
        if sorted_months:
            latest_month = sorted_months[-1]
            categories.sort(key=lambda x: x.monthly_data.get(latest_month, 0), reverse=True)
        
        cursor.close()
        conn.close()
        
        return PivotResponse(
            months=sorted_months,
            categories=categories,
            grand_totals=grand_totals
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/subcategories/{category}")
def get_subcategories(
    category: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    months_limit: int = 12
):
    """
    Get subcategory breakdown for a specific category.
    Called when user expands a category in the UI.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            WITH monthly_spending AS (
                SELECT 
                    TO_CHAR(DATE_TRUNC('month', txn_date), 'YYYY-MM') AS month,
                    COALESCE(subcategory, 'Uncategorized') as subcategory,
                    SUM(amount) AS total_spent,
                    COUNT(*) AS transaction_count
                FROM transactions
                WHERE direction = 'debit'
                    AND category = %s
        """
        
        params = [category]
        if start_date:
            query += " AND txn_date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND txn_date <= %s"
            params.append(end_date)
        
        query += """
                GROUP BY 
                    DATE_TRUNC('month', txn_date),
                    subcategory
            )
            SELECT * FROM monthly_spending
            ORDER BY month ASC, subcategory ASC
        """
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Process results
        months_set = set()
        subcategory_map = {}
        
        for row in rows:
            month = row['month']
            subcategory = row['subcategory']
            amount = float(row['total_spent'])
            
            months_set.add(month)
            
            if subcategory not in subcategory_map:
                subcategory_map[subcategory] = {}
            subcategory_map[subcategory][month] = amount
        
        sorted_months = sorted(list(months_set))
        if months_limit and len(sorted_months) > months_limit:
            sorted_months = sorted_months[-months_limit:]
        
        subcategories = []
        for subcat, monthly_data in subcategory_map.items():
            filtered_monthly = {m: monthly_data.get(m, 0.0) for m in sorted_months}
            total = sum(filtered_monthly.values())
            
            subcategories.append({
                "subcategory": subcat,
                "monthly_data": filtered_monthly,
                "total": total
            })
        
        # Sort by total descending
        subcategories.sort(key=lambda x: x['total'], reverse=True)
        
        cursor.close()
        conn.close()
        
        return {
            "category": category,
            "months": sorted_months,
            "subcategories": subcategories
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/transactions")
def get_transactions(
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    month: Optional[str] = None,  # Format: YYYY-MM
    needs_review: Optional[bool] = None,
    direction: Optional[str] = Query(None, regex="^(debit|credit)$"),
    merchant_search: Optional[str] = None,
    tag: Optional[str] = None,
    category_source: Optional[str] = Query(
        None, regex="^(rule|llm|manual|none|venmo_expanded)$"
    ),
    date_from: Optional[str] = None,  # Format: YYYY-MM-DD
    date_to: Optional[str] = None,  # Format: YYYY-MM-DD
    sort_by: str = Query("txn_date", regex="^(txn_date|amount|merchant_norm|category)$"),
    sort_dir: str = Query("desc", regex="^(asc|desc)$"),
    limit: int = Query(100, le=1000),
    offset: int = 0
):
    """
    Get individual transactions with filters.
    Supports sorting, date ranges, and various filters.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT
                txn_id,
                txn_date,
                merchant_norm,
                merchant_detail,
                description_raw,
                amount,
                direction,
                category,
                subcategory,
                needs_review,
                notes,
                tags
            FROM transactions
            WHERE 1=1
        """

        params = []

        if direction:
            query += " AND direction = %s"
            params.append(direction)

        if category:
            query += " AND category = %s"
            params.append(category)
        
        if subcategory:
            query += " AND subcategory = %s"
            params.append(subcategory)
        
        if month:
            # Month format: YYYY-MM
            query += " AND TO_CHAR(DATE_TRUNC('month', txn_date), 'YYYY-MM') = %s"
            params.append(month)
        
        if date_from:
            query += " AND txn_date >= %s"
            params.append(date_from)
        
        if date_to:
            query += " AND txn_date <= %s"
            params.append(date_to)
        
        if needs_review is not None:
            query += " AND needs_review = %s"
            params.append(needs_review)
        
        if merchant_search:
            # Free-text search across merchant, raw description, and notes.
            query += (
                " AND (merchant_norm ILIKE %s OR description_raw ILIKE %s"
                " OR COALESCE(notes, '') ILIKE %s)"
            )
            like = f"%{merchant_search}%"
            params.extend([like, like, like])

        if tag:
            # Match transactions carrying this exact tag (tags is a text[]).
            query += " AND %s = ANY(tags)"
            params.append(tag)

        if category_source:
            query += " AND category_source = %s"
            params.append(category_source)

        # Build ORDER BY clause
        order_clause = f" ORDER BY {sort_by} {sort_dir.upper()}"
        
        # Get total count for pagination (before adding ORDER BY and LIMIT)
        count_query = query.replace(
            """SELECT
                txn_id,
                txn_date,
                merchant_norm,
                merchant_detail,
                description_raw,
                amount,
                direction,
                category,
                subcategory,
                needs_review,
                notes,
                tags""",
            "SELECT COUNT(*) as count"
        )
        
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()['count']
        
        # Add sorting and pagination to main query
        query += order_clause + " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        transactions = []
        for row in rows:
            transactions.append({
                "txn_id": row['txn_id'],
                "txn_date": row['txn_date'].strftime('%Y-%m-%d'),
                "merchant_norm": row['merchant_norm'],
                "merchant_detail": row['merchant_detail'],
                "description_raw": row['description_raw'],
                "amount": float(row['amount']),
                "direction": row['direction'],
                "category": row['category'],
                "subcategory": row['subcategory'],
                "needs_review": row['needs_review'],
                "notes": row['notes'],
                "tags": row['tags'] or []
            })
        
        cursor.close()
        conn.close()
        
        return {
            "transactions": transactions,
            "total_count": total_count,
            "count": len(transactions),
            "limit": limit,
            "offset": offset
        }
    
    except Exception as e:
        # Log the actual error for debugging
        import traceback
        print(f"Error in /api/transactions: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/transactions/{txn_id}")
def update_transaction(
    txn_id: int,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    notes: Optional[str] = None,
    txn_date: Optional[str] = None,
    tags: Optional[List[str]] = Body(default=None)
):
    """
    Update a transaction's category, subcategory, notes, date, or tags.

    Recategorizing (changing category/subcategory/notes) marks the txn reviewed
    and stamps category_source='manual'. Editing only tags or the date does NOT
    touch categorization state.

    A date edit is for correcting recurring bills that posted a day early/late
    around a month boundary (so they land in the right month). We intentionally
    DO NOT recompute source_row_hash: that hash is derived from the *original*
    CSV row at import time, so leaving it untouched keeps re-imports of the same
    statement correctly de-duplicated.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        updates = []
        params = []

        recategorizing = (
            category is not None or subcategory is not None or notes is not None
        )

        if category is not None:
            updates.append("category = %s")
            params.append(category)

        if subcategory is not None:
            updates.append("subcategory = %s")
            params.append(subcategory)

        if notes is not None:
            updates.append("notes = %s")
            params.append(notes)

        if txn_date is not None:
            try:
                datetime.strptime(txn_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="txn_date must be in YYYY-MM-DD format",
                )
            updates.append("txn_date = %s")
            params.append(txn_date)

        if tags is not None:
            # Replace the full tag set. Normalize: trim, drop blanks, de-dupe.
            clean = []
            for t in tags:
                t = (t or "").strip()
                if t and t not in clean:
                    clean.append(t)
            updates.append("tags = %s")
            params.append(clean)

        # Only a recategorization marks the txn reviewed / manual.
        # A pure tag edit leaves categorization provenance untouched.
        if recategorizing:
            updates.append("needs_review = FALSE")
            updates.append("category_source = 'manual'")
            updates.append("category_confidence = 1.0")

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(txn_id)

        query = f"""
            UPDATE transactions
            SET {', '.join(updates)}
            WHERE txn_id = %s
            RETURNING txn_id, category, subcategory, needs_review, tags, txn_date
        """

        cursor.execute(query, params)
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Transaction not found")

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "txn_id": result[0],
            "category": result[1],
            "subcategory": result[2],
            "needs_review": result[3],
            "tags": result[4] or [],
            "txn_date": result[5].strftime('%Y-%m-%d') if result[5] else None,
            "message": "Transaction updated successfully"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rules")
def create_rule(
    merchant_norm: str,
    category: str,
    subcategory: str,
    match_detail: Optional[str] = None,
    match_type: str = "exact",
    priority: int = 50
):
    """
    Create a new categorization rule.
    Called when user clicks "Save & Create Rule" in the drilldown.

    Writes to the merchant_rules table (rule_pack/priority/match_type/
    match_value/match_detail/category/subcategory). Supports composite
    rules via match_detail (e.g. "SQ" + "BREADS BAKERY").
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            INSERT INTO merchant_rules
            (rule_pack, priority, match_type, match_value, match_detail,
             category, subcategory, is_active, created_by, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, 'manual_review', %s)
            RETURNING rule_id
        """

        note = f"Created from drilldown for {merchant_norm}"
        cursor.execute(query, (
            'manual',
            priority,
            match_type,
            merchant_norm,
            match_detail,
            category,
            subcategory,
            note,
        ))
        rule_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "rule_id": rule_id,
            "match_value": merchant_norm,
            "match_detail": match_detail,
            "category": category,
            "subcategory": subcategory,
            "message": "Rule created successfully"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/categories")
def get_categories():
    """Get list of all categories"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT DISTINCT category 
            FROM transactions 
            WHERE category IS NOT NULL 
            ORDER BY category
        """)
        
        categories = [row['category'] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return {"categories": categories}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/subcategories")
def get_subcategories(category: Optional[str] = None):
    """Get list of subcategories, optionally filtered by category"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        if category:
            cursor.execute("""
                SELECT DISTINCT subcategory 
                FROM transactions 
                WHERE category = %s AND subcategory IS NOT NULL 
                ORDER BY subcategory
            """, (category,))
        else:
            cursor.execute("""
                SELECT category, subcategory
                FROM taxonomy_subcategories
                ORDER BY category, subcategory
            """)
        
        if category:
            subcategories = [row['subcategory'] for row in cursor.fetchall()]
            result = {"category": category, "subcategories": subcategories}
        else:
            rows = cursor.fetchall()
            result = {}
            for row in rows:
                cat = row['category']
                if cat not in result:
                    result[cat] = []
                result[cat].append(row['subcategory'])
        
        cursor.close()
        conn.close()
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
def get_stats():
    """Get dashboard statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_transactions,
                COUNT(*) FILTER (WHERE NOT needs_review) as categorized,
                COUNT(*) FILTER (WHERE needs_review) as needs_review,
                SUM(amount) FILTER (WHERE direction = 'debit') as total_expenses,
                SUM(amount) FILTER (WHERE direction = 'credit') as total_income
            FROM transactions
        """)
        
        stats = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return {
            "total_transactions": stats['total_transactions'],
            "categorized": stats['categorized'],
            "needs_review": stats['needs_review'],
            "categorization_rate": (stats['categorized'] / stats['total_transactions'] * 100) if stats['total_transactions'] > 0 else 0,
            "total_expenses": float(stats['total_expenses'] or 0),
            "total_income": float(stats['total_income'] or 0)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Taxonomy management
#
# The DB is the source of truth for the category tree (taxonomy.json /
# taxonomy_sync.py are retired). These endpoints add/rename/move/merge/delete
# categories and subcategories and cascade every structural change to
# `transactions` and `merchant_rules` in a single transaction.
#
# Key DB facts that drive the implementation:
#   - taxonomy_categories.category is the PRIMARY KEY (the name itself), so a
#     rename is: insert new row -> re-point children -> delete old row.
#   - There is NO `ON UPDATE CASCADE` anywhere, hence the manual re-pointing.
#   - taxonomy_subcategories.category -> taxonomy_categories : ON DELETE CASCADE
#   - transactions.(category,subcategory) -> taxonomy_subcategories : SET NULL
#   - merchant_rules.(category,subcategory) -> taxonomy_subcategories : RESTRICT
#
# Re-point UPDATEs deliberately leave category_source / category_confidence /
# needs_review untouched: a structural relabel is not a manual recategorization.
# ============================================================================


def _counts(cursor, category: str, subcategory: Optional[str] = None):
    """Return (txn_count, rule_count) for a category or a specific subcategory."""
    if subcategory is None:
        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE category = %s",
            (category,),
        )
        txn_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM merchant_rules WHERE category = %s",
            (category,),
        )
        rule_count = cursor.fetchone()[0]
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE category = %s AND subcategory = %s",
            (category, subcategory),
        )
        txn_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM merchant_rules WHERE category = %s AND subcategory = %s",
            (category, subcategory),
        )
        rule_count = cursor.fetchone()[0]
    return txn_count, rule_count


@app.get("/api/taxonomy/tree")
def get_taxonomy_tree():
    """
    Full category tree for the Taxonomy Management page: every category with
    its subcategories, each annotated with txn_count / rule_count usage.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Per-(category,subcategory) usage counts.
        cursor.execute("""
            SELECT s.category, s.subcategory,
                   COALESCE(t.txn_count, 0)  AS txn_count,
                   COALESCE(r.rule_count, 0) AS rule_count
            FROM taxonomy_subcategories s
            LEFT JOIN (
                SELECT category, subcategory, COUNT(*) AS txn_count
                FROM transactions
                GROUP BY category, subcategory
            ) t ON t.category = s.category AND t.subcategory = s.subcategory
            LEFT JOIN (
                SELECT category, subcategory, COUNT(*) AS rule_count
                FROM merchant_rules
                GROUP BY category, subcategory
            ) r ON r.category = s.category AND r.subcategory = s.subcategory
            ORDER BY s.category, s.subcategory
        """)
        sub_rows = cursor.fetchall()

        subs_by_cat = {}
        for row in sub_rows:
            subs_by_cat.setdefault(row["category"], []).append({
                "subcategory": row["subcategory"],
                "txn_count": row["txn_count"],
                "rule_count": row["rule_count"],
            })

        # Categories with their own roll-up counts.
        cursor.execute("""
            SELECT c.category, c.display_order, c.is_income, c.is_transfer,
                   COALESCE(t.txn_count, 0)  AS txn_count,
                   COALESCE(r.rule_count, 0) AS rule_count
            FROM taxonomy_categories c
            LEFT JOIN (
                SELECT category, COUNT(*) AS txn_count
                FROM transactions
                GROUP BY category
            ) t ON t.category = c.category
            LEFT JOIN (
                SELECT category, COUNT(*) AS rule_count
                FROM merchant_rules
                GROUP BY category
            ) r ON r.category = c.category
            ORDER BY c.display_order, c.category
        """)
        cat_rows = cursor.fetchall()

        categories = []
        for row in cat_rows:
            categories.append({
                "category": row["category"],
                "display_order": row["display_order"],
                "is_income": row["is_income"],
                "is_transfer": row["is_transfer"],
                "txn_count": row["txn_count"],
                "rule_count": row["rule_count"],
                "subcategories": subs_by_cat.get(row["category"], []),
            })

        cursor.close()
        conn.close()
        return {"categories": categories}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----- Category ops ---------------------------------------------------------

@app.post("/api/taxonomy/categories")
def create_category(body: CategoryCreate):
    """Create a new category at display_order = MAX + 1."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM taxonomy_categories WHERE category = %s",
            (body.category,),
        )
        if cursor.fetchone():
            cursor.close()
            conn.close()
            raise HTTPException(
                status_code=409, detail=f"Category '{body.category}' already exists"
            )

        cursor.execute("SELECT COALESCE(MAX(display_order), 0) FROM taxonomy_categories")
        next_order = cursor.fetchone()[0] + 1

        cursor.execute(
            """
            INSERT INTO taxonomy_categories
                (category, display_order, is_income, is_transfer)
            VALUES (%s, %s, %s, %s)
            """,
            (body.category, next_order, body.is_income, body.is_transfer),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return {"category": body.category, "display_order": next_order,
                "message": "Category created"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/taxonomy/categories/{category}")
def update_category(category: str, body: CategoryUpdate):
    """
    Rename a category and/or set its flags/order. A rename re-points
    subcategories, transactions and rules to the new name in one transaction.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT display_order, is_income, is_transfer FROM taxonomy_categories WHERE category = %s",
            (category,),
        )
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=f"Category '{category}' not found")

        cur_order, cur_income, cur_transfer = existing
        new_name = body.new_category
        renaming = new_name is not None and new_name != category

        # Resolve final flag/order values (used by both rename and in-place edit).
        final_order = body.display_order if body.display_order is not None else cur_order
        final_income = body.is_income if body.is_income is not None else cur_income
        final_transfer = body.is_transfer if body.is_transfer is not None else cur_transfer

        if renaming:
            cursor.execute(
                "SELECT 1 FROM taxonomy_categories WHERE category = %s", (new_name,)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail=f"Category '{new_name}' already exists. Use merge instead.",
                )
            # insert target -> re-point children -> delete source, one txn.
            cursor.execute(
                """
                INSERT INTO taxonomy_categories
                    (category, display_order, is_income, is_transfer)
                VALUES (%s, %s, %s, %s)
                """,
                (new_name, final_order, final_income, final_transfer),
            )
            cursor.execute(
                "UPDATE taxonomy_subcategories SET category = %s WHERE category = %s",
                (new_name, category),
            )
            cursor.execute(
                "UPDATE transactions SET category = %s WHERE category = %s",
                (new_name, category),
            )
            cursor.execute(
                "UPDATE merchant_rules SET category = %s WHERE category = %s",
                (new_name, category),
            )
            cursor.execute(
                "DELETE FROM taxonomy_categories WHERE category = %s", (category,)
            )
            result_name = new_name
        else:
            cursor.execute(
                """
                UPDATE taxonomy_categories
                SET display_order = %s, is_income = %s, is_transfer = %s
                WHERE category = %s
                """,
                (final_order, final_income, final_transfer, category),
            )
            result_name = category

        conn.commit()
        return {"category": result_name, "message": "Category updated"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/api/taxonomy/categories/{category}/merge")
def merge_category(category: str, body: CategoryMerge):
    """
    Merge `category` into `body.into`: move all subcategories (creating missing
    target rows), re-point transactions/rules, then delete the source category.
    """
    into = body.into
    if into == category:
        raise HTTPException(status_code=400, detail="Cannot merge a category into itself")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM taxonomy_categories WHERE category = %s", (category,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Category '{category}' not found")
        cursor.execute("SELECT 1 FROM taxonomy_categories WHERE category = %s", (into,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Target category '{into}' not found")

        # Ensure target (into, subcat) rows exist for every source subcat.
        cursor.execute(
            "SELECT subcategory FROM taxonomy_subcategories WHERE category = %s",
            (category,),
        )
        src_subs = [r[0] for r in cursor.fetchall()]
        for sub in src_subs:
            cursor.execute(
                """
                INSERT INTO taxonomy_subcategories (category, subcategory)
                VALUES (%s, %s)
                ON CONFLICT (category, subcategory) DO NOTHING
                """,
                (into, sub),
            )

        # Re-point transactions and rules to the target category (keep subcategory).
        cursor.execute(
            "UPDATE transactions SET category = %s WHERE category = %s",
            (into, category),
        )
        cursor.execute(
            "UPDATE merchant_rules SET category = %s WHERE category = %s",
            (into, category),
        )

        # Delete source category; its now-orphaned subcat rows cascade.
        cursor.execute("DELETE FROM taxonomy_categories WHERE category = %s", (category,))

        conn.commit()
        return {"category": into, "message": f"Merged '{category}' into '{into}'"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@app.delete("/api/taxonomy/categories/{category}")
def delete_category(category: str):
    """Delete a category only if it has zero transactions and zero rules."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM taxonomy_categories WHERE category = %s", (category,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Category '{category}' not found")

        txn_count, rule_count = _counts(cursor, category)
        if txn_count > 0 or rule_count > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Category '{category}' has {txn_count} transactions and "
                    f"{rule_count} rules. Merge it into another category instead."
                ),
            )

        # Empty: subcategory rows cascade on delete.
        cursor.execute("DELETE FROM taxonomy_categories WHERE category = %s", (category,))
        conn.commit()
        return {"category": category, "message": "Category deleted"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


# ----- Subcategory ops ------------------------------------------------------

@app.post("/api/taxonomy/subcategories")
def create_subcategory(body: SubcategoryCreate):
    """Create a new (category, subcategory) pair."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM taxonomy_categories WHERE category = %s", (body.category,)
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404, detail=f"Category '{body.category}' not found"
            )

        cursor.execute(
            "SELECT 1 FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (body.category, body.subcategory),
        )
        if cursor.fetchone():
            raise HTTPException(
                status_code=409,
                detail=f"Subcategory '{body.category} / {body.subcategory}' already exists",
            )

        cursor.execute(
            "INSERT INTO taxonomy_subcategories (category, subcategory) VALUES (%s, %s)",
            (body.category, body.subcategory),
        )
        conn.commit()
        return {"category": body.category, "subcategory": body.subcategory,
                "message": "Subcategory created"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@app.put("/api/taxonomy/subcategories")
def update_subcategory(body: SubcategoryUpdate):
    """
    Rename a subcategory (same parent) and/or move it to a new parent. Ensures
    the target row exists, re-points transactions/rules, deletes the old row.
    """
    target_cat = body.new_category if body.new_category is not None else body.category
    target_sub = body.new_subcategory if body.new_subcategory is not None else body.subcategory

    if target_cat == body.category and target_sub == body.subcategory:
        raise HTTPException(status_code=400, detail="No change requested")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (body.category, body.subcategory),
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Subcategory '{body.category} / {body.subcategory}' not found",
            )

        cursor.execute(
            "SELECT 1 FROM taxonomy_categories WHERE category = %s", (target_cat,)
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404, detail=f"Target category '{target_cat}' not found"
            )

        # If the target already exists and holds data, this is a merge.
        cursor.execute(
            "SELECT 1 FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (target_cat, target_sub),
        )
        target_exists = cursor.fetchone() is not None
        if target_exists:
            tcount, rcount = _counts(cursor, target_cat, target_sub)
            if tcount > 0 or rcount > 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Target '{target_cat} / {target_sub}' already exists with data. "
                        "Use merge instead."
                    ),
                )

        # Ensure target row exists, re-point, delete source.
        cursor.execute(
            """
            INSERT INTO taxonomy_subcategories (category, subcategory)
            VALUES (%s, %s)
            ON CONFLICT (category, subcategory) DO NOTHING
            """,
            (target_cat, target_sub),
        )
        cursor.execute(
            """
            UPDATE transactions SET category = %s, subcategory = %s
            WHERE category = %s AND subcategory = %s
            """,
            (target_cat, target_sub, body.category, body.subcategory),
        )
        cursor.execute(
            """
            UPDATE merchant_rules SET category = %s, subcategory = %s
            WHERE category = %s AND subcategory = %s
            """,
            (target_cat, target_sub, body.category, body.subcategory),
        )
        cursor.execute(
            "DELETE FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (body.category, body.subcategory),
        )

        conn.commit()
        return {"category": target_cat, "subcategory": target_sub,
                "message": "Subcategory updated"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/api/taxonomy/subcategories/merge")
def merge_subcategory(body: SubcategoryMerge):
    """Merge a subcategory into a sibling (or a subcategory under another parent)."""
    into_cat = body.into_category if body.into_category is not None else body.category
    into_sub = body.into_subcategory

    if into_cat == body.category and into_sub == body.subcategory:
        raise HTTPException(status_code=400, detail="Cannot merge a subcategory into itself")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (body.category, body.subcategory),
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Source '{body.category} / {body.subcategory}' not found",
            )

        # Ensure target exists (create if missing under an existing category).
        cursor.execute(
            "SELECT 1 FROM taxonomy_categories WHERE category = %s", (into_cat,)
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404, detail=f"Target category '{into_cat}' not found"
            )
        cursor.execute(
            """
            INSERT INTO taxonomy_subcategories (category, subcategory)
            VALUES (%s, %s)
            ON CONFLICT (category, subcategory) DO NOTHING
            """,
            (into_cat, into_sub),
        )

        cursor.execute(
            """
            UPDATE transactions SET category = %s, subcategory = %s
            WHERE category = %s AND subcategory = %s
            """,
            (into_cat, into_sub, body.category, body.subcategory),
        )
        cursor.execute(
            """
            UPDATE merchant_rules SET category = %s, subcategory = %s
            WHERE category = %s AND subcategory = %s
            """,
            (into_cat, into_sub, body.category, body.subcategory),
        )
        cursor.execute(
            "DELETE FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (body.category, body.subcategory),
        )

        conn.commit()
        return {
            "category": into_cat,
            "subcategory": into_sub,
            "message": f"Merged '{body.category} / {body.subcategory}' into "
                       f"'{into_cat} / {into_sub}'",
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@app.delete("/api/taxonomy/subcategories")
def delete_subcategory(body: SubcategoryRef):
    """Delete a subcategory only if it has zero transactions and zero rules."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (body.category, body.subcategory),
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Subcategory '{body.category} / {body.subcategory}' not found",
            )

        txn_count, rule_count = _counts(cursor, body.category, body.subcategory)
        if txn_count > 0 or rule_count > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Subcategory '{body.category} / {body.subcategory}' has "
                    f"{txn_count} transactions and {rule_count} rules. Merge it instead."
                ),
            )

        cursor.execute(
            "DELETE FROM taxonomy_subcategories WHERE category = %s AND subcategory = %s",
            (body.category, body.subcategory),
        )
        conn.commit()
        return {"category": body.category, "subcategory": body.subcategory,
                "message": "Subcategory deleted"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


# ============================================================================
# Import (Chase CSV) — upload → preview → commit
# ============================================================================

# Cap upload size to protect the server (statements are tiny: ~50-300 rows).
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def _valid_taxonomy_pairs(conn) -> set:
    """Set of valid (category, subcategory) pairs from the DB taxonomy, plus
    each category paired with None (category-only assignment is allowed)."""
    cursor = conn.cursor()
    cursor.execute("SELECT category, subcategory FROM taxonomy_subcategories")
    pairs = {(c, s) for c, s in cursor.fetchall()}
    cursor.execute("SELECT category FROM taxonomy_categories")
    for (c,) in cursor.fetchall():
        pairs.add((c, None))
    cursor.close()
    return pairs


@app.post("/api/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    account_id: Optional[int] = Form(None),
    use_llm: bool = Form(False),
):
    """
    Parse + categorize an uploaded Chase CSV and return a preview. Writes NOTHING.

    The LLM (if enabled) is paid here, not on commit. Each returned row carries
    everything commit needs to insert it, plus a per-row `is_duplicate` flag so
    the user can see which rows already exist before importing.
    """
    from budget_automation.core.csv_parser import parse_chase_csv
    from budget_automation.core.import_service import (
        categorize_parsed,
        existing_hashes_for,
        existing_content_keys,
        content_key,
    )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    tmp_path = None
    conn = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".csv", delete=False
        ) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        try:
            parsed = parse_chase_csv(tmp_path, "auto", account_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if not parsed:
            return {"csv_type": None, "account_id": account_id,
                    "totals": {"parsed": 0}, "rows": []}

        detected_account = parsed[0]["account_id"]
        csv_type = parsed[0]["source"]

        conn = get_db_connection()
        txn_dicts, stats = categorize_parsed(conn, parsed, enable_llm=use_llm)

        # Duplicate detection robust to the dedup-hash scheme change: a row is a
        # duplicate if its new-style hash is already stored, OR if the DB already
        # holds at least as many rows with the same content key as this row's
        # occurrence index (handles rows inserted under the old hash scheme).
        new_hashes = [t["source_row_hash"] for t in txn_dicts]
        stored = existing_hashes_for(conn, new_hashes)
        account_ids = list({t["account_id"] for t in txn_dicts})
        db_key_counts = existing_content_keys(conn, account_ids)

        seen_occurrence: dict = {}
        rows = []
        dup_count = 0
        for t in txn_dicts:
            key = content_key(
                t["txn_date"], t["description_raw"], t["amount"], t["account_id"]
            )
            seen_occurrence[key] = seen_occurrence.get(key, 0) + 1
            occ = seen_occurrence[key]

            is_dup = (
                t["source_row_hash"] in stored
                or db_key_counts.get(key, 0) >= occ
            )
            if is_dup:
                dup_count += 1

            rows.append({
                "source_row_hash": t["source_row_hash"],
                "txn_date": str(t["txn_date"]),
                "post_date": str(t["post_date"]),
                "description_raw": t["description_raw"],
                "merchant_norm": t["merchant_norm"],
                "merchant_detail": t["merchant_detail"],
                "amount": float(t["amount"]),
                "direction": t["direction"],
                "category": t["category"],
                "subcategory": t["subcategory"],
                "category_source": t["category_source"],
                "category_confidence": (
                    float(t["category_confidence"])
                    if t["category_confidence"] is not None else None
                ),
                "needs_review": t["needs_review"],
                "is_duplicate": is_dup,
                # carried for commit (not shown), so commit need not re-parse/LLM
                "_insert": {
                    "account_id": t["account_id"],
                    "source": t["source"],
                    "merchant_raw": t["merchant_raw"],
                    "currency": t["currency"],
                    "type": t["type"],
                    "is_return": t["is_return"],
                    "notes": t["notes"],
                    "memo": t["memo"],
                },
            })

        return {
            "csv_type": csv_type,
            "account_id": detected_account,
            "totals": {
                "parsed": len(rows),
                "new": len(rows) - dup_count,
                "duplicates": dup_count,
                "rule_matched": stats.get("rule_match", 0),
                "llm_matched": stats.get("llm_suggest", 0),
                "needs_review": stats.get("needs_review", 0),
            },
            "rows": rows,
        }
    finally:
        if conn is not None:
            conn.close()
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


class ImportCommitRow(BaseModel):
    source_row_hash: str
    txn_date: str
    post_date: Optional[str] = None
    description_raw: str
    merchant_norm: str
    merchant_detail: Optional[str] = None
    amount: float
    direction: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    category_source: Optional[str] = None
    category_confidence: Optional[float] = None
    needs_review: bool = False
    _insert: dict


class ImportCommitBody(BaseModel):
    rows: List[dict]


@app.post("/api/import/commit")
def import_commit(body: ImportCommitBody):
    """
    Insert the rows the user kept (from a prior preview). Does NOT re-run the
    LLM. Categories are re-validated against the DB taxonomy to prevent a tampered
    client from writing invalid pairs. Dedup on source_row_hash UNIQUE is the
    backstop.
    """
    from budget_automation.core.import_service import insert_transactions

    if not body.rows:
        return {"inserted": 0, "duplicates": 0, "errors": 0}

    conn = get_db_connection()
    try:
        valid_pairs = _valid_taxonomy_pairs(conn)

        txn_dicts = []
        for r in body.rows:
            ins = r.get("_insert", {})
            category = r.get("category")
            subcategory = r.get("subcategory")
            # Validate against taxonomy; anything invalid falls back to review.
            if (category, subcategory) not in valid_pairs and (category, None) not in valid_pairs:
                category, subcategory = "Uncategorized", "Needs Review"
                needs_review = True
            else:
                needs_review = bool(r.get("needs_review", False))

            txn_dicts.append({
                "account_id": ins["account_id"],
                "source": ins["source"],
                "source_row_hash": r["source_row_hash"],
                "txn_date": r["txn_date"],
                "post_date": r.get("post_date") or r["txn_date"],
                "description_raw": r["description_raw"],
                "merchant_raw": ins["merchant_raw"],
                "merchant_norm": r["merchant_norm"],
                "merchant_detail": r.get("merchant_detail"),
                "amount": r["amount"],
                "currency": ins.get("currency", "USD"),
                "direction": r["direction"],
                "type": ins.get("type"),
                "is_return": ins.get("is_return", False),
                "category": category,
                "subcategory": subcategory,
                "category_source": r.get("category_source"),
                "category_confidence": r.get("category_confidence"),
                "needs_review": needs_review,
                "notes": ins.get("notes"),
                "memo": ins.get("memo"),
                "created_by": "import",
            })

        inserted, duplicates, errors = insert_transactions(conn, txn_dicts)
        return {"inserted": inserted, "duplicates": duplicates, "errors": errors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/transactions/recategorize-review")
def recategorize_review_queue():
    """
    Re-run the needs-review queue through the rules + LLM pipeline.

    Targets every transaction with needs_review = TRUE (e.g. rows imported while
    the LLM was unavailable, plus prior low-confidence attempts). Each is passed
    through the same CategorizationOrchestrator the importer uses (rules first,
    then LLM fallback). Results are written back per row:

      - A rule/LLM suggestion (anything other than 'Uncategorized') overwrites the
        row's category/subcategory/category_source/category_confidence.
      - needs_review is cleared (FALSE) only when the result's confidence meets the
        REVIEW_THRESHOLD; otherwise the suggestion is filled in but the row stays
        flagged for manual confirmation.
      - Rows the pipeline still can't place (or that error) are left untouched and
        stay in the queue.

    Manual recategorizations are NOT preserved across this call only if they were
    still flagged needs_review (a manual edit normally clears the flag, so it won't
    be picked up here). Writes are per-row committed; the LLM is paid on this call.
    """
    from budget_automation.core.taxonomy_db import load_taxonomy_from_db
    from budget_automation.core.categorization_orchestrator import (
        CategorizationOrchestrator,
        Transaction,
        load_rules_from_db,
    )

    review_threshold = float(os.getenv("REVIEW_THRESHOLD", "0.80"))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT txn_id, merchant_norm, merchant_detail, description_raw,
                   amount, direction
            FROM transactions
            WHERE needs_review = TRUE
            ORDER BY txn_id
            """
        )
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            return {
                "scanned": 0, "rule_matched": 0, "llm_matched": 0,
                "cleared": 0, "still_flagged": 0, "unresolved": 0,
            }

        taxonomy = load_taxonomy_from_db(conn)
        rules = load_rules_from_db(conn)
        orchestrator = CategorizationOrchestrator(
            taxonomy=taxonomy,
            rules=rules,
            review_threshold=review_threshold,
            enable_llm=True,
        )

        # Build Transaction objects, keeping each one's txn_id for write-back.
        # categorize_batch mutates these in place (only reorders the list), so
        # pairing by object identity is exact.
        txn_by_id = {}
        transactions = []
        for (txn_id, m_norm, m_detail, desc, amount, direction) in rows:
            txn = Transaction(
                txn_id=txn_id,
                merchant_norm=m_norm,
                merchant_detail=m_detail,
                description_raw=desc or "",
                amount=float(amount),
                direction=direction,
                txn_date="",
                post_date="",
                account_id=0,
                source="recategorize",
                type="",
                is_return=False,
            )
            txn_by_id[id(txn)] = txn_id
            transactions.append(txn)

        categorized = orchestrator.categorize_batch(transactions)

        rule_matched = llm_matched = cleared = still_flagged = unresolved = 0
        write_cursor = conn.cursor()
        for txn in categorized:
            real_id = txn_by_id[id(txn)]

            # Pipeline couldn't place it (no rule, LLM disabled/failed) -> leave
            # the row exactly as it was, still in the queue.
            if not txn.category or txn.category == "Uncategorized":
                unresolved += 1
                continue

            confidence = txn.category_confidence or 0.0
            clear = confidence >= review_threshold
            new_needs_review = not clear

            write_cursor.execute(
                """
                UPDATE transactions
                SET category = %s,
                    subcategory = %s,
                    category_source = %s,
                    category_confidence = %s,
                    needs_review = %s,
                    notes = %s
                WHERE txn_id = %s
                """,
                (
                    txn.category,
                    txn.subcategory,
                    txn.category_source,
                    confidence,
                    new_needs_review,
                    txn.notes,
                    real_id,
                ),
            )
            conn.commit()

            if txn.category_source == "rule":
                rule_matched += 1
            elif txn.category_source == "llm":
                llm_matched += 1
            if clear:
                cleared += 1
            else:
                still_flagged += 1

        write_cursor.close()

        return {
            "scanned": len(rows),
            "rule_matched": rule_matched,
            "llm_matched": llm_matched,
            "cleared": cleared,
            "still_flagged": still_flagged,
            "unresolved": unresolved,
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class BulkRecategorizeBody(BaseModel):
    txn_ids: List[int]
    category: str
    subcategory: Optional[str] = None


@app.post("/api/transactions/bulk-recategorize")
def bulk_recategorize(body: BulkRecategorizeBody):
    """
    Recategorize many transactions at once (used by the Transactions cleanup
    page). Mirrors the single PUT semantics: stamps category_source='manual',
    confidence 1.0, and clears needs_review.

    The (category, subcategory) pair is validated against the DB taxonomy and an
    invalid pair is rejected (400) — this is an explicit user action, so we do
    NOT silently fall back to Uncategorized. All rows update in one transaction.
    """
    if not body.txn_ids:
        return {"updated": 0}

    conn = get_db_connection()
    try:
        valid_pairs = _valid_taxonomy_pairs(conn)
        if (body.category, body.subcategory) not in valid_pairs and (
            body.category,
            None,
        ) not in valid_pairs:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category/subcategory: "
                f"{body.category} / {body.subcategory}",
            )

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE transactions
            SET category = %s,
                subcategory = %s,
                category_source = 'manual',
                category_confidence = 1.0,
                needs_review = FALSE
            WHERE txn_id = ANY(%s)
            """,
            (body.category, body.subcategory, body.txn_ids),
        )
        updated = cursor.rowcount
        conn.commit()
        cursor.close()
        return {"updated": updated}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================================
# Amazon enrichment — stage orders → preview → commit (soft-supersede)
# ============================================================================

@app.post("/api/amazon/import")
async def amazon_import(file: UploadFile = File(...)):
    """Stage an uploaded Amazon order-history CSV into amazon_orders_raw."""
    from budget_automation.core.amazon_import import stage_amazon_orders

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    tmp_path = None
    conn = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".csv", delete=False
        ) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        conn = get_db_connection()
        result = stage_amazon_orders(conn, tmp_path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn is not None:
            conn.close()
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/api/amazon/enrichment/preview")
def amazon_enrichment_preview(
    start_date: str = "2023-01-01",
    use_llm: bool = False,
):
    """Read-only enrichment plan: matches, line items, and card txns that would
    be superseded. Writes nothing."""
    from budget_automation.core.amazon_enrichment import build_enrichment_plan

    conn = get_db_connection()
    try:
        return build_enrichment_plan(conn, start_date=start_date, use_llm=use_llm)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class AmazonEnrichBody(BaseModel):
    order_ids: List[str]
    use_llm: bool = False
    start_date: str = "2023-01-01"


@app.post("/api/amazon/enrichment/commit")
def amazon_enrichment_commit(body: AmazonEnrichBody):
    """Enrich approved orders in a single transaction. Soft-supersedes matched
    card txns (exclude_from_budget=TRUE) instead of deleting them."""
    from budget_automation.core.amazon_enrichment import commit_enrichment

    conn = get_db_connection()
    try:
        return commit_enrichment(
            conn,
            body.order_ids,
            use_llm=body.use_llm,
            start_date=body.start_date,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/import/last-dates")
def import_last_dates():
    """Latest transaction/order DATE we already hold, per import type, so the
    user knows where to resume uploading. Reports the date of the most recent
    transaction/order itself (not when it was uploaded or enriched).

    - Chase: MAX(txn_date) per account, filtered to real statement sources
      (chase_checking / chase_credit) so enrichment line-items don't skew it.
    - Amazon: MAX(order_date) from amazon_orders_raw.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                a.account_id AS account_id,
                a.account_name,
                a.account_type,
                MAX(t.txn_date) AS last_txn_date,
                COUNT(t.txn_id) AS txn_count
            FROM accounts a
            LEFT JOIN transactions t
                ON t.account_id = a.account_id
               AND t.source IN ('chase_checking', 'chase_credit')
            GROUP BY a.account_id, a.account_name, a.account_type
            ORDER BY a.account_id
        """)
        chase = [
            {
                "account_id": r["account_id"],
                "account_name": r["account_name"],
                "account_type": r["account_type"],
                "last_txn_date": r["last_txn_date"].isoformat() if r["last_txn_date"] else None,
                "txn_count": r["txn_count"],
            }
            for r in cursor.fetchall()
        ]

        cursor.execute("""
            SELECT
                MAX(order_date) AS last_order_date,
                COUNT(DISTINCT order_id) AS order_count
            FROM amazon_orders_raw
        """)
        amz = cursor.fetchone()
        amazon = {
            "last_order_date": amz["last_order_date"].isoformat() if amz["last_order_date"] else None,
            "order_count": amz["order_count"],
        }

        cursor.close()
        conn.close()

        return {"chase": chase, "amazon": amazon}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
