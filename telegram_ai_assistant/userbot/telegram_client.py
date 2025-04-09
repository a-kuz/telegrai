import sys
import os
import json
import asyncio
import re
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from datetime import datetime
from typing import Dict, Any, List, Optional

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from utils.logging_utils import setup_userbot_logger
# Setup component logger
logger = setup_userbot_logger()

from telegram_ai_assistant.config import TELEGRAM_API_ID, TELEGRAM_API_HASH, USERBOT_SESSION, MONITORED_CHATS, DOWNLOADS_DIR, ADMIN_USER_ID
from utils.db_utils import store_message, store_unanswered_question, mark_question_as_answered
from ai_module.ai_analyzer import analyze_message, detect_question_target, extract_task_from_message
from linear_integration.linear_client import LinearClient
from utils.task_utils import handle_potential_task
from utils.message_handler import process_new_message

# We'll use a hardcoded session string to avoid interactive authentication
# Replace this with the actual session string for your account
SESSION_STRING = "1ApWapzMBuy6sUBC3Q4jWi1w0zcoyXB5jR93dluQ9uVrg4M3cdz3Vsvcyh5Uz1asAyVnlnXHqpFf35MDr7-WQuMoGAzUQUmn29MxzZndcIMcTLVfviRGHnUsOFULzNozRh20aiFnxCdGPu06WLwJocCH3SwRXLY4Ha930QJV17RFTXV8LOYwkbD3yTg-H_1_wZtwjt4Q54aiu6eFU79jicj8NJunrGKMfAz66HYZwLjXRQOnRzerkJctfIyZl8sJYeJuL5KKSvYGT_9qWj_tgnyjF8TOOHmTbH8lf80jqVe6I78REYhwCNrnbh44sNdD1ePwHsDTeYEIJVcDYYMVqTjg_kEuO7Bo="

# Initialize Telethon client with more specific device info to make it less suspicious
client = TelegramClient(
    StringSession(SESSION_STRING), 
    TELEGRAM_API_ID, 
    TELEGRAM_API_HASH,
    device_model="Desktop",
    system_version="Windows 10",
    app_version="1.0.0"
)
linear_client = LinearClient()

# Make sure downloads directory exists
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

async def process_new_message(event):
    """Process a new message from Telegram and perform AI analysis."""
    try:
        # Get message details
        sender = await event.get_sender()
        chat = await event.get_chat()
        
        # Skip messages from self (avoid self-loop)
        if sender.id == (await client.get_me()).id:
            return
        
        text = event.raw_text
        message_id = event.id
        
        logger.debug(f"New message received: chat_id={chat.id}, message_id={message_id}, text={text[:50]}...")
        
        # Process media attachments if any
        attachments = []
        if event.media:
            logger.debug(f"Message has media attachment")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(DOWNLOADS_DIR, f"{timestamp}_{chat.id}_{message_id}")
            downloaded_path = await client.download_media(event.media, file=file_path)
            if downloaded_path:
                logger.debug(f"Downloaded media to {downloaded_path}")
                attachments.append(downloaded_path)
            else:
                logger.warning(f"Failed to download media for message {message_id}")
        
        # Store in database
        chat_name = getattr(chat, "title", str(chat.id))
        sender_name = f"{getattr(sender, 'first_name', '')} {getattr(sender, 'last_name', '')}".strip()
        
        logger.info(f"Processing message from {sender_name} in {chat_name} (ID: {message_id})")
        
        # Store message in DB
        await store_message(
            chat_id=chat.id,
            chat_name=chat_name,
            message_id=message_id,
            sender_id=sender.id,
            sender_name=sender_name,
            text=text,
            attachments=attachments,
            timestamp=event.date
        )
        logger.debug(f"Message {message_id} stored in database")
        
        # AI analysis
        message_data = {
            "text": text,
            "attachments": attachments,
            "chat_id": chat.id,
            "chat_name": chat_name,
            "message_id": message_id,
            "sender_id": sender.id,
            "sender_name": sender_name,
            "timestamp": event.date.isoformat()
        }
        
        # Perform async analysis
        asyncio.create_task(analyze_and_process(message_data))
        logger.debug(f"Started async task to analyze message {message_id}")
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)

