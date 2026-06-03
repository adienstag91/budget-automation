"""
Taxonomy loader (DB-authoritative).

The category tree lives in the `taxonomy_categories` / `taxonomy_subcategories`
tables and is managed through the Taxonomy Management page / the `/api/taxonomy/*`
endpoints. The old `data/taxonomy/taxonomy.json` is retired.

This module builds the taxonomy in the shape the categorization stack expects
(`LLMCategorizer` reads `taxonomy['categories'][i]['name']` and
`['subcategories']`), so the importer and the Amazon enricher can both load it
from the DB instead of a stale JSON file.
"""
from typing import Dict


def load_taxonomy_from_db(conn) -> Dict:
    """
    Build the taxonomy dict from the database.

    Returns:
        {
          "categories": [
            {"name": <category>,
             "subcategories": [<subcategory>, ...],
             "is_income": bool,
             "is_transfer": bool},
            ...
          ]
        }
    Categories are ordered by display_order; subcategories alphabetically.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT category, display_order, is_income, is_transfer
        FROM taxonomy_categories
        ORDER BY display_order, category
        """
    )
    cat_rows = cursor.fetchall()

    cursor.execute(
        """
        SELECT category, subcategory
        FROM taxonomy_subcategories
        ORDER BY category, subcategory
        """
    )
    sub_rows = cursor.fetchall()
    cursor.close()

    subs_by_cat: Dict[str, list] = {}
    for category, subcategory in sub_rows:
        subs_by_cat.setdefault(category, []).append(subcategory)

    categories = []
    for category, _display_order, is_income, is_transfer in cat_rows:
        categories.append(
            {
                "name": category,
                "subcategories": subs_by_cat.get(category, []),
                "is_income": is_income,
                "is_transfer": is_transfer,
            }
        )

    return {"categories": categories}
