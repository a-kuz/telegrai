#!/bin/bash

# Run the bot
echo "Starting the bot component..."
bash run.sh

# Wait a bit
sleep 5

# Run the userbot
echo "Starting the userbot component..."
bash run_userbot.sh

echo "Both components started successfully. To see running sessions:"
echo "sudo screen -ls"
echo ""
echo "To view logs:"
echo "tail -f logs/bot.log       # For bot logs"
echo "tail -f logs/userbot.log   # For userbot logs" 