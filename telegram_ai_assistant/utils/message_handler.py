import os
import time
from telethon import events
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto, PeerUser, PeerChannel, PeerChat
from typing import Dict, Any, List, Optional

from utils.logging_utils import setup_userbot_logger
# Setup component logger
logger = setup_userbot_logger()

from telegram_ai_assistant.config import DOWNLOADS_DIR, ADMIN_USER_ID
from telegram_ai_assistant.utils.db_utils import store_message, store_unanswered_question, mark_question_as_answered
from telegram_ai_assistant.ai_module.ai_analyzer import analyze_message, detect_question_target, extract_task_from_message
from telegram_ai_assistant.linear_integration.linear_client import LinearClient
from telegram_ai_assistant.utils.task_utils import handle_potential_task

async def download_media(event, message_data):
    """Download media from a message if present."""
    if not event.media:
        return None
    
    try:
        if not os.path.exists(DOWNLOADS_DIR):
            os.makedirs(DOWNLOADS_DIR)
            
        file_path = await event.download_media(DOWNLOADS_DIR)
        message_data["media_path"] = file_path
        
        # Log media type
        if isinstance(event.media, MessageMediaPhoto):
            logger.info(f"Downloaded photo: {file_path}")
        elif isinstance(event.media, MessageMediaDocument):
            logger.info(f"Downloaded document: {file_path}")
        else:
            logger.info(f"Downloaded media: {file_path}")
            
        return file_path
    except Exception as e:
        logger.error(f"Error downloading media: {str(e)}")
        return None

async def get_chat_details(event):
    """Get details about the chat where the message was sent."""
    chat_type = "unknown"
    chat_id = 0
    chat_title = "Unknown"
    
    try:
        chat = await event.get_chat()
        chat_id = event.chat_id
        
        if hasattr(chat, 'title'):
            chat_title = chat.title
        elif hasattr(chat, 'first_name'):
            chat_title = f"{chat.first_name} {chat.last_name if hasattr(chat, 'last_name') else ''}".strip()
            
        if isinstance(event.peer_id, PeerUser):
            chat_type = "private"
        elif isinstance(event.peer_id, PeerChannel):
            chat_type = "channel"
        elif isinstance(event.peer_id, PeerChat):
            chat_type = "group"
    except Exception as e:
        logger.error(f"Error getting chat details: {str(e)}")
    
    return {
        "chat_id": chat_id,
        "chat_title": chat_title,
        "chat_type": chat_type
    }

async def get_sender_details(event):
    """Get details about the sender of the message."""
    sender_id = 0
    sender_username = None
    sender_name = "Unknown"
    
    try:
        sender = await event.get_sender()
        sender_id = sender.id
        
        if hasattr(sender, 'username'):
            sender_username = sender.username
            
        if hasattr(sender, 'first_name'):
            sender_name = f"{sender.first_name} {sender.last_name if hasattr(sender, 'last_name') else ''}".strip()
    except Exception as e:
        logger.error(f"Error getting sender details: {str(e)}")
    
    return {
        "sender_id": sender_id,
        "sender_username": sender_username,
        "sender_name": sender_name
    }

async def process_new_message(event):
    """Process a new message from Telegram."""
    start_time = time.time()
    
    # Ignore messages sent by the bot itself
    if event.out:
        return
    
    try:
        # Get basic message information
        message_id = event.id
        message_text = event.message.message if event.message else ""
        date = event.message.date if event.message else None
        
        chat_details = await get_chat_details(event)
        sender_details = await get_sender_details(event)
        
        logger.info(f"New message [{message_id}] from {sender_details['sender_name']} ({sender_details['sender_id']}) "
                   f"in {chat_details['chat_title']} ({chat_details['chat_id']}): {message_text[:100]}...")

        # Prepare message data for storage
        message_data = {
            "message_id": message_id,
            "chat_id": chat_details["chat_id"],
            "chat_title": chat_details["chat_title"],
            "chat_type": chat_details["chat_type"],
            "sender_id": sender_details["sender_id"],
            "sender_name": sender_details["sender_name"],
            "sender_username": sender_details["sender_username"],
            "message_text": message_text,
            "date": date,
            "media_path": None,
            "message_link": f"https://t.me/c/{str(chat_details['chat_id']).replace('-100', '')}/{message_id}" 
                           if chat_details["chat_type"] in ["group", "channel"] else None
        }
        
        # Handle media if present
        await download_media(event, message_data)
        
        # Store the message in the database
        message_db_id = store_message(message_data)
        logger.debug(f"Stored message with DB ID: {message_db_id}")
        
        # Run AI analysis on the message
        analysis_result = await analyze_message(message_text)
        logger.debug(f"AI analysis result: {analysis_result}")
        
        # Check for tasks
        if analysis_result.get("is_task", False):
            task_details = extract_task_from_message(message_text)
            await handle_potential_task(task_details, message_data, message_db_id)
        
        # Check for questions
        question_target = detect_question_target(message_text)
        if question_target:
            logger.info(f"Question detected, target: {question_target}")
            question_id = store_unanswered_question(message_db_id, question_target)
            # If question is for admin, notify them
            if question_target == "admin" and ADMIN_USER_ID:
                # Notification logic would go here
                pass
        
        elapsed_time = time.time() - start_time
        logger.debug(f"Message processing completed in {elapsed_time:.2f} seconds")
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True) 