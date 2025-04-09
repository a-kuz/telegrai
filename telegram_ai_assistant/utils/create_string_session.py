import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

# Your API credentials - replace these with your actual values or read from env
API_ID = 27114734
API_HASH = "7ffa5afbd7f3a5a7cd4dd4232dbb1bac"

async def main():
    """Generate a string session for Telegram authentication."""
    print("Generating Telegram string session...")
    
    # Create a client with temporary string session
    async with TelegramClient(
        StringSession(), 
        API_ID, 
        API_HASH,
        device_model="Desktop",
        system_version="Windows 10",
        app_version="1.0.0"
    ) as client:
        # Just print the session string
        print("\nYour string session:\n")
        print(client.session.save())
        print("\nSave this string safely - you'll need to use it in the Telegram client.")
        print("Update the SESSION_STRING variable in telegram_ai_assistant/userbot/telegram_client.py with this value.")
        print("\nWarning: Anyone with this string can log in as you!")

if __name__ == "__main__":
    asyncio.run(main()) 