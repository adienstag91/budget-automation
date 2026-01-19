# Git Repository Setup Guide

Complete guide to organizing your project and creating a Git repository.

## 📁 Project Structure (Final)

```
budget-automation/
├── .env.example                # Environment template (SAFE TO COMMIT)
├── .gitignore                  # Git ignore rules (SAFE TO COMMIT)
├── LICENSE                     # MIT License (SAFE TO COMMIT)
├── MANIFEST.in                 # Package data manifest
├── README.md                   # Project README (SAFE TO COMMIT)
├── docker-compose.yml          # Docker configuration (SAFE TO COMMIT)
├── requirements.txt            # Python dependencies (SAFE TO COMMIT)
├── setup.py                    # Package setup (SAFE TO COMMIT)
│
├── src/budget_automation/      # Main Python package
│   ├── __init__.py
│   ├── cli/                    # Command-line tools
│   │   ├── __init__.py
│   │   ├── init_db.py         # Database initialization
│   │   └── import_csv.py      # CSV import
│   ├── core/                   # Core categorization logic
│   │   ├── __init__.py
│   │   ├── categorization_orchestrator.py
│   │   ├── csv_parser.py
│   │   ├── llm_categorizer.py
│   │   ├── merchant_normalizer.py
│   │   └── rule_matcher.py
│   ├── db/                     # Database
│   │   ├── __init__.py
│   │   └── db_schema.sql      # Schema (SAFE TO COMMIT)
│   └── utils/                  # Utilities
│       ├── __init__.py
│       └── db_connection.py
│
├── data/                       # Data files
│   ├── taxonomy/              
│   │   └── taxonomy.json       # Categories (SAFE TO COMMIT)
│   ├── rules/
│   │   ├── learned_rules.sql   # Generated rules (SAFE TO COMMIT)
│   │   └── manual_rules.sql    # Manual rules (SAFE TO COMMIT)
│   ├── analysis/
│   │   └── learned_analysis.json  # Analysis (SAFE TO COMMIT)
│   ├── uploads/                # CSV uploads (GITIGNORED)
│   │   └── .gitkeep
│   └── exports/                # Exports (GITIGNORED)
│       └── .gitkeep
│
├── docs/                       # Documentation (SAFE TO COMMIT)
│   ├── ARCHITECTURE.md
│   ├── COMPREHENSIVE_SUMMARY.md
│   ├── DOCKER_SETUP_GUIDE.md
│   └── SQUARE_MERCHANT_LEARNING.md
│
├── tests/                      # Unit tests (SAFE TO COMMIT)
│   └── __init__.py
│
├── scripts/                    # Helper scripts (SAFE TO COMMIT)
│
└── backups/                    # Database backups (GITIGNORED)
    └── .gitkeep
```

## 🚀 Step-by-Step Setup

### 1. Navigate to Project Directory

```bash
cd /outputs/budget-automation-project
```

### 2. Initialize Git Repository

```bash
# Initialize git
git init

# Verify .gitignore is in place
cat .gitignore

# Check what will be committed
git status
```

You should see:
- ✅ Source code (src/)
- ✅ Documentation (docs/, README.md)
- ✅ Configuration files (.env.example, docker-compose.yml, etc.)
- ✅ Data files (taxonomy, rules, analysis)
- ❌ NO personal CSVs (data/uploads/)
- ❌ NO .env file (contains API keys)

### 3. Create Initial Commit

```bash
# Stage all files
git add .

# Create initial commit
git commit -m "Initial commit: Budget automation system v1.0

- Automated transaction categorization (90%+ accuracy)
- 196 learned rules from historical data
- Composite rules for payment processors
- Docker-based PostgreSQL setup
- CLI tools for init and import
- Complete documentation"

# Verify commit
git log
```

### 4. Create GitHub Repository

#### Option A: Using GitHub CLI (Recommended)

```bash
# Install gh if needed
# Mac: brew install gh
# Windows: winget install GitHub.cli

# Login to GitHub
gh auth login

# Create repository
gh repo create budget-automation --public --source=. --remote=origin

# Push code
git push -u origin main
```

#### Option B: Using GitHub Web Interface

1. Go to https://github.com/new
2. Repository name: `budget-automation`
3. Description: "Intelligent budgeting system with 90%+ auto-categorization"
4. **Public** or **Private** (your choice)
5. ❌ Do NOT initialize with README (you already have one)
6. Click "Create repository"

Then connect your local repo:

```bash
# Replace 'yourusername' with your GitHub username
git remote add origin https://github.com/yourusername/budget-automation.git

# Push code
git branch -M main
git push -u origin main
```

### 5. Verify on GitHub

Visit your repository and verify:
- ✅ README displays properly
- ✅ Source code is there
- ✅ Documentation in docs/ folder
- ✅ No sensitive data (no .env, no CSV files)

## 🔒 Security Checklist

Before pushing, verify these files are **NOT** in git:

```bash
# Check what's being tracked
git ls-files | grep -E "(\.env$|\.csv|\.CSV|uploads|exports)"

# Should return NOTHING
# If it returns files, they're being tracked (BAD!)
```