async def analyze_and_process(message_data: Dict[str, Any]):
    """Analyze message with AI and take appropriate actions."""
    try:
        logger.info(f"Analyzing message {message_data['message_id']} with AI")
        
        # Get AI analysis of the message
        analysis = await analyze_message(message_data)
        logger.debug(f"AI analysis complete for message {message_data['message_id']}: {analysis}")
        
        # Check if this is a question targeting the admin
        question_data = await detect_question_target(message_data, ADMIN_USER_ID)
        if question_data and question_data.get("is_question"):
            logger.info(f"Question detected targeting admin: {question_data['question_text']}")
            await store_unanswered_question(
                message_id=question_data["message_id"],
                chat_id=question_data["chat_id"],
                target_user_id=question_data["target_user_id"],
                question_text=question_data["question_text"]
            )
            logger.debug(f"Stored unanswered question in database")
        
        # Check if message appears to contain a task
        if analysis.get("has_task", False):
            logger.info(f"Potential task detected in message {message_data['message_id']}")
            task_data = await extract_task_from_message(message_data)
            if task_data:
                # Store task details for later confirmation by admin via bot
                # This will be processed by the bot component
                logger.debug(f"Extracted task data: {task_data.get('title')}")
                # Notify admin bot about potential task
                await handle_potential_task(task_data, message_data)
                logger.info(f"Handled potential task: {task_data.get('title')}")
        
        # Check if message is answering a previous question
        await check_if_answering_question(message_data)
        
    except Exception as e:
        logger.error(f"Error in AI analysis for message {message_data.get('message_id', 'unknown')}: {str(e)}", exc_info=True)

async def check_if_answering_question(message_data: Dict[str, Any]):
    """Check if this message is answering a previously asked question."""
    try:
        sender_id = message_data.get("sender_id")
        chat_id = message_data.get("chat_id")
        
        # Skip if not from admin
        if sender_id != ADMIN_USER_ID:
            return
        
        # Check for question pattern in replied message
        if hasattr(message_data.get("original_event", {}), "reply_to_msg_id"):
            reply_id = message_data["original_event"].reply_to_msg_id
            if reply_id:
                logger.info(f"Admin replied to message {reply_id} in chat {chat_id}")
                # Mark as answered if it was a tracked question
                result = await mark_question_as_answered(reply_id, chat_id)
                if result:
                    logger.info(f"Marked question {reply_id} as answered")
                else:
                    logger.debug(f"Message {reply_id} was not a tracked question")
    except Exception as e:
        logger.error(f"Error checking if message answers a question: {str(e)}", exc_info=True)

async def send_message_as_user(chat_id: int, text: str) -> bool:
    """Send a message to a Telegram chat on behalf of the user."""
    try:
        logger.info(f"Sending message to chat {chat_id}")
        logger.debug(f"Message content: {text[:50]}...")
        await client.send_message(chat_id, text)
        logger.info(f"Message sent successfully to chat {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error sending message to chat {chat_id}: {str(e)}", exc_info=True)
        return False

async def start_client():
    """Initialize and start the Telegram userbot client."""
    logger.info("Initializing Telegram userbot client")
    
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        logger.error("Telegram API credentials are missing. Please set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
        return None
    
    try:
        # Create the client and connect
        await client.start()
        
        if not await client.is_user_authorized():
            logger.error("User is not authorized. Please run the authentication script first.")
            await client.disconnect()
            return None
        
        # If MONITORED_CHATS is empty, monitor all chats
        if not MONITORED_CHATS:
            @client.on(events.NewMessage)
            async def handler(event):
                await process_new_message(event)
            logger.info("Telegram userbot client started")
            logger.info("Monitoring ALL chats")
        else:
            @client.on(events.NewMessage(chats=MONITORED_CHATS))
            async def handler(event):
                await process_new_message(event)
            logger.info("Telegram userbot client started")
            logger.info(f"Monitoring {len(MONITORED_CHATS)} chats: {MONITORED_CHATS}")
        
        return client
    except Exception as e:
        logger.error(f"Error initializing Telegram client: {str(e)}")
        return None

async def stop_client(client):
    """Stop the Telegram userbot client."""
    logger.info("Stopping Telegram userbot client")
    
    if client:
        await client.disconnect()
        logger.info("Telegram userbot client disconnected")
    else:
        logger.warning("Attempt to stop non-existent client")

async def main():
    """Main function to run the Telegram userbot client."""
    logger.info("Starting Telegram userbot client standalone")
    
    client = await start_client()
    if not client:
        logger.error("Failed to start Telegram userbot client")
        return
    
    try:
        logger.info("Telegram userbot client running...")
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    finally:
        await stop_client(client)

if __name__ == "__main__":
    asyncio.run(main()) 