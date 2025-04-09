import os
from dotenv import load_dotenv
import json
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", ""))
DB_URI = os.getenv("DB_URI", "sqlite:///telegram_assistant.db") 