If you accidentally committed sensitive files:

```bash
# Remove from git but keep locally
git rm --cached data/uploads/*.csv
git rm --cached .env

# Commit the removal
git commit -m "Remove sensitive files from tracking"

# Verify .gitignore is working
git status
# Should show: "nothing to commit, working tree clean"
```

## 📝 Update README Before Publishing

Edit `README.md` and replace placeholders:

```bash
# Line 5: Update GitHub username
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# setup.py line 14: Update URL
url="https://github.com/YOURUSERNAME/budget-automation",

# README.md bottom: Update links
- **Repository:** https://github.com/YOURUSERNAME/budget-automation
- **Issues:** https://github.com/YOURUSERNAME/budget-automation/issues
```

Then commit the changes:

```bash
git add README.md setup.py
git commit -m "Update repository URLs"
git push
```

## 🏷️ Create First Release (Optional)

```bash
# Tag the release
git tag -a v1.0.0 -m "Release v1.0.0: Initial public release

Features:
- 90%+ automatic categorization
- 196 learned rules from historical data
- Composite rules for payment processors (Square, Zelle)
- Docker-based setup
- CLI tools (budget-init, budget-import)
- Complete documentation"

# Push tag to GitHub
git push origin v1.0.0

# Or use GitHub CLI
gh release create v1.0.0 --title "v1.0.0 - Initial Release" --notes "First public release"
```

## 📦 Package Distribution (Optional)

To publish to PyPI:

```bash
# Install build tools
pip install build twine

# Build package
python -m build

# Check distribution
twine check dist/*

# Upload to PyPI (requires account)
twine upload dist/*
```

Then users can install with:
```bash
pip install budget-automation
```

## 🌿 Branching Strategy

Suggested workflow:

```bash
# Create development branch
git checkout -b develop

# Create feature branches
git checkout -b feature/streamlit-ui
git checkout -b feature/google-sheets-export

# Merge back to develop when done
git checkout develop
git merge feature/streamlit-ui

# Merge to main for releases
git checkout main
git merge develop
git tag v1.1.0
git push --tags
```

## 🔄 Keeping It Updated

### Daily Workflow

```bash
# Make changes to code
# ...

# Check what changed
git status
git diff

# Stage and commit
git add .
git commit -m "Add feature: description"

# Push to GitHub
git push
```

### Adding New Features

```bash
# Create feature branch
git checkout -b feature/dashboard

# Make changes, commit often
git commit -m "Add spending trends chart"
git commit -m "Add category breakdown"

# Push feature branch
git push -u origin feature/dashboard

# Create pull request on GitHub
gh pr create --title "Add Dashboard Feature" --body "Implements spending dashboard with charts"

# After review, merge
gh pr merge
```

## 📊 GitHub Repository Settings

Recommended settings:

### General
- ✅ Issues (for bug reports)
- ✅ Wiki (for extended docs)
- ✅ Discussions (for Q&A)

### Branches
- **Default branch**: `main`
- **Branch protection** (optional):
  - Require pull request reviews
  - Require status checks
  - No force pushes

### Security
- ✅ Enable Dependabot alerts
- ✅ Enable secret scanning
- ❌ Never commit .env files

### Topics (GitHub tags)
Add these topics to make it discoverable:
- `budgeting`
- `finance`
- `automation`
- `postgresql`
- `docker`
- `python`
- `machine-learning`
- `personal-finance`

## 🎯 What's Safe to Commit

### ✅ SAFE (No Personal Data)

- All source code (src/)
- Documentation (docs/, README.md)
- Configuration templates (.env.example)
- Database schema (db_schema.sql)
- Learned rules (learned_rules.sql) *
- Taxonomy (taxonomy.json)
- Docker configuration
- Tests
- .gitignore
- Requirements files

\* Rules contain merchant names but no amounts, dates, or personal info

### ❌ NEVER COMMIT (Personal Data)

- CSV files with transactions
- .env with API keys
- Database dumps
- Exports folder
- Any file with dollar amounts
- Any file with dates + merchants

## 🧪 Test Before Pushing

```bash
# Clone to temp directory to test
cd /tmp
git clone /path/to/budget-automation
cd budget-automation

# Try setup
pip install -e .

# Verify no sensitive data
find . -name "*.csv"  # Should be empty
grep -r "sk-ant-" .   # Should find nothing (API keys)
cat .env              # Should not exist

# If all clear, you're good to push!
```

## 🎉 You're Done!

Your repository is now:
- ✅ Properly structured
- ✅ Documented
- ✅ Secure (no sensitive data)
- ✅ Ready to share
- ✅ Easy to install
- ✅ Professional quality

Share it with:
```
https://github.com/YOURUSERNAME/budget-automation
```

## 💡 Next Steps

1. **Add badges** to README (build status, coverage, etc.)
2. **Write more tests** (increase code coverage)
3. **Add CI/CD** (GitHub Actions for testing)
4. **Create demo** (synthetic data showcase)
5. **Build Streamlit UI** (Phase 2)
6. **Write blog post** about the project
7. **Share on social media** (LinkedIn, Twitter)

Happy coding! 🚀
