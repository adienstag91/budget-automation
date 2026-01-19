"""
Database connection utilities
"""
import os
import psycopg2
from typing import Optional
from dotenv import load_dotenv


# Load environment variables
load_dotenv()


def get_db_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None
):
    """
    Get database connection using environment variables or provided values
    
    Args:
        host: Database host (default: from DB_HOST env var)
        port: Database port (default: from DB_PORT env var)
        database: Database name (default: from DB_NAME env var)
        user: Database user (default: from DB_USER env var)
        password: Database password (default: from DB_PASSWORD env var)
        
    Returns:
        psycopg2 connection object
    """
    return psycopg2.connect(
        host=host or os.getenv('DB_HOST', 'localhost'),
        port=port or int(os.getenv('DB_PORT', '5432')),
        database=database or os.getenv('DB_NAME', 'budget_db'),
        user=user or os.getenv('DB_USER', 'budget_user'),
        password=password or os.getenv('DB_PASSWORD', 'budget_password_local_dev')
    )


def test_connection() -> bool:
    """
    Test database connection
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
