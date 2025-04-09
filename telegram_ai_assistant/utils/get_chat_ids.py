import sys
import os
import asyncio
from telethon import TelegramClient
from getpass import getpass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH

async def main():
    print("Telegram Chat ID Finder")
    print("=======================")
    print("This utility helps you find IDs of Telegram chats to monitor.")
    print()
    
    # Check if config has valid values
    use_config = False
    if TELEGRAM_API_ID != "12345" and TELEGRAM_API_HASH != "your_api_hash":
        use_config_input = input("Use API credentials from config.py? (y/n): ").lower()
        use_config = use_config_input == 'y'
    
    # If not using config, prompt for credentials
    if not use_config:
        try:
            api_id = int(input("Enter your Telegram API ID: "))
            api_hash = input("Enter your Telegram API hash: ")
        except ValueError:
            print("Error: API ID must be an integer.")
            return
    else:
        api_id = TELEGRAM_API_ID
        api_hash = TELEGRAM_API_HASH
    
    # Create a temporary session
    session_name = "chat_id_finder_session"
    client = TelegramClient(session_name, api_id, api_hash)
    
    print("\nConnecting to Telegram...")
    await client.start()
    
    # Ensure we're connected
    if not await client.is_user_authorized():
        print("You need to login first!")
        phone = input("Enter your phone number (with country code): ")
        await client.send_code_request(phone)
        code = input("Enter the code you received: ")
        await client.sign_in(phone, code)
    
    print("\nFetching dialogs (chats)...")
    
    # Get all dialogs (conversations)
    dialogs = await client.get_dialogs()
    
    # Display in a way that's easy to read
    print("\n=== YOUR CHATS ===")
    print("\n[GROUPS]")
    for i, dialog in enumerate(dialogs):
        if dialog.is_group or dialog.is_channel:
            chat_id = dialog.id
            # For supergroups and channels, Telegram adds -100 prefix in many API calls
            if dialog.is_channel:  # This includes supergroups
                chat_id_for_monitoring = f"-100{chat_id}".replace('-100-100', '-100')
                print(f"{dialog.name}: {chat_id} (Use this for monitoring: {chat_id_for_monitoring})")
            else:
                print(f"{dialog.name}: {chat_id}")
    
    print("\n[PRIVATE CHATS]")
    for dialog in dialogs:
        if not dialog.is_group and not dialog.is_channel:
            print(f"{dialog.name}: {dialog.id}")
    
    print("\n=== HOW TO USE THESE IDs ===")
    print("1. Copy the IDs of the chats you want to monitor")
    print("2. Add them to the MONITORED_CHATS list in your .env file")
    print("3. Format example: MONITORED_CHATS=[-100123456789,-100987654321]")
    print("Note: For supergroups and channels, use the 'Use this for monitoring' ID")
    
    # Clean up
    await client.disconnect()
    print("\nSession ended. You can delete the file 'chat_id_finder_session.session' if you don't need it anymore.")

if __name__ == "__main__":
    asyncio.run(main()) 