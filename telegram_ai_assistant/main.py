import os
import asyncio
import argparse
import sys
from telegram_ai_assistant.utils.db_models import init_db
from telegram_ai_assistant.utils.logging_utils import setup_main_logger, log_startup, log_shutdown, enable_debug_mode

# Import components
from telegram_ai_assistant.userbot.telegram_client import start_client as start_userbot
from telegram_ai_assistant.bot.telegram_bot import start_bot

# Set up logging
logger = setup_main_logger()

async def run_userbot():
    """Run the Telegram user client (userbot)"""
    logger.info("Starting Telegram userbot client...")
    from telegram_ai_assistant.userbot.telegram_client import start_client
    await start_client()

async def run_bot():
    """Run the Telegram bot"""
    logger.info("Starting Telegram bot...")
    from telegram_ai_assistant.bot.telegram_bot import start_bot
    await start_bot()

async def run_all():
    """Run both userbot and bot together"""
    # Initialize database
    logger.info("Initializing database...")
    init_db()
    
    # Run both components as tasks
    userbot_task = asyncio.create_task(run_userbot())
    bot_task = asyncio.create_task(run_bot())
    
    # Wait for both tasks
    await asyncio.gather(userbot_task, bot_task)

def main():
    parser = argparse.ArgumentParser(description='Telegram AI Assistant')
    parser.add_argument('--mode', type=str, choices=['all', 'userbot', 'bot'], 
                        default='all', help='Which components to run')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Enable debug mode if requested
    if args.debug:
        enable_debug_mode()
        logger.debug("Debug mode enabled")
    
    # Log application startup
    log_startup("Telegram AI Assistant")
    
    try:
        # Run specified components
        if args.mode == 'all':
            logger.info("Running both userbot and bot")
            asyncio.run(run_all())
        elif args.mode == 'userbot':
            logger.info("Running only userbot")
            asyncio.run(run_userbot())
        elif args.mode == 'bot':
            logger.info("Running only bot")
            asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
    finally:
        # Log application shutdown
        log_shutdown("Telegram AI Assistant")

if __name__ == "__main__":
    main() 