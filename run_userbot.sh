#!/bin/bash

# Kill any existing userbot processes
echo "Checking for existing userbot processes..."
if screen -list | grep -q "telegram_userbot"; then
    echo "Killing existing telegram_userbot screen session..."
    screen -S telegram_userbot -X quit
fi

# Kill any python processes related to the userbot
echo "Killing any existing python processes for the userbot..."
pkill -f "python3 -m telegram_ai_assistant.main --mode userbot"

# Wait a moment for processes to terminate
sleep 2

# Start the userbot in a new screen session
echo "Starting telegram userbot..."
cd /srv/app && screen -S telegram_userbot -d -m bash -c "source venv/bin/activate && python3 -m telegram_ai_assistant.main --mode userbot"

echo "Userbot started successfully." 