import os
from dotenv import load_dotenv
import json

load_dotenv()

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", ""))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

USERBOT_SESSION = os.getenv("USERBOT_SESSION", "user_session")

MONITORED_CHATS = json.loads(os.getenv("MONITORED_CHATS", "[]")) 

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")
LINEAR_TEAM_MAPPING = json.loads(os.getenv("LINEAR_TEAM_MAPPING", "{}"))

DB_URI = os.getenv("DB_URI", "sqlite:///telegram_assistant.db")

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", ""))

REMINDER_INTERVAL = int(os.getenv("REMINDER_INTERVAL", "3600"))
SUMMARY_HOUR = int(os.getenv("SUMMARY_HOUR", "18"))

DOWNLOADS_DIR = os.getenv("DOWNLOADS_DIR", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True) 