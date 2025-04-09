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
from bot.bot_config import BOT_TOKEN, ADMIN_USER_ID
from config import OPENAI_MODEL
from utils.db_utils import (
    get_recent_chat_messages, 
    get_pending_reminders, 
    update_reminder_sent,
    get_tasks_by_due_date,
    get_team_productivity,
    get_user_chats
)
from ai_module.ai_analyzer import (
    generate_chat_summary, 
    analyze_productivity,
    suggest_response,
    client
)
from linear_integration.linear_client import LinearClient
from userbot.telegram_client import send_message_as_user
from utils.task_utils import pending_tasks
from utils.logging_utils import setup_bot_logger, log_startup
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
linear_client = LinearClient()
logger = setup_bot_logger()
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
        "/chats - List your available chats\n"
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
        "/chats - List your available chats\n"
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
    args = message.text.split(maxsplit=1)
    chat_name = args[1].strip() if len(args) > 1 else None
    logger.info(f"Summary requested for chat: {chat_name or 'All chats'}")
    processing_msg = await message.reply("Generating summary... This might take a moment.")
    try:
        chat_id = None  # TODO: Implement chat name to ID mapping
        chat_messages = await get_recent_chat_messages(chat_id, hours=24, limit=100)
        if not chat_messages:
            logger.info("No recent messages found to summarize")
            await processing_msg.edit_text("No recent messages found to summarize.")
            return
        logger.debug(f"Found {len(chat_messages)} messages to summarize")
        summary = await generate_chat_summary(
            chat_messages, 
            chat_name or "All monitored chats"
        )
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
        tasks = await get_tasks_by_due_date(days=7)
        if not tasks:
            await processing_msg.edit_text("No pending tasks found for the next 7 days.")
            return
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
        reminders = await get_pending_reminders(ADMIN_USER_ID, hours_threshold=1)
        if not reminders:
            await message.reply("No pending questions or reminders at the moment.")
            return
        response = ["❓ <b>Unanswered Questions</b>\n"]
        for reminder in reminders:
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
        productivity_data = await get_team_productivity(days=7)
        if not productivity_data:
            await processing_msg.edit_text("No productivity data available.")
            return
        analysis = await analyze_productivity(productivity_data)
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
    user_states[message.from_user.id] = AWAITING_TASK_TITLE
    await message.reply(
        "Let's create a new task in Linear.\n\n"
        "Please enter the task title:"
    )
