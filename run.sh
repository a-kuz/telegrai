#!/bin/bash

# Kill any existing bot processes
echo "Checking for existing bot processes..."
if screen -list | grep -q "telegram_bot"; then
    echo "Killing existing telegram_bot screen session..."
    screen -S telegram_bot -X quit
fi

# Kill any python processes related to the bot
echo "Killing any existing python processes for the bot..."
pkill -f "python3 -m telegram_ai_assistant.main"

# Wait a moment for processes to terminate
sleep 2

# Start the bot in a new screen session
echo "Starting telegram bot..."
cd /srv/app && screen -S telegram_bot -d -m bash -c "source venv/bin/activate && python3 -m telegram_ai_assistant.main --mode bot"

echo "Bot started successfully."