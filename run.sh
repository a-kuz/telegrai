#!/bin/bash

# Check if process is running and kill it if it is
if pgrep -f "python3 -m telegram_ai_assistant.main" > /dev/null; then
    echo "Stopping existing Telegram AI Assistant process..."
    pkill -f "python3 -m telegram_ai_assistant.main"
    sleep 1  # Give process time to terminate
else
    echo "No existing Telegram AI Assistant process found."
fi

# Start the application
echo "Starting Telegram AI Assistant..."
nohup python3 -m telegram_ai_assistant.main --mode all > ./telegram_bot.log 2>&1 &

echo "Telegram AI Assistant started with PID: $!"