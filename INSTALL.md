# Installation Guide

This document provides step-by-step instructions for setting up the Telegram AI Assistant on your system.

## Prerequisites

Before you begin, make sure you have:

1. Python 3.8 or higher installed
2. Access to a Telegram account (for the userbot)
3. A Telegram bot token (create one via [@BotFather](https://t.me/BotFather))
4. OpenAI API key with access to o3-mini
5. (Optional) Linear.app API key for task management

## Step 1: Get Telegram API Credentials

To use the userbot (client) functionality, you need Telegram API credentials:

1. Visit [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. Log in with your phone number
3. Create a new application if you don't have one already
4. Note down the `api_id` and `api_hash` values

## Step 2: Set Up the Environment

1. Clone the repository:

```bash
git clone https://github.com/akuz/telegram-ai-assistant.git
cd telegram-ai-assistant
```

2. Create a virtual environment (recommended):

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r telegram_ai_assistant/requirements.txt
```

4. Create and configure the .env file:

```bash
cp telegram_ai_assistant/.env.example telegram_ai_assistant/.env
```

5. Edit the .env file with your credentials:

```bash
# Telegram API credentials
TELEGRAM_API_ID=123456  # Your API ID
TELEGRAM_API_HASH=your_api_hash_here

# Telegram Bot token
BOT_TOKEN=your_bot_token_here

# Chat IDs to monitor
MONITORED_CHATS=[-100123456789,-100987654321]  # Replace with actual chat IDs

# OpenAI API key
OPENAI_API_KEY=your_openai_api_key_here

# Linear API key (optional)
LINEAR_API_KEY=your_linear_api_key_here

# Admin user ID (your Telegram user ID)
ADMIN_USER_ID=your_user_id_here
```

## Step 3: Find Chat IDs to Monitor

To get the IDs of chats you want to monitor:

1. Start the Telegram userbot temporarily:

```bash
python -c "import asyncio; from telethon import TelegramClient; async def main(): client = TelegramClient('user_session_temp', 123456, 'your_api_hash'); await client.start(); dialogs = await client.get_dialogs(); for d in dialogs: print(f'{d.name}: {d.id}'); await client.disconnect(); asyncio.run(main())"
```

Replace `123456` and `your_api_hash` with your actual API ID and hash.

2. Note down the IDs of the chats you want to monitor
3. Update the `MONITORED_CHATS` setting in your .env file

## Step 4: Initialize the Database

```bash
python -m telegram_ai_assistant.utils.db_models
```

## Step 5: Start the Assistant

1. For the first run (you'll be prompted to authenticate):

```bash
python -m telegram_ai_assistant.main
```

2. After authentication, you can run in the background:

```bash
nohup python -m telegram_ai_assistant.main > telegram_assistant.log 2>&1 &
```

## Step 6: Interact with the Bot

Once the assistant is running:

1. Start a conversation with your Telegram bot
2. Send `/start` to initialize the bot
3. Try various commands like `/help`, `/summary`, `/tasks`, etc.

## Troubleshooting

- If you encounter authentication issues with Telegram, delete the `user_session.session` file and try again
- Check the logs for any errors: `tail -f telegram_assistant.log`
- Ensure your API keys are correct in the .env file
- Make sure the Telegram bot has been started (sent `/start` command)

## Optional: Install as a System Service

For a more permanent installation:

1. Create a systemd service file:

```bash
sudo nano /etc/systemd/system/telegram-ai-assistant.service
```

2. Add the following content (adjust paths as needed):

```
[Unit]
Description=Telegram AI Assistant
After=network.target

[Service]
User=yourusername
WorkingDirectory=/path/to/telegram-ai-assistant
ExecStart=/path/to/python -m telegram_ai_assistant.main
Restart=always

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:

```bash
sudo systemctl enable telegram-ai-assistant
sudo systemctl start telegram-ai-assistant
```

4. Check the status:

```bash
sudo systemctl status telegram-ai-assistant
``` 