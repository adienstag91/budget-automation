# Budget Automation 💰

An intelligent budgeting system that learns from your historical spending patterns to automatically categorize transactions with 90%+ accuracy.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🎯 Features

- **90%+ Auto-Categorization** - Learns from 196 rules generated from your spending history
- **Smart Pattern Recognition** - Handles payment processors (Square, Zelle) with composite rules
- **AI Suggestions** - Optional Claude API integration for unknown merchants
- **Deduplication** - Safe to re-import CSVs, no duplicates
- **Docker-Based** - Isolated PostgreSQL database, easy setup
- **Learning Loop** - Categorize once, automated forever

## 🚀 Quick Start

### Prerequisites

- **Docker Desktop** ([Download](https://www.docker.com/products/docker-desktop/))
- **Python 3.10+**
- **Chase Bank** (currently supports Chase CSV formats)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/budget-automation.git
cd budget-automation

# 2. Install Python package
pip install -e .

# 3. Copy environment template
cp .env.example .env
# Edit .env and add your Anthropic API key (optional)

# 4. Start Docker database
docker-compose up -d

# 5. Initialize database
budget-init

# 6. Import your first CSV
budget-import /path/to/chase_export.csv
```

### Expected Results

```
📊 CATEGORIZATION STATISTICS
Total transactions: 111

✅ Categorization Results:
  • Rule match: 89 (80.2%)
  • LLM suggestion: 15 (13.5%)

📋 Review Status:
  • High confidence (≥90%): 101 (91.0%)
  • Needs review: 10 (9.0%)
```

## 📁 Project Structure

```
budget-automation/
├── src/budget_automation/          # Main package
│   ├── cli/                        # Command-line scripts
│   │   ├── init_db.py              # Database initialization
│   │   └── import_csv.py           # CSV import
│   ├── core/                       # Core logic
│   │   ├── merchant_normalizer.py  # Clean merchant names
│   │   ├── csv_parser.py           # Parse Chase CSVs
│   │   ├── rule_matcher.py         # Apply categorization rules
│   │   ├── llm_categorizer.py      # AI suggestions
│   │   └── categorization_orchestrator.py  # Main engine
│   ├── db/                         # Database
│   │   └── db_schema.sql           # PostgreSQL schema
│   └── utils/                      # Utilities
│       └── db_connection.py        # Database connections
├── data/                           # Configuration & rules
│   ├── taxonomy/                   # Budget categories
│   ├── rules/                      # Learned + manual rules
│   ├── analysis/                   # Learning results
│   ├── uploads/                    # CSV imports (gitignored)
│   └── exports/                    # Exports (gitignored)
├── docs/                           # Documentation
├── tests/                          # Unit tests
├── docker-compose.yml              # Docker setup
├── setup.py                        # Package configuration
└── requirements.txt                # Dependencies
```

## 🧠 How It Works

### 1. Merchant Normalization

Raw bank descriptions are cleaned and parsed:

```
"AMZN Mktp US*UE1F70L13" → "AMAZON"
"SQ *BREADS BAKERY" → "SQ" + detail: "BREADS BAKERY"
"Zelle payment to Devi Daycare" → "ZELLE TO" + detail: "DEVI DAYCARE"
```

### 2. Rule Matching (Priority Order)

1. **Manual rules** (priority 10) - Your explicit overrides
2. **Composite rules** (priority 50) - Business-specific (e.g., SQ + business name)
3. **Learned rules** (priority 100) - From historical analysis

### 3. LLM Fallback (Optional)

If no rule matches, Claude suggests a category with confidence score.

### 4. Review Queue

Low-confidence transactions go to review queue for manual categorization, which creates new rules.

## 🔧 Usage

### Initialize Database

```bash
budget-init
```

Creates schema, loads taxonomy, and imports 199 rules.

### Import Transactions

```bash
# Basic import
budget-import checking.csv

# Auto-detect CSV type
budget-import transactions.csv

# Disable LLM (rules only)
budget-import transactions.csv --no-llm

# Dry run (preview without importing)
budget-import transactions.csv --dry-run
```

### Using as Python Module

```python
from budget_automation import normalize_merchant
from budget_automation.core.csv_parser import parse_chase_csv

# Normalize a merchant
merchant, detail = normalize_merchant("SQ *BREADS BAKERY")
# Returns: ("SQ", "BREADS BAKERY")

# Parse a CSV
transactions = parse_chase_csv("checking.csv")
```

## 🐳 Docker Commands

```bash
# Start database
docker-compose up -d

# Stop database
docker-compose stop

# View logs
docker-compose logs -f

# Reset database (deletes all data)
docker-compose down -v

# Access database directly
docker-compose exec postgres psql -U budget_user -d budget_db

# Enable pgAdmin (web UI)
docker-compose --profile tools up -d
# Then visit http://localhost:5050
```

## ⚙️ Configuration

### Environment Variables (.env)

```bash
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=budget_db
DB_USER=budget_user
DB_PASSWORD=budget_password_local_dev

# Anthropic API (optional)
ANTHROPIC_API_KEY=your-key-here

# Categorization
REVIEW_THRESHOLD=0.90
ENABLE_LLM=true
```

### Taxonomy (data/taxonomy/taxonomy.json)

Your budget categories. Modify to match your spending:

```json
{
  "categories": [
    {
      "name": "Groceries",
      "subcategories": ["Stop & Shop", "Trader Joes", "Costco"]
    }
  ]
}
```

## 📊 Generated Rules

### From Your Data (196 rules)

The system analyzed 5,863 historical transactions and generated:

- **AMAZON** → Shopping/Amazon (99.4% confidence)
- **STOP & SHOP** → Groceries/Stop & Shop (98.9%)
- **MTA SUBWAY** → Travel/MTA (100%)
- **COSTCO GAS** → Bills & Utilities/Car Gas (95.2%)

### Manual Priority Rules (3 rules)

- **ZELLE TO + DEVI DAYCARE** → Baby/Daycare
- **ZELLE FROM + ROBERT DIENSTAG** → Income/Family Support
- **EAST PARK BEVERAGE** → Food & Drink/Alcohol

## 🎓 Key Innovations

### Composite Rules

Solves the payment processor problem:

```
Problem: "Square" appears for coffee, therapy, restaurants
Solution: Match on merchant + business name

SQ + "BREADS BAKERY" → Food & Drink/Coffee
SQ + "HEADWAY" → Health & Wellness/Therapy
```

### Learning from History

Built 196 rules from your actual spending patterns, not generic categories.

### Deduplication

SHA256 hash prevents duplicates. Safe to re-import same CSV.

## 📈 Results

**Time Savings:**
- Before: 1 hour/month manual categorization
- After: 5 minutes/month (new merchants only)
- **92% reduction in manual work**

**Accuracy:**
- 75-80% auto-categorized immediately
- 90%+ after reviewing ~50 Square/Zelle merchants once
- <5% ongoing manual effort

## 🧪 Development

### Run Tests

```bash
# Install dev dependencies
pip install -e .[dev]

# Run tests
pytest

# With coverage
pytest --cov=budget_automation
```

### Code Formatting

```bash
# Format code
black src/

# Lint
flake8 src/

# Type check
mypy src/
```

## 📚 Documentation

- **[Docker Setup Guide](docs/DOCKER_SETUP.md)** - Docker basics + troubleshooting
- **[Architecture](docs/ARCHITECTURE.md)** - System design
- **[Square Merchant Learning](docs/SQUARE_MERCHANT_LEARNING.md)** - Composite rules

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Run `black` and `flake8`
5. Submit a pull request

## 📝 License

MIT License - see [LICENSE](LICENSE) file

## 🙏 Acknowledgments

- Built with [Anthropic Claude](https://www.anthropic.com/)
- Inspired by manual budgeting pain 😅

## 🔗 Links

- **Repository:** https://github.com/yourusername/budget-automation
- **Issues:** https://github.com/yourusername/budget-automation/issues
- **Anthropic API:** https://console.anthropic.com/

---

**Built with ❤️ to eliminate tedious budget categorization**