@dp.message(Command("chats"))
async def cmd_chats(message: types.Message):
    """Show the list of user's chats"""
    if message.from_user.id != ADMIN_USER_ID:
        logger.info(f"Unauthorized chats list request from user ID: {message.from_user.id}")
        return
    
    logger.info(f"Chats list requested by user {message.from_user.id}")
    processing_msg = await message.reply("Fetching your chats...")
    
    try:
        # Get all chats for the user
        chats = await get_user_chats(message.from_user.id)
        
        if not chats:
            await processing_msg.edit_text("You don't have any chats yet.")
            return
        
        # Format the chat list
        chat_list = ["📃 <b>Your Chats</b>\n"]
        
        for chat in chats:
            chat_name = chat["chat_name"] if chat["chat_name"] else f"Chat {chat['chat_id']}"
            status = "✅ Active" if chat["is_active"] else "❌ Inactive"
            
            # Format last message time
            last_activity = "Never"
            if chat.get("last_message_time"):
                last_message_time = chat["last_message_time"]
                delta = datetime.utcnow() - last_message_time
                if delta.days > 0:
                    last_activity = f"{delta.days} days ago"
                elif delta.seconds >= 3600:
                    last_activity = f"{delta.seconds // 3600} hours ago"
                else:
                    last_activity = f"{delta.seconds // 60} minutes ago"
            
            chat_info = (
                f"• <b>{chat_name}</b>\n"
                f"  ID: {chat['chat_id']}\n"
                f"  Status: {status}\n"
                f"  Messages: {chat.get('message_count', 0)}\n"
                f"  Last activity: {last_activity}\n"
            )
            chat_list.append(chat_info)
        
        await processing_msg.edit_text("\n".join(chat_list), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error retrieving chats: {str(e)}")
        await processing_msg.edit_text(f"Error retrieving chats: {str(e)}")
@dp.message()
async def handle_all_messages(message: types.Message):
    """Handle all regular messages, including task creation steps and questions"""
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
                f"<b>Title:</b> {issue.get('title')}\n"
                f"<b>ID:</b> {issue.get('identifier')}\n"
                f"<b>URL:</b> {issue.get('url')}",
                parse_mode="HTML"
            )
            
            # Clean up
            del task_creation_data[user_id]
            
        except Exception as e:
            logger.error(f"Error creating Linear task: {str(e)}")
            await message.reply(f"Error creating Linear task: {str(e)}")
            task_creation_data.pop(user_id, None)
    else:
        # Check if the message appears to be a command in natural language
        text = message.text.lower()
        
        # Chat related commands
        if any(pattern in text for pattern in [
            'my chats', 'list chats', 'show chats', 'what chats', 'which chats', 'available chats',
            'chats do i have', 'show my chats', 'my chat list', 'какие у меня чаты', 'мои чаты',
            'список чатов', 'покажи чаты', 'какие чаты'
        ]):
            await cmd_chats(message)
            return
        
        # Task related commands
        elif any(pattern in text for pattern in ['create task', 'add task', 'new task', 'create a task', 'add a task']):
            await cmd_createtask(message)
            return
        elif any(pattern in text for pattern in ['my tasks', 'list tasks', 'show tasks', 'pending tasks', 'task list']):
            await cmd_tasks(message)
            return
            
        # Summary related commands    
        elif any(pattern in text for pattern in ['show summary', 'get summary', 'summarize', 'chat summary', 'conversation summary']):
            await cmd_summary(message)
            return
            
        # Reminder related commands
        elif any(pattern in text for pattern in ['show reminders', 'list reminders', 'pending questions', 'unanswered questions']):
            await cmd_reminders(message)
            return
            
        # Team report commands
        elif any(pattern in text for pattern in ['team report', 'productivity report', 'show report', 'team productivity']):
            await cmd_teamreport(message)
            return
            
        # Help commands
        elif ('help' in text and any(word in text for word in ['show', 'get', 'what', 'how', 'commands'])) or text == 'help':
            await cmd_help(message)
            return
            
        # Try to interpret the intent using AI if no direct command match
        elif any(intent_word in text for intent_word in ['show', 'list', 'get', 'create', 'make', 'add', 'find']):
            try:
                # Use OpenAI to determine the user's intent
                system_prompt = """
                Determine which command the user is trying to access with their natural language request.
                Pay special attention to requests about chats, conversations, or message groups.
                
                Choose from the following commands:
                - chats - Show user's chats list (PRIORITY: If the query is about "what chats", "my chats", "available chats", etc.)
                - summary - Generate a summary of recent conversations
                - tasks - Show pending tasks
                - reminders - Check for unanswered questions
                - teamreport - View team productivity report
                - createtask - Create a new task
                - help - Show all available commands
                
                If the query mentions "chats", "conversations", "dialogs", or similar terms related to messaging, prioritize returning "chats".
                
                Return ONLY the command name and nothing else.
                """
                
                response = await client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message.text}
                    ]
                )
                
                detected_command = response.choices[0].message.content.strip().lower()
                
                # Execute the detected command
                if detected_command == 'tasks':
                    await cmd_tasks(message)
                elif detected_command == 'summary':
                    await cmd_summary(message)
                elif detected_command == 'reminders':
                    await cmd_reminders(message)
                elif detected_command == 'teamreport':
                    await cmd_teamreport(message)
                elif detected_command == 'chats':
                    await cmd_chats(message)
                elif detected_command == 'createtask':
                    await cmd_createtask(message)
                elif detected_command == 'help':
                    await cmd_help(message)
                
            except Exception as e:
                logger.error(f"Error detecting command with AI: {str(e)}")
                # Fall through to question answering
                
        # For any other message, assume it's a question and generate a response using AI
        try:
            # First, check if this is about chats but wasn't caught by our patterns
            # This is a direct override to handle common chat queries that might otherwise
            # go to the general AI response
            if any(word in text for word in ['chat', 'чат', 'conversation', 'dialog']) and \
               any(word in text for word in ['my', 'mine', 'have', 'list', 'show', 'мои', 'есть', 'список', 'покажи']):
                logger.info("Detected chat-related query via keywords, redirecting to chat command")
                await cmd_chats(message)
                return
                
            # Show typing indicator to user
            await bot.send_chat_action(message.chat.id, 'typing')
            
            # Get AI-generated response
            ai_response = await suggest_response(message.text)
            
            # Reply with the generated response
            await message.reply(ai_response)
            
        except Exception as e:
            logger.error(f"Error generating AI response: {str(e)}")
            await message.reply("I'm having trouble processing that right now. Please try again later.")
@dp.callback_query(lambda c: c.data.startswith('respond_'))
async def callback_respond(callback_query: types.CallbackQuery):
    """Handle respond button click for unanswered questions"""
    if callback_query.from_user.id != ADMIN_USER_ID:
        return
    parts = callback_query.data.split('_')
    if len(parts) != 3:
        await callback_query.answer("Invalid callback data")
        return
    chat_id = int(parts[1])
    message_id = int(parts[2])
    await callback_query.answer()
    await bot.send_message(
        callback_query.from_user.id,
        f"Please type your response to the question (from chat {chat_id}, message {message_id}):\n\n"
        f"To cancel, type /cancel"
    )
