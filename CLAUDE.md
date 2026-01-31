# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Budget Automation is an intelligent budgeting system that learns from historical spending patterns to automatically categorize transactions. It uses a rule-based matching system with optional LLM fallback to categorize 90%+ of transactions automatically.

**Key Innovation**: Composite rules that handle payment processors (Square, Zelle, Toast) by matching both merchant name and business/payee details.

## Development Commands

### Initial Setup

```bash
# Install package in development mode
pip install -e .

# Install with dev dependencies (testing, linting, formatting)
pip install -e ".[dev]"

# Install with UI dependencies (Streamlit dashboard)
pip install -e ".[ui]"

# Copy environment template and configure
cp .env.example .env
# Edit .env to add ANTHROPIC_API_KEY (optional)
```

### Database Operations

```bash
# Start PostgreSQL database (runs on port 5433 to avoid conflicts)
docker-compose up -d

# Stop database (preserves data)
docker-compose stop

# Reset database completely (deletes all data)
docker-compose down -v

# View database logs
docker-compose logs -f postgres

# Access database directly via psql
docker-compose exec postgres psql -U budget_user -d budget_db

# Start pgAdmin web UI (optional)
docker-compose --profile tools up -d
# Access at http://localhost:5050 (admin@budget.local / admin)
```

### CLI Commands

```bash
# Initialize database (create schema, load taxonomy, import rules)
budget-init

# Import transactions from Chase CSV
budget-import path/to/chase_export.csv

# Import without LLM (rules only)
budget-import transactions.csv --no-llm

# Dry run (preview without importing)
budget-import transactions.csv --dry-run
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=budget_automation

# Run specific test file
pytest tests/test_merchant_normalizer.py

# Run specific test function
pytest tests/test_merchant_normalizer.py::test_normalize_amazon
```

### Code Quality

```bash
# Format code
black budget_automation/ tests/

# Lint code
flake8 budget_automation/ tests/

# Type check
mypy budget_automation/
```

## Architecture

### Core Components

1. **Merchant Normalizer** (`budget_automation/core/merchant_normalizer.py`)
   - Cleans raw bank descriptions into normalized merchant names
   - Extracts details for payment processors (Square, Zelle, Toast)
   - Returns tuple: `(merchant_norm, merchant_detail)`
   - Example: `"SQ *BREADS BAKERY"` → `("SQ", "BREADS BAKERY")`

2. **Rule Matcher** (`budget_automation/core/rule_matcher.py`)
   - Matches transactions against merchant rules
   - Supports simple rules (merchant only) and composite rules (merchant + detail)
   - Rule priority: Manual (10) > Composite (50) > Learned (100)
   - Match types: exact, contains, startswith, regex

3. **Categorization Orchestrator** (`budget_automation/core/categorization_orchestrator.py`)
   - Main categorization engine
   - Tries rule matching first (highest priority)
   - Falls back to LLM suggestions for unknowns (if enabled)
   - Flags low-confidence transactions for manual review

4. **LLM Categorizer** (`budget_automation/core/llm_categorizer.py`)
   - Uses Claude API to suggest categories for unknown merchants
   - Returns category, subcategory, confidence score, and rationale
   - Only used when rule matching fails and ANTHROPIC_API_KEY is set

5. **CSV Parser** (`budget_automation/core/csv_parser.py`)
   - Parses Chase CSV exports (both checking and credit card formats)
   - Normalizes merchants using merchant_normalizer
   - Creates SHA256 hash for deduplication

### Database Schema

**Key Tables**:
- `taxonomy_categories` / `taxonomy_subcategories`: Budget taxonomy (17 categories, 110+ subcategories)
- `accounts`: Bank accounts (checking, credit, savings)
- `transactions`: Core transaction data with categorization metadata
- `merchant_rules`: Auto-categorization rules (simple and composite)
- `tag_overrides`: Manual category changes that can be promoted to rules
- `tag_events`: Audit log for categorization decisions

**Important Fields**:
- `transactions.merchant_norm`: Normalized merchant name for rule matching
- `transactions.merchant_detail`: Additional detail for composite rules (extracted by normalizer, stored in `merchant_raw` field)
- `transactions.source_row_hash`: SHA256 hash for deduplication
- `transactions.tag_confidence`: Confidence score (0.0-1.0)
- `transactions.needs_review`: Boolean flag for review queue
- `merchant_rules.match_detail`: For composite rules (SQ + business, Zelle + payee)
- `merchant_rules.priority`: Lower number = higher priority (10 = manual, 50 = composite, 100 = learned)

**Note**: The schema uses `merchant_raw` to store the detail extracted by the normalizer. When querying or importing, this detail is passed as `merchant_detail` to the rule matcher.

### Rule Matching Strategy

**Priority Order** (lower priority number = matched first):
1. **Manual rules** (priority 10): User-defined overrides
   - Example: "EAST PARK BEVERAGE" → Food & Drink/Alcohol
2. **Composite rules** (priority 50): Payment processor + business/payee
   - Example: "SQ" + "BREADS BAKERY" → Food & Drink/Coffee
   - Example: "ZELLE TO" + "DEVI DAYCARE" → Baby/Daycare
3. **Learned rules** (priority 100): Generated from historical analysis
   - Example: "AMAZON" → Shopping/Amazon (99.4% confidence)

**Why Composite Rules?**
Payment processors (Square, Zelle, Toast) are used by many different businesses. A simple rule like "SQ → Coffee" would be wrong for "SQ *THERAPIST OFFICE". Composite rules match both the processor AND the specific business name.

### File Structure

