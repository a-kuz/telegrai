import os
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

# Bot token from BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Admin user ID
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", ""))

# DB URI - needed to access the same database
DB_URI = os.getenv("DB_URI", "sqlite:///telegram_assistant.db") 