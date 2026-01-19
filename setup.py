"""
Budget Automation - Setup Configuration
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="budget-automation",
    version="1.0.0",
    author="Andrew",
    description="Intelligent budgeting system that learns from spending patterns",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/budget-automation",  # Update with your repo
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.10",
    install_requires=[
        "psycopg2-binary>=2.9.9",
        "anthropic>=0.39.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.3",
            "pytest-cov>=4.1.0",
            "black>=23.12.1",
            "flake8>=7.0.0",
            "mypy>=1.8.0",
        ],
        "ui": [
            "streamlit>=1.29.0",
            "pandas>=2.1.4",
            "plotly>=5.18.0",
            "altair>=5.2.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "budget-init=budget_automation.cli.init_db:main",
            "budget-import=budget_automation.cli.import_csv:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Office/Business :: Financial",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    include_package_data=True,
    package_data={
        "budget_automation": [
            "db/*.sql",
        ],
    },
)