```
budget_automation/
├── cli/
│   ├── init_db.py          # budget-init command
│   └── import_csv.py       # budget-import command
├── core/
│   ├── categorization_orchestrator.py  # Main categorization engine
│   ├── rule_matcher.py                 # Rule matching logic
│   ├── llm_categorizer.py              # Claude API integration
│   ├── merchant_normalizer.py          # Clean merchant names
│   └── csv_parser.py                   # Parse Chase CSVs
├── db/
│   └── db_schema.sql                   # Database schema
└── utils/
    └── db_connection.py                # Database connection helper

data/
├── taxonomy/
│   └── taxonomy.json                   # Budget categories (17 categories, 110+ subcategories)
└── rules/
    ├── learned_rules.sql               # 196 rules from historical analysis
    └── manual_rules.sql                # 3 manual high-priority rules

tests/
└── (test files)
```

## Working with Transactions

### Transaction Flow

1. **Import**: CSV → Parsed → Merchant normalized → SHA256 hash created
2. **Categorization**: Rule match → LLM suggestion (optional) → Review queue
3. **Review**: User categorizes → Optional rule creation
4. **Future imports**: New transactions auto-categorized by rules

### Adding New Rules

**Manual rule creation** (for specific overrides):
```python
# In budget_automation/core/rule_matcher.py, add to create_manual_rules():
{
    'rule_pack': 'manual',
    'priority': 10,
    'match_type': 'exact',
    'match_value': 'MERCHANT_NAME',
    'match_detail': None,  # or 'BUSINESS_NAME' for composite
    'category': 'Category Name',
    'subcategory': 'Subcategory Name',
    'is_active': True,
    'created_by': 'manual',
    'notes': 'Explanation',
}
```

**Database insertion** (for programmatic rules):
```sql
INSERT INTO merchant_rules (rule_pack, priority, match_type, match_value, match_detail, category, subcategory, is_active, created_by, notes)
VALUES ('manual', 10, 'exact', 'MERCHANT', 'DETAIL', 'Category', 'Subcategory', TRUE, 'manual', 'Note');
```

### Merchant Normalization Patterns

The normalizer recognizes these patterns:

- **Amazon**: `"AMZN Mktp US*123"` → `("AMAZON", None)`
- **Square**: `"SQ *BREADS BAKERY"` → `("SQ", "BREADS BAKERY")`
- **Toast**: `"TST* RESTAURANT NAME"` → `("TST", "RESTAURANT NAME")`
- **Zelle**: `"Zelle payment to John Smith"` → `("ZELLE TO", "JOHN SMITH")`
- **Zelle from**: `"Zelle Transfer Conf# 123 Robert Dienstag"` → `("ZELLE FROM", "ROBERT DIENSTAG")`
- **Gas stations**: Keeps specific brand (Exxon, Shell, BP, Costco Gas)
- **MTA**: Various patterns → `("MTA SUBWAY", None)` or `("MTA", None)`

When adding new normalization patterns, update `merchant_normalizer.py:normalize_merchant()`.

## Important Implementation Notes

### Deduplication
- All transactions are hashed (SHA256) based on: date, description, amount, account
- `source_row_hash` field ensures safe re-imports
- Same CSV can be imported multiple times without duplicates

### Taxonomy Structure
- 17 top-level categories defined in `data/taxonomy/taxonomy.json`
- 110+ subcategories specific to actual spending patterns
- Categories are referenced by foreign key in rules and transactions
- Adding new categories requires updating taxonomy.json and running database seed

### LLM Integration
- Optional: Only used if `ANTHROPIC_API_KEY` is set in .env
- Falls back gracefully if API key missing or API fails
- Confidence scores determine if transaction needs manual review
- Review threshold defaults to 0.90 (90% confidence)

### Docker Configuration
- PostgreSQL runs on port 5433 (not 5432) to avoid local conflicts
- Database credentials are in docker-compose.yml (NOT production-safe)
- Data persists in Docker volume `postgres_data`
- pgAdmin available via `--profile tools` flag

### Testing Strategy
- Merchant normalizer has comprehensive test suite (19/19 tests passing)
- Test files use pytest framework
- Rule matcher and orchestrator have built-in test functions
- Run tests before committing changes

## Common Tasks

### Add a new merchant normalization rule
1. Update `normalize_merchant()` in `budget_automation/core/merchant_normalizer.py`
2. Add test case to verify pattern
3. Run tests: `pytest tests/test_merchant_normalizer.py`

### Change rule priority
- Lower priority number = matched first
- Standard priorities: 10 (manual), 50 (composite), 100 (learned)
- Update `merchant_rules.priority` in database

### Debug categorization
- Check orchestrator stats with `.print_stats()`
- Review rule matcher stats with `.print_stats()`
- Query `tag_events` table for audit trail
- Use `--dry-run` flag to preview without importing

### Add new CSV format
1. Create parser in `budget_automation/core/csv_parser.py`
2. Follow pattern from `parse_chase_checking()` and `parse_chase_credit()`
3. Return list of dicts with required fields
4. Update `import_csv.py` to detect new format

## Environment Variables

Required in `.env`:
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: Database connection
- `ANTHROPIC_API_KEY`: Optional, for LLM categorization
- `REVIEW_THRESHOLD`: Default 0.90 (90% confidence)
- `ENABLE_LLM`: Default true

## Known Issues and Gotchas

1. **Port Conflict**: Database runs on 5433, not 5432 (to avoid local PostgreSQL conflicts)
2. **merchant_detail Storage**: Detail is extracted by normalizer but stored in `merchant_raw` field in database
3. **Rule Order**: Composite rules must have LOWER priority number than learned rules to be matched first
4. **Taxonomy Changes**: Updating taxonomy.json requires re-running seed script
5. **Hash Collision**: Extremely rare, but SHA256 hash assumes no identical transactions on same day
