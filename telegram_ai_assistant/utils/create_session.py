import sys
import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, USERBOT_SESSION
async def main():
    """Generate a session file for Telegram userbot without disconnecting other sessions."""
    print("Creating Telegram session...")
    print(f"API ID: {TELEGRAM_API_ID}")
    print(f"Session name: {USERBOT_SESSION}")
    client = TelegramClient(
        USERBOT_SESSION, 
        TELEGRAM_API_ID, 
        TELEGRAM_API_HASH,
        device_model="Desktop",
        system_version="Windows 10",
        app_version="1.0.0"
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Please log in to Telegram with your account")
            phone = input("Enter your phone number (with country code, e.g., +12345678901): ")
            await client.send_code_request(phone)
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    code = input(f"Enter the code you received (attempt {attempt+1}/{max_attempts}): ")
                    await client.sign_in(phone, code)
                    break
                except PhoneCodeInvalidError:
                    if attempt < max_attempts - 1:
                        print("Invalid code. Please try again.")
                    else:
                        print("Too many invalid code attempts. Exiting.")
                        return
                except SessionPasswordNeededError:
                    password = input("Two-factor authentication is enabled. Please enter your password: ")
                    await client.sign_in(password=password)
                    break
    except Exception as e:
        print(f"Error during authentication: {e}")
        return
    if await client.is_user_authorized():
        print(f"Session file has been created at {USERBOT_SESSION}.session")
        print("Session string (for backup):")
        session_string = StringSession.save(client.session)
        print(session_string)
        print("\nYou can now run the main application.")
    else:
        print("Failed to authenticate.")
    await client.disconnect()
if __name__ == "__main__":
    asyncio.run(main()) 