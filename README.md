# Telegram AI Assistant

<div align="center">
  <img src="https://i.ibb.co/k2nt5R1z/14ca1ab027ab74ee7b020aef9ca24eb3807cd270b59a11de8cb919f830507fae.png" alt="Telegram AI Assistant Logo" width="200"/>

  
  <br>
  <h3>Smart AI Assistant for Telegram</h3>
  <p>Monitors chats, tracks tasks, reminds about questions, and creates summaries</p>
</div>

## 📱 Overview

Telegram AI Assistant is a powerful tool for productive work with Telegram chats. It uses artificial intelligence to analyze messages, track tasks, questions, and important information, ensuring nothing important is missed in the flow of messages.

## ✨ Key Features

- **Passive chat monitoring** - reads messages in all or selected chats without sending messages on your behalf
- **AI content analysis** - uses OpenAI GPT-4o to understand the context of messages, images, and links
- **Task management** - automatically detects tasks in messages and creates them in Linear
- **Question tracking** - identifies questions directed at you and reminds you of unanswered ones
- **Automatic summaries** - generates brief reports on discussions in chats
- **Activity analytics** - tracks team engagement and activity
- **Two-component architecture**:
  - Userbot (user client) for reading messages from your account
  - Bot for interacting with you and displaying results

## 🏗️ System Architecture

![Architecture](https://i.imgur.com/jUw5XTl.png)

The system consists of several components:

1. **Telegram Userbot** - uses Telethon to read messages from your account
2. **AI module** - analyzes message content using OpenAI GPT-4o
3. **Linear integration** - manages tasks in the Linear tracker
4. **Telegram Bot** - provides an interface for interacting with the system
5. **Database** - stores messages, tasks, and other data

## 🧩 Usage Examples

### Chat Monitoring

The assistant can monitor all your chats or only selected ones:

```
# Monitor all chats
MONITORED_CHATS=[]

# Monitor specific chats
MONITORED_CHATS=[-100123456789, -100987654321]
```

### Bot Commands

![Bot Command Examples](https://i.imgur.com/bQVyZIw.png)

The bot supports the following commands:

- `/start` - Initialize the bot
- `/help` - Show available commands
- `/summary [chat_name]` - Get a summary of recent conversations (optionally from a specific chat)
- `/tasks` - Show pending tasks from Linear
- `/reminders` - Check unanswered questions
- `/teamreport` - View team productivity report
- `/createtask` - Manually create a new task in Linear

### Example Summary Retrieval 

```
🤖 @assistant_akuz3_bot

/summary

📊 Summary for All Chats
Period: Last 24 hours

Main topics discussed:
1. Product roadmap for Q3
2. Design review for homepage update
3. Bug fixes for authentication system

Key updates:
- Maria shared the new marketing plan
- Alex fixed the login issue
- Team agreed to postpone the API update

Questions for you:
1. "Can you review the latest pull request?"
2. "What do you think about the new color scheme?"

Tasks identified:
- Implement user settings page by Friday
- Schedule a meeting with the client next week
```

### Example Question Tracking

```
🤖 @assistant_akuz3_bot

/reminders

❓ Unanswered Questions

Question: Could you share your thoughts on the new landing page design?
Asked: 2 hours ago
Reminder count: 1

[Respond] [Ignore]
```

### Example Automatic Task Detection

```
🤖 @assistant_akuz3_bot

📋 Potential Task Detected

Title: Update API documentation for v2.0
Description: Need to update the API docs to reflect the new endpoints and parameters added in version 2.0
Assignee: Not specified
Due Date: Next Friday

From chat: Dev Team

[Create Task] [Ignore]
```

## 🛠️ Requirements

- Python 3.8+
- Telegram API keys (from [my.telegram.org/apps](https://my.telegram.org/apps))
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- OpenAI API key with access to GPT-4o
- Linear API key (optional, for task integration)

## 📦 Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/telegram-ai-assistant.git
cd telegram-ai-assistant
```

2. Install the required packages:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

4. Edit the `.env` file with your credentials.

5. Initialize the database:

```bash
python -m telegram_ai_assistant.utils.db_models
```

## 🚀 Running

### Running with screen for background operation

```bash
# Start userbot (reading messages)
screen -S telegram_assistant -d -m bash -c "cd /path/to/telegram_ai_assistant && source venv/bin/activate && python -m telegram_ai_assistant.main --mode userbot"

# Start bot (interaction interface)
screen -S telegram_bot -d -m bash -c "cd /path/to/telegram_ai_assistant && source venv/bin/activate && python -m telegram_ai_assistant.main --mode bot"
```

### Managing screen sessions

```bash
# View the list of running sessions
screen -ls

# Connect to a session
screen -r telegram_assistant

# Detach from a session (without stopping)
# Press Ctrl+A, then D

# Terminate a session
screen -S telegram_assistant -X quit
```

## 🔧 Configuration

### Setting up environment variables (.env)

```
# Telegram API credentials
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

# Telegram Bot token
BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ

# Chat IDs to monitor (empty array to monitor all chats)
MONITORED_CHATS=[]

# OpenAI API key
OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890

# OpenAI model
OPENAI_MODEL=gpt-4o

# Linear API key
LINEAR_API_KEY=lin_abcdefghijklmnopqrstuvwxyz

# Linear team mapping
LINEAR_TEAM_MAPPING={"default": "TEAM_NAME"}

# Admin user ID (your Telegram user ID)
ADMIN_USER_ID=1234567890
```

### Finding Chat IDs

Use the utility to get chat IDs:

```bash
python -m telegram_ai_assistant.utils.get_chat_ids
```

## 📋 Frequently Asked Questions

### How to find my Telegram User ID?
Send a message to the bot [@userinfobot](https://t.me/userinfobot) in Telegram

### Will the assistant's actions be visible to other users?
No, the assistant only reads messages using the userbot client and does not perform any visible actions in chats.

### Is it safe to use the assistant with my Telegram account?
Yes, if used for personal use. However, abuse of the Telegram API may lead to account restrictions.

### What to do if other Telegram clients log out?
This may happen due to suspicious activity. Use the assistant moderately and ensure that the userbot client code has the correct parameters for `device_model`, `system_version`, and `app_version`.

## 🛡️ Security

- The userbot has access to all messages in monitored chats.
- Credentials are stored in the `.env` file.
- Data is stored in a local database.
- Ensure the server is secure and access is restricted.
- Maintain privacy and data protection standards.

## 📄 License

MIT License

## ⚠️ Disclaimer

This project is not affiliated with Telegram, OpenAI, or Linear. The userbot functionality uses the Telegram API in accordance with their terms of use for personal use, but be aware that misuse may lead to account restrictions.

---

If you need any further assistance or specific sections translated, feel free to ask!
