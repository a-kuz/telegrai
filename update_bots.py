import sqlite3
import sys
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('bot_updater')

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

def update_bot_users():
    """Mark known bot users in the database"""
    try:
        # Connect to SQLite database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # List of common bot usernames or name patterns
        bot_patterns = [
            "%bot%",           # Any username with "bot" in it
            "t.me/assistant_%",  # Telegram assistant bots
            "BotFather",       # Telegram's BotFather
            "%_bot"            # Names ending with _bot
        ]
        
        # Check User table and mark bots
        for pattern in bot_patterns:
            # First try matching first_name or last_name
            cursor.execute("""
                UPDATE users 
                SET is_bot = 1 
                WHERE (first_name LIKE ? OR last_name LIKE ? OR username LIKE ?)
            """, (pattern, pattern, pattern))
            
            updated = cursor.rowcount
            if updated > 0:
                logger.info(f"Marked {updated} users as bots with pattern '{pattern}'")
        
        # Specific check for t.me links in first_name or last_name
        cursor.execute("""
            UPDATE users 
            SET is_bot = 1 
            WHERE first_name LIKE 't.me/%' OR last_name LIKE 't.me/%' OR username LIKE 't.me/%'
        """)
        updated = cursor.rowcount
        if updated > 0:
            logger.info(f"Marked {updated} users as bots with t.me links")
        
        # Commit changes
        conn.commit()
        logger.info("Bot user update completed successfully")
        
        # Print current bot users for verification
        cursor.execute("SELECT user_id, first_name, last_name, username, is_bot FROM users WHERE is_bot = 1")
        bots = cursor.fetchall()
        logger.info(f"Current bot users in database ({len(bots)}):")
        for bot in bots:
            logger.info(f"Bot ID {bot[0]}: {bot[1]} {bot[2]} (@{bot[3]})")
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    logger.info("Starting bot user update")
    update_bot_users()
    logger.info("Bot user update finished") 