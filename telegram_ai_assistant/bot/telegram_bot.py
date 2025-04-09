import sys
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiogram.utils.markdown as md
from collections import defaultdict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Use the local bot config
from bot.bot_config import BOT_TOKEN, ADMIN_USER_ID
from utils.db_utils import (
    get_recent_chat_messages, 
    get_pending_reminders, 
    update_reminder_sent,
    get_tasks_by_due_date,
    get_team_productivity
)
from ai_module.ai_analyzer import (
    generate_chat_summary, 
    analyze_productivity,
    suggest_response
)
from linear_integration.linear_client import LinearClient
from userbot.telegram_client import send_message_as_user
from utils.task_utils import pending_tasks
from utils.logging_utils import setup_bot_logger, log_startup

# Initialize bot with HTML parse mode using the new API
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
linear_client = LinearClient()

# Setup logging
logger = setup_bot_logger()

# Simple state management for task creation
user_states = {}
AWAITING_TASK_TITLE = "awaiting_title"
AWAITING_TASK_DESCRIPTION = "awaiting_description"
task_creation_data = defaultdict(dict)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("Sorry, this bot is private.")
        logger.info(f"Unauthorized access attempt from user ID: {message.from_user.id}")
        return
    
    logger.info(f"Start command received from admin user {ADMIN_USER_ID}")
    await message.reply(
        "👋 Hello! I'm your AI assistant for Telegram work chats.\n\n"
        "I monitor your chats, identify important messages, track tasks, "
        "and help you stay on top of your responsibilities.\n\n"
        "Here are my main commands:\n"
        "/summary - Get a summary of recent conversations\n"
        "/tasks - Show pending tasks\n"
        "/reminders - Check for unanswered questions\n"
        "/teamreport - View team productivity report\n"
        "/help - Show all available commands"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Handle /help command"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    help_text = (
        "📋 <b>Available Commands</b>\n\n"
        "/summary [chat_name] - Generate summary of recent conversations\n"
        "/tasks - Show pending tasks in Linear\n"
        "/reminders - Check for unanswered questions\n"
        "/teamreport - View team productivity report\n"
        "/createtask - Create a new task in Linear\n"
        "/respond [chat_id] [message_id] - Respond to a message\n"
    )
    
    await message.reply(help_text, parse_mode="HTML")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    """Generate and send summary of recent conversations"""
    if message.from_user.id != ADMIN_USER_ID:
        logger.info(f"Unauthorized summary request from user ID: {message.from_user.id}")
        return
    
    # Check if a specific chat name was provided
    args = message.text.split(maxsplit=1)
    chat_name = args[1].strip() if len(args) > 1 else None
    
    logger.info(f"Summary requested for chat: {chat_name or 'All chats'}")
    
    # Temporary response while processing
    processing_msg = await message.reply("Generating summary... This might take a moment.")
    
    try:
        # If chat_name is provided, find matching chat ID
        # This is a simplified example - in reality you'd query the database
        # or maintain a mapping of chat names to IDs
        chat_id = None  # TODO: Implement chat name to ID mapping
        
        # For demo purposes, we'll use recent messages from all chats
        chat_messages = await get_recent_chat_messages(chat_id, hours=24, limit=100)
        
        if not chat_messages:
            logger.info("No recent messages found to summarize")
            await processing_msg.edit_text("No recent messages found to summarize.")
            return
        
        logger.debug(f"Found {len(chat_messages)} messages to summarize")
        
        # Generate summary using AI
        summary = await generate_chat_summary(
            chat_messages, 
            chat_name or "All monitored chats"
        )
        
        # Format and send the summary
        response = (
            f"📊 <b>Summary for {chat_name or 'All Chats'}</b>\n"
            f"<i>Period: Last 24 hours</i>\n\n"
            f"{summary}"
        )
        
        logger.info(f"Summary generated successfully for {chat_name or 'All chats'}")
        await processing_msg.edit_text(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error generating summary: {str(e)}", exc_info=True)
        await processing_msg.edit_text(f"Error generating summary: {str(e)}")

@dp.message(Command("tasks"))
async def cmd_tasks(message: types.Message):
    """Show pending tasks from Linear"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    processing_msg = await message.reply("Fetching tasks from Linear...")
    
    try:
        # Get tasks due in the next 7 days
        tasks = await get_tasks_by_due_date(days=7)
        
        if not tasks:
            await processing_msg.edit_text("No pending tasks found for the next 7 days.")
            return
        
        # Format tasks
        response = ["📝 <b>Pending Tasks (Next 7 Days)</b>\n"]
        
        for task in tasks:
            due_date = task.get("due_date")
            due_date_str = due_date.strftime("%Y-%m-%d") if due_date else "No due date"
            
            task_text = (
                f"• <b>{task.get('title')}</b>\n"
                f"  ID: {task.get('linear_id')}\n"
                f"  Status: {task.get('status')}\n"
                f"  Due: {due_date_str}\n"
                f"  Assignee: {task.get('assignee_name')}\n"
            )
            response.append(task_text)
        
        await processing_msg.edit_text("\n".join(response), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error fetching tasks: {str(e)}")
        await processing_msg.edit_text(f"Error fetching tasks: {str(e)}")

@dp.message(Command("reminders"))
async def cmd_reminders(message: types.Message):
    """Check for unanswered questions"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    try:
        # Get unanswered questions
        reminders = await get_pending_reminders(ADMIN_USER_ID, hours_threshold=1)
        
        if not reminders:
            await message.reply("No pending questions or reminders at the moment.")
            return
        
        # Format reminders
        response = ["❓ <b>Unanswered Questions</b>\n"]
        
        for reminder in reminders:
            # Create inline keyboard for each reminder
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Respond", 
                        callback_data=f"respond_{reminder['chat_id']}_{reminder['message_id']}"
                    ),
                    InlineKeyboardButton(
                        text="Ignore", 
                        callback_data=f"ignore_{reminder['id']}"
                    )
                ]
            ])
            
            # Format time ago
            asked_at = reminder.get("asked_at")
            time_ago = "Unknown time"
            if asked_at:
                delta = datetime.utcnow() - asked_at
                if delta.days > 0:
                    time_ago = f"{delta.days} days ago"
                elif delta.seconds >= 3600:
                    time_ago = f"{delta.seconds // 3600} hours ago"
                else:
                    time_ago = f"{delta.seconds // 60} minutes ago"
            
            reminder_text = (
                f"<b>Question:</b> {reminder.get('question')}\n"
                f"<b>Asked:</b> {time_ago}\n"
                f"<b>Reminder count:</b> {reminder.get('reminder_count', 0)}"
            )
            
            # Send each reminder as a separate message with its own inline keyboard
            await message.answer(reminder_text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error fetching reminders: {str(e)}")
        await message.reply(f"Error fetching reminders: {str(e)}")

@dp.message(Command("teamreport"))
async def cmd_teamreport(message: types.Message):
    """Generate and send team productivity report"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    processing_msg = await message.reply("Generating team productivity report...")
    
    try:
        # Get team productivity data
        productivity_data = await get_team_productivity(days=7)
        
        if not productivity_data:
            await processing_msg.edit_text("No productivity data available.")
            return
        
        # Use AI to analyze productivity data
        analysis = await analyze_productivity(productivity_data)
        
        # Format the report
        response = [
            "📈 <b>Team Productivity Report</b>\n",
            "<i>Period: Last 7 days</i>\n\n",
            "<b>Raw Data:</b>"
        ]
        
        for item in productivity_data:
            user_stats = (
                f"• <b>{item.get('name')}</b>:\n"
                f"  Messages: {item.get('total_messages', 0)}\n"
                f"  Tasks created: {item.get('tasks_created', 0)}\n"
                f"  Tasks completed: {item.get('tasks_completed', 0)}\n"
            )
            response.append(user_stats)
        
        response.append("\n<b>Analysis:</b>\n" + analysis)
        
        await processing_msg.edit_text("\n".join(response), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error generating team report: {str(e)}")
        await processing_msg.edit_text(f"Error generating team report: {str(e)}")

@dp.message(Command("createtask"))
async def cmd_createtask(message: types.Message):
    """Create a new task in Linear"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    # Set user state to awaiting task title
    user_states[message.from_user.id] = AWAITING_TASK_TITLE
    
    # Task creation process has multiple steps
    # Step 1: Ask for task title
    await message.reply(
        "Let's create a new task in Linear.\n\n"
        "Please enter the task title:"
    )

@dp.message()
async def handle_all_messages(message: types.Message):
    """Handle all regular messages, including task creation steps"""
    user_id = message.from_user.id
    
    # Only process messages from admin
    if user_id != ADMIN_USER_ID:
        return
    
    # Check if user is in task creation flow
    current_state = user_states.get(user_id)
    
    if current_state == AWAITING_TASK_TITLE:
        # User is entering task title
        task_title = message.text.strip()
        
        if task_title:
            # Store the title
            task_creation_data[user_id]["title"] = task_title
            
            # Move to next state
            user_states[user_id] = AWAITING_TASK_DESCRIPTION
            
            # Ask for description
            await message.reply(
                "Got it! Now please enter the task description (or type /skip for no description):"
            )
        else:
            await message.reply("Please enter a valid task title.")
    
    elif current_state == AWAITING_TASK_DESCRIPTION:
        # User is entering task description
        task_description = message.text.strip()
        
        if task_description == "/skip":
            task_description = ""
        
        # Store the description
        task_creation_data[user_id]["description"] = task_description
        
        # Reset state
        user_states.pop(user_id)
        
        # Create the task
        await message.reply("Creating task in Linear...")
        
        try:
            # Get team ID
            team_id = await linear_client.get_team_id_for_chat(message.chat.id)
            
            if not team_id:
                team_id = LINEAR_TEAM_MAPPING.get("default")
                
            if not team_id:
                await message.reply("❌ Error: Could not determine which Linear team to assign this task to.")
                return
            
            # Create issue in Linear
            issue = await linear_client.create_issue(
                title=task_creation_data[user_id]["title"],
                description=task_creation_data[user_id]["description"],
                team_id=team_id
            )
            
            # Send confirmation
            await message.reply(
                f"✅ Task created in Linear!\n\n"
                f"<b>{issue.get('title')}</b>\n"
                f"ID: {issue.get('identifier')}\n"
                f"URL: {issue.get('url')}\n",
                parse_mode="HTML"
            )
            
            # Clean up
            del task_creation_data[user_id]
            
        except Exception as e:
            logger.error(f"Error creating Linear task: {str(e)}")
            await message.reply(f"❌ Error creating task in Linear: {str(e)}")
            user_states.pop(user_id, None)
            task_creation_data.pop(user_id, None)

@dp.callback_query(lambda c: c.data.startswith('respond_'))
async def callback_respond(callback_query: types.CallbackQuery):
    """Handle respond button click for unanswered questions"""
    if callback_query.from_user.id != ADMIN_USER_ID:
        return
    
    # Extract chat_id and message_id from callback data
    # Format: respond_CHAT_ID_MESSAGE_ID
    parts = callback_query.data.split('_')
    if len(parts) != 3:
        await callback_query.answer("Invalid callback data")
        return
    
    chat_id = int(parts[1])
    message_id = int(parts[2])
    
    # Acknowledge the callback
    await callback_query.answer()
    
    # Send follow-up message asking for the response
    await bot.send_message(
        callback_query.from_user.id,
        f"Please type your response to the question (from chat {chat_id}, message {message_id}):\n\n"
        f"To cancel, type /cancel"
    )
    
    # Note: In a real implementation, you'd use a state machine or conversation handler
    # to track the ongoing conversation and process the user's response

@dp.callback_query(lambda c: c.data.startswith('ignore_'))
async def callback_ignore(callback_query: types.CallbackQuery):
    """Handle ignore button click for unanswered questions"""
    if callback_query.from_user.id != ADMIN_USER_ID:
        return
    
    # Extract reminder_id from callback data
    # Format: ignore_REMINDER_ID
    parts = callback_query.data.split('_')
    if len(parts) != 2:
        await callback_query.answer("Invalid callback data")
        return
    
    reminder_id = int(parts[1])
    
    # Mark the reminder as sent/addressed
    success = await update_reminder_sent(reminder_id)
    
    if success:
        await callback_query.answer("Question marked as addressed")
        await bot.edit_message_text(
            "✅ This question has been ignored/addressed.",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id
        )
    else:
        await callback_query.answer("Failed to update reminder status")

@dp.callback_query(lambda c: c.data.startswith('createtask_'))
async def callback_createtask(callback_query: types.CallbackQuery):
    """Handle create task button click for potential tasks"""
    if callback_query.from_user.id != ADMIN_USER_ID:
        return
    
    # Extract task_id from callback data
    # Format: createtask_TASK_ID
    parts = callback_query.data.split('_')
    if len(parts) != 2:
        await callback_query.answer("Invalid callback data")
        return
    
    task_id = parts[1]
    
    # Retrieve task details from pending_tasks
    if task_id not in pending_tasks:
        await callback_query.answer("Task not found or expired")
        return
    
    task_data = pending_tasks[task_id]
    
    # Acknowledge the callback
    await callback_query.answer()
    
    # Process task creation
    try:
        # Update UI to show processing
        await bot.edit_message_text(
            "Creating task in Linear...",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id
        )
        
        # Get team ID for the chat
        team_id = await linear_client.get_team_id_for_chat(task_data.get("chat_id"))
        
        if not team_id:
            await bot.edit_message_text(
                "⚠️ Could not determine which Linear team to assign this task to.",
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id
            )
            return
        
        # Create the issue in Linear
        issue = await linear_client.create_issue(
            title=task_data.get("title", "Untitled Task"),
            description=task_data.get("description", ""),
            team_id=team_id,
            assignee_id=task_data.get("assignee_id"),
            due_date=task_data.get("due_date")
        )
        
        # Update UI with success
        await bot.edit_message_text(
            f"✅ Task created in Linear!\n\n"
            f"<b>{issue.get('title')}</b>\n"
            f"ID: {issue.get('identifier')}\n"
            f"URL: {issue.get('url')}\n",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            parse_mode="HTML"
        )
        
        # Optionally notify the original chat about task creation
        if task_data.get("notify_chat", False):
            chat_id = task_data.get("chat_id")
            await send_message_as_user(
                chat_id,
                f"📋 Created task in Linear: {issue.get('identifier')} - {issue.get('title')}"
            )
        
        # Remove from pending tasks
        del pending_tasks[task_id]
        
    except Exception as e:
        logger.error(f"Error creating Linear task: {str(e)}")
        await bot.edit_message_text(
            f"❌ Error creating task in Linear: {str(e)}",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id
        )

@dp.callback_query(lambda c: c.data.startswith('ignoretask_'))
async def callback_ignoretask(callback_query: types.CallbackQuery):
    """Handle ignore task button click for potential tasks"""
    if callback_query.from_user.id != ADMIN_USER_ID:
        return
    
    # Extract task_id from callback data
    parts = callback_query.data.split('_')
    if len(parts) != 2:
        await callback_query.answer("Invalid callback data")
        return
    
    task_id = parts[1]
    
    # Remove from pending tasks
    if task_id in pending_tasks:
        del pending_tasks[task_id]
    
    # Acknowledge the callback
    await callback_query.answer("Task ignored")
    
    # Update UI
    await bot.edit_message_text(
        "✓ This task suggestion has been ignored.",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id
    )

async def check_reminders_periodically():
    """Periodically check for unanswered questions and send reminders"""
    logger.info("Starting periodic reminder checker")
    while True:
        try:
            # Get pending reminders
            reminders = await get_pending_reminders(ADMIN_USER_ID, hours_threshold=1)
            
            if reminders:
                logger.debug(f"Found {len(reminders)} pending reminders to process")
            
            for reminder in reminders:
                # Check if it's time to send a reminder
                reminder_count = reminder.get("reminder_count", 0)
                asked_at = reminder.get("asked_at")
                
                # Skip reminders that are too recent or have been reminded too many times
                if reminder_count >= 3:
                    continue
                
                # For testing, send reminders more frequently
                # In production, you'd use a more sophisticated time-based logic
                if reminder_count == 0 and (datetime.utcnow() - asked_at).total_seconds() >= 3600:
                    # First reminder after 1 hour
                    logger.info(f"Sending first reminder for question from chat {reminder.get('chat_id')}")
                    await send_reminder(reminder)
                elif reminder_count == 1 and (datetime.utcnow() - asked_at).total_seconds() >= 7200:
                    # Second reminder after 2 hours
                    logger.info(f"Sending second reminder for question from chat {reminder.get('chat_id')}")
                    await send_reminder(reminder)
                elif reminder_count == 2 and (datetime.utcnow() - asked_at).total_seconds() >= 14400:
                    # Third and final reminder after 4 hours
                    logger.info(f"Sending final reminder for question from chat {reminder.get('chat_id')}")
                    await send_reminder(reminder)
            
        except Exception as e:
            logger.error(f"Error in reminder check: {str(e)}", exc_info=True)
        
        # Check every 15 minutes
        logger.debug("Reminder checker sleeping for 15 minutes")
        await asyncio.sleep(900)

async def send_reminder(reminder):
    """Send a reminder about an unanswered question"""
    try:
        question_text = reminder.get("question", "")
        chat_id = reminder.get("chat_id")
        message_id = reminder.get("message_id")
        reminder_count = reminder.get("reminder_count", 0)
        
        # Create inline keyboard
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Respond", 
                    callback_data=f"respond_{chat_id}_{message_id}"
                ),
                InlineKeyboardButton(
                    text="Ignore", 
                    callback_data=f"ignore_{reminder['id']}"
                )
            ]
        ])
        
        # Format reminder message based on reminder count
        urgency = ["", "⚠️", "🔴"][reminder_count] if reminder_count < 3 else "🔴"
        time_ago = "Unknown time"
        asked_at = reminder.get("asked_at")
        if asked_at:
            delta = datetime.utcnow() - asked_at
            if delta.days > 0:
                time_ago = f"{delta.days} days ago"
            elif delta.seconds >= 3600:
                time_ago = f"{delta.seconds // 3600} hours ago"
            else:
                time_ago = f"{delta.seconds // 60} minutes ago"
        
        message = (
            f"{urgency} <b>REMINDER</b> ({reminder_count + 1}/3): Unanswered question\n\n"
            f"<b>Question:</b> {question_text}\n"
            f"<b>Asked:</b> {time_ago}\n"
            f"<b>Chat ID:</b> {chat_id}"
        )
        
        # Send reminder
        await bot.send_message(
            ADMIN_USER_ID,
            message,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Update reminder status
        await update_reminder_sent(reminder["id"])
        
    except Exception as e:
        logger.error(f"Error sending reminder: {str(e)}")

async def start_bot():
    """Start the bot and background tasks"""
    # Log startup
    log_startup("Telegram Bot")
    logger.info(f"Bot starting with token: {BOT_TOKEN[:5]}...")
    logger.info(f"Admin user ID: {ADMIN_USER_ID}")
    
    # Start the reminder checker as a background task
    logger.info("Starting background tasks")
    asyncio.create_task(check_reminders_periodically())
    
    # Start polling
    logger.info("Starting bot polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_bot()) 