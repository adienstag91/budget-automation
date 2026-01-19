# Budget Automation - Docker Setup & Quick Start

## What is Docker? 🐳

**Docker** is a tool that lets you run software in isolated "containers" - think of them as lightweight, self-contained environments. For this project, we're using Docker to run PostgreSQL (our database) without needing to install it directly on your computer.

### Benefits of Docker:
- ✅ **No installation mess** - Postgres runs in a container, not on your machine
- ✅ **Consistent environment** - Works the same on Mac, Windows, Linux
- ✅ **Easy cleanup** - Delete the container, everything's gone
- ✅ **Isolated** - Won't interfere with other software
- ✅ **Reproducible** - Same setup every time

### Docker Concepts:
- **Image**: A blueprint (like "PostgreSQL 16")
- **Container**: A running instance of an image (your actual database)
- **Volume**: Persistent storage (your data survives container restarts)
- **docker-compose**: Tool to manage multiple containers with one config file

## Prerequisites

### 1. Install Docker Desktop

**Mac:**
```bash
# Download from: https://www.docker.com/products/docker-desktop/
# Or with Homebrew:
brew install --cask docker
```

**Windows:**
```bash
# Download from: https://www.docker.com/products/docker-desktop/
```

**Linux:**
```bash
# Ubuntu/Debian:
sudo apt-get update
sudo apt-get install docker.io docker-compose

# Start Docker service:
sudo systemctl start docker
sudo systemctl enable docker
```

### 2. Verify Docker is Running

```bash
docker --version
# Should show: Docker version 24.x.x or higher

docker-compose --version
# Should show: Docker Compose version 2.x.x or higher
```

### 3. Install Python Dependencies

```bash
pip install psycopg2-binary anthropic --break-system-packages
```

## Quick Start (5 Minutes)

### Step 1: Start Docker Containers

```bash
cd budget-automation/infra
docker-compose up -d
```

**What this does:**
- `-d` means "detached" (runs in background)
- Starts PostgreSQL on port 5432
- Creates a persistent volume for your data
- Database will be empty initially

**Expected output:**
```
Creating network "budget_network" with the default driver
Creating volume "infra_postgres_data" with local driver
Creating budget_postgres ... done
```

**Verify it's running:**
```bash
docker-compose ps
```

You should see:
```
Name                 State    Ports
budget_postgres      Up       0.0.0.0:5432->5432/tcp
```

### Step 2: Initialize Database

```bash
cd ../pipeline
python init_database.py
```

**What this does:**
1. Creates all tables (taxonomy, transactions, rules, etc.)
2. Loads your 17 categories + 110 subcategories
3. Loads 196 learned rules from your historical data
4. Loads 3 manual high-priority rules (Zelle, East Park)
5. Creates default Chase accounts

**Expected output:**
```
🚀 BUDGET DATABASE INITIALIZATION
================================================================================
🔌 Connecting to database...
   ✅ Connected

📄 Creating database schema
   ✅ Success

📚 Loading taxonomy from .../taxonomy.json
   ✅ Loaded 17 categories, 110 subcategories

🏦 Creating default accounts
   ✅ Created 2 accounts

📄 Loading learned rules (from historical data)
   ✅ Success

📄 Loading manual rules (high-priority)
   ✅ Success

================================================================================
📊 DATABASE SUMMARY
================================================================================
Categories: 17
Subcategories: 110
Accounts: 2

Merchant Rules:
  • learned: 196 rules (0 composite)
  • manual: 3 rules (2 composite)
  Total: 199 rules

Transactions: 0
================================================================================

✅ Database initialization complete!
```

### Step 3: Import Your First CSV

```bash
# Import your December checking CSV
python import_transactions.py /path/to/checking_1225.CSV

# Or import credit card CSV
python import_transactions.py /path/to/credit_1225.CSV
```

**What this does:**
1. Parses the Chase CSV
2. Normalizes merchant names
3. Applies rules to categorize transactions
4. Uses LLM for unknowns (if API key set)
5. Inserts into database
6. Shows statistics

**Expected output:**
```
📥 TRANSACTION IMPORT
================================================================================
CSV File: checking_1225.CSV
CSV Type: auto
LLM Enabled: True
================================================================================

🔌 Connecting to database...
   ✅ Connected

📚 Loading rules from database...
   ✅ Loaded 199 active rules

📄 Parsing CSV file...
   ✅ Parsed 43 transactions from checking CSV

🧠 Initializing categorization engine...
   ✅ Ready

🏷️  Categorizing 43 transactions...

================================================================================
📊 CATEGORIZATION STATISTICS
================================================================================
Total transactions: 43

✅ Categorization Results:
  • Rule match: 38 (88.4%)
  • LLM suggestion: 3 (7.0%)

📋 Review Status:
  • High confidence (≥90%): 40 (93.0%)
  • Needs review: 3 (7.0%)
================================================================================

💾 Inserting into database...
   ✅ Inserted: 43

⚠️  3 transactions need review:
   • UNKNOWN MERCHANT NYC                                  $15.00
   • NEW COFFEE SHOP                                       $8.50
   • RANDOM STORE                                          $25.00

✅ Import complete!
```

