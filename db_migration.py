import sqlite3
import sys
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('db_migration')

# Get the database file path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from telegram_ai_assistant.config import DB_URI
    # Extract SQLite file path from URI
    if DB_URI.startswith('sqlite:///'):
        db_path = DB_URI[10:]
    else:
        db_path = 'telegram_assistant.db'  # Default path
except ImportError:
    db_path = 'telegram_assistant.db'  # Default path

logger.info(f"Using database at: {db_path}")

def run_migration():
    """Add new columns to the unanswered_questions table"""
    try:
        # Connect to SQLite database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if sender_id column exists
        cursor.execute("PRAGMA table_info(unanswered_questions)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add sender_id column if it doesn't exist
        if 'sender_id' not in columns:
            logger.info("Adding sender_id column to unanswered_questions table")
            cursor.execute("ALTER TABLE unanswered_questions ADD COLUMN sender_id INTEGER")
        
        # Add is_bot column if it doesn't exist
        if 'is_bot' not in columns:
            logger.info("Adding is_bot column to unanswered_questions table")
            cursor.execute("ALTER TABLE unanswered_questions ADD COLUMN is_bot BOOLEAN DEFAULT 0")
        
        # Add answered_at column if it doesn't exist
        if 'answered_at' not in columns:
            logger.info("Adding answered_at column to unanswered_questions table")
            cursor.execute("ALTER TABLE unanswered_questions ADD COLUMN answered_at DATETIME")
        
        # Check User table columns
        cursor.execute("PRAGMA table_info(users)")
        user_columns = [column[1] for column in cursor.fetchall()]
        
        # Add is_bot column to User table if it doesn't exist
        if 'is_bot' not in user_columns:
            logger.info("Adding is_bot column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN is_bot BOOLEAN DEFAULT 0")
        
        # Add created_at column to User table if it doesn't exist
        if 'created_at' not in user_columns:
            logger.info("Adding created_at column to users table")
            current_time = datetime.utcnow().isoformat()
            cursor.execute(f"ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT '{current_time}'")
            
            # Update existing rows to have the current timestamp
            cursor.execute(f"UPDATE users SET created_at = '{current_time}'")
            
        # Add username column to User table if it doesn't exist
        if 'username' not in user_columns:
            logger.info("Adding username column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN username VARCHAR(255)")
        
        # Check Message table for is_bot column
        cursor.execute("PRAGMA table_info(messages)")
        message_columns = [column[1] for column in cursor.fetchall()]
        
        # Add is_bot column to Message table if it doesn't exist
        if 'is_bot' not in message_columns:
            logger.info("Adding is_bot column to messages table")
            cursor.execute("ALTER TABLE messages ADD COLUMN is_bot BOOLEAN DEFAULT 0")
        
        # Commit changes
        conn.commit()
        logger.info("Database migration completed successfully")
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    logger.info("Starting database migration")
    run_migration()
    logger.info("Migration finished") 