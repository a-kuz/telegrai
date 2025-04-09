import sys
import os
import requests

# Get the parent directory to access config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BOT_TOKEN

def check_bot_token(token):
    """Check if a Telegram bot token is valid."""
    print(f"Checking token: {token}")
    
    url = f"https://api.telegram.org/bot{token}/getMe"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if data.get("ok"):
            bot_info = data.get("result", {})
            print("✅ Token is valid!")
            print(f"Bot username: @{bot_info.get('username')}")
            print(f"Bot name: {bot_info.get('first_name')}")
            print(f"Bot ID: {bot_info.get('id')}")
            return True
    
    print("❌ Token is invalid!")
    print(f"Error: {response.text}")
    return False

if __name__ == "__main__":
    # Allow passing token as command line argument
    if len(sys.argv) > 1:
        token = sys.argv[1]
        check_bot_token(token)
    else:
        # Use token from config
        check_bot_token(BOT_TOKEN) 