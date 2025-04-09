import sys
import os
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ADMIN_USER_ID, BOT_TOKEN
pending_tasks = {}
async def handle_potential_task(task_data: Dict[str, Any], message_data: Dict[str, Any], bot: Optional[Bot] = None):
    """Handle a potential task detected by AI"""
    try:
        if bot is None:
            from aiogram.client.default import DefaultBotProperties
            bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
            needs_cleanup = True
        else:
            needs_cleanup = False
        task_id = f"task_{int(datetime.utcnow().timestamp())}"
        pending_tasks[task_id] = {
            **task_data,
            "chat_id": message_data.get("chat_id"),
            "message_id": message_data.get("message_id"),
            "detected_at": datetime.utcnow()
        }
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Create Task", 
                    callback_data=f"createtask_{task_id}"
                ),
                InlineKeyboardButton(
                    text="Ignore", 
                    callback_data=f"ignoretask_{task_id}"
                )
            ]
        ])
        assignee = task_data.get("assignee", "Not specified")
        due_date = task_data.get("due_date", "Not specified")
        message = (
            f"📋 <b>Potential Task Detected</b>\n\n"
            f"<b>Title:</b> {task_data.get('title')}\n"
            f"<b>Description:</b> {task_data.get('description')}\n"
            f"<b>Assignee:</b> {assignee}\n"
            f"<b>Due Date:</b> {due_date}\n\n"
            f"<b>From chat:</b> {message_data.get('chat_name')}"
        )
        await bot.send_message(
            ADMIN_USER_ID,
            message,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        if needs_cleanup:
            await bot.session.close()
    except Exception as e:
        print(f"Error handling potential task: {str(e)}")
    return pending_tasks 