"""
FastAPI Backend for Budget Pivot Table

This exposes your PostgreSQL data as REST API endpoints that 
your Lovable frontend can consume.

Run with: uvicorn api:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, date
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
import os

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
    months_limit: int = Query(12, description="Number of recent months to include")
):
    """
    Get pivot table data with categories and monthly spending.
    
    This is the main endpoint your Lovable frontend will call.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build query for category-level data
        query = """
            WITH monthly_spending AS (
                SELECT 
                    DATE_TRUNC('month', txn_date) AS month,
                    category,
                    subcategory,
                    SUM(amount) AS total_spent,
                    COUNT(*) AS transaction_count
                FROM transactions
                WHERE direction = 'debit'
                    AND category IS NOT NULL
                    AND category != ''
        """
        
        params = []
        if start_date:
            query += " AND txn_date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND txn_date <= %s"
            params.append(end_date)
        
        query += """
                GROUP BY 
                    DATE_TRUNC('month', txn_date),
                    category,
                    subcategory
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
            query += " AND (merchant_norm ILIKE %s OR description_raw ILIKE %s)"
            params.append(f"%{merchant_search}%")
            params.append(f"%{merchant_search}%")
        
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
    tags: Optional[List[str]] = Body(default=None)
):
    """
    Update a transaction's category, subcategory, notes, or tags.

    Recategorizing (changing category/subcategory/notes) marks the txn reviewed
    and stamps category_source='manual'. Editing only tags does NOT touch
    categorization state -- tags are independent, manual, ad-hoc labels.
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
            RETURNING txn_id, category, subcategory, needs_review, tags
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