@dp.callback_query(lambda c: c.data.startswith('ignore_'))
async def callback_ignore(callback_query: types.CallbackQuery):
    """Handle ignore button click for unanswered questions"""
    if callback_query.from_user.id != ADMIN_USER_ID:
        return
    parts = callback_query.data.split('_')
    if len(parts) != 2:
        await callback_query.answer("Invalid callback data")
        return
    reminder_id = int(parts[1])
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
    parts = callback_query.data.split('_')
    if len(parts) != 2:
        await callback_query.answer("Invalid callback data")
        return
    task_id = parts[1]
    if task_id not in pending_tasks:
        await callback_query.answer("Task not found or expired")
        return
    task_data = pending_tasks[task_id]
    await callback_query.answer()
    try:
        await bot.edit_message_text(
            "Creating task in Linear...",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id
        )
        team_id = await linear_client.get_team_id_for_chat(task_data.get("chat_id"))
        if not team_id:
            await bot.edit_message_text(
                "⚠️ Could not determine which Linear team to assign this task to.",
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id
            )
            return
        issue = await linear_client.create_issue(
            title=task_data.get("title", "Untitled Task"),
            description=task_data.get("description", ""),
            team_id=team_id,
            assignee_id=task_data.get("assignee_id"),
            due_date=task_data.get("due_date")
        )
        await bot.edit_message_text(
            f"✅ Task created in Linear!\n\n"
            f"<b>{issue.get('title')}</b>\n"
            f"ID: {issue.get('identifier')}\n"
            f"URL: {issue.get('url')}\n",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            parse_mode="HTML"
        )
        if task_data.get("notify_chat", False):
            chat_id = task_data.get("chat_id")
            await send_message_as_user(
                chat_id,
                f"📋 Created task in Linear: {issue.get('identifier')} - {issue.get('title')}"
            )
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
    parts = callback_query.data.split('_')
    if len(parts) != 2:
        await callback_query.answer("Invalid callback data")
        return
    task_id = parts[1]
    if task_id in pending_tasks:
        del pending_tasks[task_id]
    await callback_query.answer("Task ignored")
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
            reminders = await get_pending_reminders(ADMIN_USER_ID, hours_threshold=1)
            if reminders:
                logger.debug(f"Found {len(reminders)} pending reminders to process")
            reminders = [r for r in reminders if not r.get("is_bot", False)]
            for reminder in reminders:
                reminder_count = reminder.get("reminder_count", 0)
                asked_at = reminder.get("asked_at")
                if reminder_count >= 3:
                    continue
                if reminder_count == 0 and (datetime.utcnow() - asked_at).total_seconds() >= 3600:
                    logger.info(f"Sending first reminder for question from chat {reminder.get('chat_id')}")
                    await send_reminder(reminder)
                elif reminder_count == 1 and (datetime.utcnow() - asked_at).total_seconds() >= 7200:
                    logger.info(f"Sending second reminder for question from chat {reminder.get('chat_id')}")
                    await send_reminder(reminder)
                elif reminder_count == 2 and (datetime.utcnow() - asked_at).total_seconds() >= 14400:
                    logger.info(f"Sending final reminder for question from chat {reminder.get('chat_id')}")
                    await send_reminder(reminder)
            await asyncio.sleep(15 * 60)
        except Exception as e:
            logger.error(f"Error in reminder checker: {str(e)}")
            await asyncio.sleep(60)
async def send_reminder(reminder):
    """Send a reminder about an unanswered question"""
    try:
        question_text = reminder.get("question", "")
        chat_id = reminder.get("chat_id")
        message_id = reminder.get("message_id")
        reminder_count = reminder.get("reminder_count", 0)
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
        await bot.send_message(
            ADMIN_USER_ID,
            message,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await update_reminder_sent(reminder["id"])
    except Exception as e:
        logger.error(f"Error sending reminder: {str(e)}")
async def start_bot():
    """Start the bot and background tasks"""
    # Log startup
    log_startup("Telegram Bot")
    logger.info(f"Bot starting with token: {BOT_TOKEN[:5]}...")
    logger.info(f"Admin user ID: {ADMIN_USER_ID}")
    
    # Initialize database
    from telegram_ai_assistant.utils.db_models import init_db
    logger.info("Initializing database...")
    init_db()
    
    # Start the reminder checker as a background task
    logger.info("Starting background tasks")
    asyncio.create_task(check_reminders_periodically())
    
    # Start polling
    logger.info("Starting bot polling")
    await dp.start_polling(bot)
if __name__ == "__main__":
    asyncio.run(start_bot()) 