## Docker Commands Cheat Sheet

### Starting & Stopping

```bash
# Start containers (in background)
docker-compose up -d

# Stop containers (keeps data)
docker-compose stop

# Stop and remove containers (keeps data in volume)
docker-compose down

# Stop, remove containers AND delete data
docker-compose down -v
```

### Viewing Logs

```bash
# View all logs
docker-compose logs

# Follow logs in real-time
docker-compose logs -f

# View only Postgres logs
docker-compose logs postgres
```

### Database Management

```bash
# Connect to database directly
docker-compose exec postgres psql -U budget_user -d budget_db

# Backup database
docker-compose exec postgres pg_dump -U budget_user budget_db > backup.sql

# Restore database
docker-compose exec -T postgres psql -U budget_user budget_db < backup.sql

# Check database size
docker-compose exec postgres psql -U budget_user -d budget_db -c "SELECT pg_size_pretty(pg_database_size('budget_db'));"
```

### Container Info

```bash
# List running containers
docker-compose ps

# View resource usage
docker stats

# View container details
docker-compose exec postgres env
```

## Optional: pgAdmin (Database GUI)

Want a visual interface for your database?

### 1. Enable pgAdmin

```bash
cd infra
docker-compose --profile tools up -d
```

### 2. Access pgAdmin

Open browser: http://localhost:5050

**Login:**
- Email: admin@budget.local
- Password: admin

### 3. Connect to Postgres

1. Click "Add New Server"
2. **General tab:**
   - Name: Budget DB
3. **Connection tab:**
   - Host: postgres
   - Port: 5432
   - Username: budget_user
   - Password: budget_password_local_dev
   - Save password: ✓

Now you can browse tables, run queries, view data!

## Troubleshooting

### Port 5432 Already in Use

If you have Postgres installed locally:

**Option 1: Stop local Postgres**
```bash
# Mac:
brew services stop postgresql

# Ubuntu:
sudo systemctl stop postgresql
```

**Option 2: Use different port**

Edit `infra/docker-compose.yml`:
```yaml
ports:
  - "5433:5432"  # Change 5432 to 5433
```

Then update connection strings to use port 5433.

### Cannot Connect to Database

```bash
# Check if container is running
docker-compose ps

# If not running, start it
docker-compose up -d

# Check logs for errors
docker-compose logs postgres

# Restart container
docker-compose restart postgres
```

### Database Schema Changes

If you modify `db_schema.sql`:

```bash
# Option 1: Recreate database (loses all data)
docker-compose down -v
docker-compose up -d
python init_database.py

# Option 2: Apply changes manually
docker-compose exec postgres psql -U budget_user -d budget_db
# Then run your ALTER TABLE commands
```

### Reset Everything

```bash
# Stop and remove all containers and volumes
cd infra
docker-compose down -v

# Start fresh
docker-compose up -d
cd ../pipeline
python init_database.py
```

## Environment Variables (Optional)

For LLM categorization, set your Anthropic API key:

```bash
# Mac/Linux:
export ANTHROPIC_API_KEY='your-api-key-here'

# Windows:
set ANTHROPIC_API_KEY=your-api-key-here

# Or create a .env file in project root:
echo "ANTHROPIC_API_KEY=your-api-key-here" > .env
```

**Get an API key:** https://console.anthropic.com/

## Directory Structure

```
budget-automation/
├── infra/
│   └── docker-compose.yml       ← Docker configuration
├── pipeline/
│   ├── init_database.py         ← Setup script
│   ├── import_transactions.py   ← CSV import
│   ├── merchant_normalizer.py   ← Merchant cleanup
│   ├── csv_parser.py            ← Chase CSV parser
│   ├── rule_matcher.py          ← Rule engine
│   ├── llm_categorizer.py       ← AI suggestions
│   └── categorization_orchestrator.py  ← Main brain
├── data/
│   ├── taxonomy.json            ← Your categories
│   ├── learned_rules.sql        ← 196 auto-generated rules
│   └── manual_rules.sql         ← 3 priority rules
└── app/                         ← Streamlit UI (Phase 2)
```

## What's Next?

Now that Docker is running and your database is set up:

1. **Import your December CSVs** to test the system
2. **Review the results** - see what got auto-categorized
3. **Add missing rules** for any merchants that need review
4. **Phase 2**: Build the Streamlit UI for easier imports and review

---

**Docker Benefits Recap:**
- ✅ Database running in isolated container
- ✅ Easy to start/stop/reset
- ✅ No conflicts with other software
- ✅ Data persists in volume
- ✅ Can backup/restore easily
- ✅ Works the same everywhere

**You now know Docker!** 🎉
