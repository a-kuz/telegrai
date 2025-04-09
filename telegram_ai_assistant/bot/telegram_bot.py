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
import re
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telegram_ai_assistant.bot.bot_config import BOT_TOKEN, ADMIN_USER_ID
from telegram_ai_assistant.config import OPENAI_MODEL, LINEAR_TEAM_MAPPING
from telegram_ai_assistant.utils.db_utils import (
    get_recent_chat_messages, 
    get_pending_reminders, 
    update_reminder_sent,
    get_tasks_by_due_date,
    get_team_productivity,
    get_user_chats,
    execute_sql_query
)
from telegram_ai_assistant.ai_module.ai_analyzer import (
    generate_chat_summary, 
    analyze_productivity,
    suggest_response,
    client,
    generate_sql_from_question,
    iterative_reasoning,
    iterative_discussion_summary,
    ai_agent_query
)
from telegram_ai_assistant.ai_module.context_processor import process_question_with_context, analyze_message_intent
from telegram_ai_assistant.linear_integration.linear_client import LinearClient
from telegram_ai_assistant.userbot.telegram_client import send_message_as_user
from telegram_ai_assistant.utils.task_utils import pending_tasks
from telegram_ai_assistant.utils.logging_utils import setup_bot_logger, log_startup
from aiogram.fsm.context import FSMContext
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
linear_client = LinearClient()
logger = setup_bot_logger()
user_states = {}
AWAITING_TASK_TITLE = "awaiting_title"
AWAITING_TASK_DESCRIPTION = "awaiting_description"
AWAITING_TASK_CONFIRMATION = "awaiting_task_confirmation"
task_creation_data = defaultdict(dict)
task_confirmation_data = defaultdict(dict)
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
    """Show available commands"""
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("I'm a personal assistant bot.")
        return
    
    help_text = """
🤖 *Telegram AI Assistant*

*Available Commands:*

📋 *Tasks & Work*
/tasks - View pending tasks from Linear
/createtask - Create a new task in Linear
/dailytasks - View tasks for today
/assigntask - Assign a task to a team member

❓ *Questions & Reminders*
/reminders - Check unanswered questions
/respond - Respond to a pending question

📊 *Insights & Summaries*
/summary [chat_name] - Get a chat summary (all chats or specific)
/teamreport - View team productivity report
/chatactivity - See chat activity statistics
/discussionsummary - Generate step-by-step discussion analysis with corrections

🧠 *AI Functions*
/agent [question] - AI agent that plans & executes DB queries to answer questions
/reason - Solve problems with step-by-step reasoning
/ask - Ask a question using database information
/sqlquery - Run a specific SQL query
/classify - Classify a message by type/intent

🔄 *System & Utilities*
/start - Initialize the bot
/help - Show this help message
/status - Check system status
/settings - Configure bot settings

For any issues or questions about the bot itself, contact the developer.
"""
    await message.reply(help_text, parse_mode="Markdown")
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
        
        # Sort productivity data by message count (descending)
        productivity_data = sorted(
            productivity_data, 
            key=lambda x: x.get('total_messages', 0), 
            reverse=True
        )
        
        for item in productivity_data:
            name = item.get('name', 'Unknown User')
            # Remove any 'None' values that might be appended to the name
            if name.endswith(' None'):
                name = name.replace(' None', '')
            
            # Format message count with thousand separator for readability
            message_count = "{:,}".format(item.get('total_messages', 0))
            tasks_created = item.get('tasks_created', 0)
            tasks_completed = item.get('tasks_completed', 0)
            
            user_stats = (
                f"• <b>{name}</b>:\n"
                f"  Messages: {message_count}\n"
                f"  Tasks created: {tasks_created}\n"
                f"  Tasks completed: {tasks_completed}\n"
            )
            response.append(user_stats)
        
        response.append("\n<b>Analysis:</b>\n" + analysis)
        await processing_msg.edit_text("\n".join(response), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error generating team report: {str(e)}")
        await processing_msg.edit_text(f"Error generating team report: {str(e)}")
@dp.message(Command("createtask"))
async def cmd_createtask(message: types.Message, task_title_from_message: bool = False):
    """Handle /createtask command, create a new task in Linear"""
    user_id = message.from_user.id
    
    # Если сообщение уже содержит название задачи
    if task_title_from_message and message.text:
        text = message.text.strip()
        
        # Извлекаем название задачи из текста сообщения
        title = text
        description = ""
        
        # Удаляем префиксы команд
        prefixes_to_remove = [
            "создай", "создать", "добавь", "добавить", "новый", "новая", 
            "таск", "задача", "задачу", "задание"
        ]
        
        for prefix in prefixes_to_remove:
            if title.lower().startswith(prefix):
                title = title[len(prefix):].strip()
        
        # Проверяем на указание "без описания"
        if "без описания" in title.lower():
            title = title.lower().replace("без описания", "").strip()
        
        # Если после обработки осталось название
        if title:
            processing_msg = await message.reply(f"Создаю задачу с названием: {title}")
            
            try:
                # Get team ID
                team_id = await linear_client.get_team_id_for_chat(message.chat.id)
                
                if not team_id:
                    # Проверяем и загружаем конфигурацию LINEAR_TEAM_MAPPING
                    from telegram_ai_assistant.config import LINEAR_TEAM_MAPPING
                    
                    logger.debug(f"LINEAR_TEAM_MAPPING: {LINEAR_TEAM_MAPPING}")
                    
                    if not LINEAR_TEAM_MAPPING or not isinstance(LINEAR_TEAM_MAPPING, dict):
                        error_msg = "❌ Ошибка: LINEAR_TEAM_MAPPING не настроен или некорректный формат. Проверьте .env файл."
                        logger.error(error_msg)
                        await processing_msg.edit_text(error_msg)
                        return
                        
                    # Проверяем наличие default команды
                    if "default" not in LINEAR_TEAM_MAPPING:
                        error_msg = "❌ Ошибка: В LINEAR_TEAM_MAPPING отсутствует 'default' команда. Добавьте её в .env файл."
                        logger.error(error_msg)
                        await processing_msg.edit_text(error_msg)
                        return
                        
                    team_id = LINEAR_TEAM_MAPPING.get("default")
                    
                if not team_id:
                    await processing_msg.edit_text("❌ Error: Could not determine which Linear team to assign this task to.")
                    return
                
                # Логируем данные для отладки
                logger.info(f"Creating Linear task with title: '{title}', team_id: '{team_id}'")
                
                # Create issue in Linear
                issue = await linear_client.create_issue(
                    title=title,
                    description=description,
                    team_id=team_id
                )
                
                # Send confirmation
                await processing_msg.edit_text(
                    f"✅ Задача создана в Linear!\n\n"
                    f"<b>Название:</b> {issue.get('title')}\n"
                    f"<b>ID:</b> {issue.get('identifier')}\n"
                    f"<b>URL:</b> {issue.get('url')}",
                    parse_mode="HTML"
                )
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error creating Linear task: {error_msg}", exc_info=True)
                
                # Добавляем более информативное сообщение в зависимости от типа ошибки
                if "Argument Validation Error" in error_msg:
                    error_display = "❌ Ошибка при создании задачи: Ошибка валидации данных. Возможно, неверный ID команды или другие параметры.\n\nПроверьте настройки LINEAR_TEAM_MAPPING в файле .env"
                elif "authentication failed" in error_msg.lower():
                    error_display = "❌ Ошибка аутентификации в Linear API. Проверьте токен LINEAR_API_KEY в файле .env"
                else:
                    error_display = f"❌ Ошибка при создании задачи: {error_msg}"
                
                await processing_msg.edit_text(error_display)
            
            return
    
    # Стандартный поток создания задачи через состояния
    user_states[user_id] = AWAITING_TASK_TITLE
    await message.reply(
        "Please enter a title for the new task:"
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
        # Get all chats from the database directly
        from telegram_ai_assistant.utils.db_utils import execute_sql_query
        
        # Simple direct query to get all chats
        sql_query = """
        SELECT 
            chats.id, 
            chats.chat_id, 
            chats.chat_name, 
            chats.is_active,
            (SELECT COUNT(*) FROM messages WHERE messages.chat_id = chats.chat_id) as message_count,
            (SELECT MAX(timestamp) FROM messages WHERE messages.chat_id = chats.chat_id) as last_message_time
        FROM chats
        ORDER BY message_count DESC
        """
        
        # Execute the query directly
        logger.info(f"Executing SQL query: {sql_query}")
        query_result = await execute_sql_query(sql_query)
        
        if not query_result:
            await processing_msg.edit_text("You don't have any chats yet.")
            return
        
        # Format the chat list
        chat_list = ["📃 <b>Your Chats</b>\n"]
        
        for chat in query_result:
            chat_name = chat.get("chat_name") if chat.get("chat_name") else f"Chat {chat.get('chat_id')}"
            status = "✅ Active" if chat.get("is_active") else "❌ Inactive"
            
            # Format last message time
            last_activity = "Never"
            if chat.get("last_message_time"):
                last_message_time = datetime.fromisoformat(chat.get("last_message_time"))
                delta = datetime.utcnow() - last_message_time
                if delta.days > 0:
                    last_activity = f"{delta.days} days ago"
                elif delta.seconds >= 3600:
                    last_activity = f"{delta.seconds // 3600} hours ago"
                else:
                    last_activity = f"{delta.seconds // 60} minutes ago"
            
            chat_info = (
                f"• <b>{chat_name}</b>\n"
                f"  ID: {chat.get('chat_id')}\n"
                f"  Status: {status}\n"
                f"  Messages: {chat.get('message_count', 0)}\n"
                f"  Last activity: {last_activity}\n"
            )
            chat_list.append(chat_info)
        
        await processing_msg.edit_text("\n".join(chat_list), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error retrieving chats: {str(e)}")
        await processing_msg.edit_text(f"Error retrieving chats: {str(e)}")
@dp.message(Command("ask"))
async def cmd_ask(message: types.Message):
    """Ask a question using natural language"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    try:
        # Get the question from the message text (remove the /ask command)
        text = message.text
        parts = text.split(maxsplit=1)
        
        if len(parts) < 2:
            await message.reply(
                "Please provide a question. Usage:\n"
                "/ask [your question]\n\n"
                "To use the old context-based approach, add the --old flag:\n"
                "/ask --old [your question]"
            )
            return
        
        # Check for flags
        query_text = parts[1]
        use_legacy_mode = False
        show_details = False
        
        if "--old" in query_text:
            use_legacy_mode = True
            query_text = query_text.replace("--old", "").strip()
        
        if "--details" in query_text or "-d" in query_text:
            show_details = True
            query_text = query_text.replace("--details", "").replace("-d", "").strip()
        
        if use_legacy_mode:
            # Use the old context-based approach
            processing_msg = await message.reply("Обрабатываю ваш вопрос...")
            
            try:
                chat_id = message.chat.id
                result = await process_question_with_context(query_text, chat_id)
                
                answer = result.get("answer", "Не удалось сформировать ответ")
                
                if show_details:
                    context_used = result.get("context_used", "unknown")
                    details = result.get("details", {})
                    
                    details_text = f"\n\n<b>📊 Контекст:</b> {context_used}"
                    
                    if context_used == "database_query" and "sql_query" in details:
                        details_text += f"\n<b>SQL:</b>\n<pre>{details['sql_query']}</pre>"
                    
                    answer += details_text
                
                await processing_msg.edit_text(answer, parse_mode="HTML")
                logger.info(f"Processed contextual question: {query_text[:50]}...")
            except Exception as e:
                logger.error(f"Error processing contextual question: {str(e)}")
                await processing_msg.edit_text(f"Произошла ошибка: {str(e)}")
        else:
            # Use the new autonomous AI agent approach
            await message.reply(
                "🤖 Starting AI analysis of your question...\n"
                "I'll plan and execute the necessary database queries to find your answer."
            )
            
            # Start the autonomous agent
            from telegram_ai_assistant.ai_module.ai_analyzer import ai_agent_query
            asyncio.create_task(ai_agent_query(query_text))
            
            logger.info(f"Started autonomous AI agent for question: {query_text[:50]}...")
    
    except Exception as e:
        logger.error(f"Error in ask command: {str(e)}")
        await message.reply(f"Error processing your question: {str(e)}")
@dp.message(Command("reason"))
async def cmd_reason(message: types.Message):
    """Solve a problem using iterative reasoning with visible thought process"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    try:
        # Get the question from the message text (remove the /reason command)
        command_parts = message.text.split(maxsplit=1)
        if len(command_parts) < 2:
            await message.reply(
                "Please provide a question or problem to reason about.\n"
                "Example: /reason Calculate the compound interest on $1000 invested for 5 years at 8% annual interest rate with quarterly compounding."
            )
            return
        
        question = command_parts[1].strip()
        
        # Let the user know we're starting the reasoning process
        intro_message = await message.reply(
            "🧠 Starting iterative reasoning process...\n"
            "I'll think step-by-step and show my work in a continuously updated message."
        )
        
        # We don't need to await the result here since the iterative_reasoning
        # function itself will update the Telegram message as it progresses
        asyncio.create_task(iterative_reasoning(question, max_attempts=3))
        
        logger.info(f"Started iterative reasoning for question: {question[:50]}...")
        
    except Exception as e:
        logger.error(f"Error in reasoning command: {str(e)}")
        await message.reply(f"Error starting reasoning process: {str(e)}")
@dp.message(Command("discussionsummary"))
async def cmd_discussion_summary(message: types.Message):
    """Generate a comprehensive discussion summary with step-by-step analysis and error correction"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    try:
        # Parse command arguments
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        # Default values
        chat_id = None
        time_period = "24h"
        
        # Process arguments if any
        for arg in args:
            if arg.startswith("chat="):
                try:
                    chat_id = int(arg.split("=")[1])
                except ValueError:
                    await message.reply("Invalid chat ID format. Use numbers only.")
                    return
            elif arg in ["24h", "7d", "30d"]:
                time_period = arg
        
        # Show options if no specific chat selected
        if chat_id is None:
            from telegram_ai_assistant.utils.db_utils import execute_sql_query
            
            # Get recent active chats
            chats_query = """
            SELECT 
                chats.id, 
                chats.chat_id, 
                chats.chat_name, 
                chats.is_active,
                (SELECT COUNT(*) FROM messages WHERE messages.chat_id = chats.chat_id) as message_count,
                (SELECT MAX(timestamp) FROM messages WHERE messages.chat_id = chats.chat_id) as last_message_time
            FROM chats
            WHERE chats.is_active = 1
            ORDER BY last_message_time DESC
            LIMIT 10
            """
            chats = await execute_sql_query(chats_query)
            
            if not chats:
                await message.reply("No active chats found in the database.")
                return
            
            # Create inline keyboard with chat options
            keyboard = []
            for chat in chats:
                chat_name = chat.get("chat_name") or f"Chat {chat.get('chat_id')}"
                msg_count = chat.get("message_count", 0)
                callback_data = f"summarize_chat:{chat.get('chat_id')}:{time_period}"
                keyboard.append([InlineKeyboardButton(
                    text=f"{chat_name} ({msg_count} messages)", 
                    callback_data=callback_data
                )])
            
            # Add option for all chats
            keyboard.append([InlineKeyboardButton(
                text="📊 All active chats", 
                callback_data=f"summarize_chat:all:{time_period}"
            )])
            
            # Add time period options
            keyboard.append([
                InlineKeyboardButton(text="24 hours", callback_data=f"change_period:24h"),
                InlineKeyboardButton(text="7 days", callback_data=f"change_period:7d"),
                InlineKeyboardButton(text="30 days", callback_data=f"change_period:30d")
            ])
            
            # Send message with options
            await message.reply(
                f"🔍 *Discussion Summary Generation*\n\n"
                f"Please select a chat to analyze or choose 'All active chats'.\n"
                f"Current time period: *{time_period}*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        else:
            # Start the iterative summary process directly if chat ID provided
            await message.reply(
                f"🔍 *Starting iterative discussion summary for chat {chat_id}*\n\n"
                f"Time period: *{time_period}*\n\n"
                f"I'll guide you through the analysis process step by step, allowing corrections at each stage.",
                parse_mode="Markdown"
            )
            
            # Start the analysis process
            asyncio.create_task(iterative_discussion_summary(chat_id, time_period))
            
            logger.info(f"Started iterative discussion summary for chat_id={chat_id}, period={time_period}")
            
    except Exception as e:
        logger.error(f"Error in discussion summary command: {str(e)}")
        await message.reply(f"Error starting discussion summary: {str(e)}")

@dp.callback_query(lambda c: c.data.startswith(("summarize_chat:", "change_period:", "try_different_period", "retry_", "continue_", "accept_", "refine_")))
async def summary_callback_handler(callback_query: types.CallbackQuery):
    """Handle callbacks for the iterative discussion summary feature"""
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer("You are not authorized to use this feature.")
        return
    
    try:
        # Extract callback data
        data = callback_query.data
        logger.debug(f"Received callback: {data}")
        
        # Process different callback types
        if data.startswith("summarize_chat:"):
            # Format: summarize_chat:chat_id:time_period
            parts = data.split(":")
            if len(parts) >= 3:
                chat_id_str = parts[1]
                time_period = parts[2]
                
                chat_id = None if chat_id_str == "all" else int(chat_id_str)
                
                # Acknowledge the callback
                await callback_query.answer("Starting analysis...")
                
                # Update message to show we're starting
                chat_info = "all chats" if chat_id is None else f"chat {chat_id}"
                await callback_query.message.edit_text(
                    f"🔍 *Starting iterative discussion summary for {chat_info}*\n\n"
                    f"Time period: *{time_period}*\n\n"
                    f"I'll guide you through the analysis process step by step, allowing corrections at each stage.",
                    parse_mode="Markdown"
                )
                
                # Start the analysis process
                asyncio.create_task(iterative_discussion_summary(chat_id, time_period))
                
                logger.info(f"Started iterative discussion summary for chat_id={chat_id}, period={time_period}")
                
        elif data.startswith("change_period:"):
            # Format: change_period:new_period
            parts = data.split(":")
            if len(parts) >= 2:
                new_period = parts[1]
                
                # Acknowledge the callback
                await callback_query.answer(f"Changed time period to {new_period}")
                
                # Get current inline keyboard
                current_keyboard = callback_query.message.reply_markup.inline_keyboard
                
                # Update only the period-related buttons (last row)
                for i, row in enumerate(current_keyboard):
                    for j, button in enumerate(row):
                        if button.callback_data.startswith("summarize_chat:"):
                            # Update button data with new period
                            chat_part = button.callback_data.split(":")[1]
                            current_keyboard[i][j].callback_data = f"summarize_chat:{chat_part}:{new_period}"
                
                # Set all period buttons to normal except the selected one
                period_row = current_keyboard[-1]
                for i, button in enumerate(period_row):
                    period = button.callback_data.split(":")[-1]
                    if period == new_period:
                        period_row[i].text = f"✅ {button.text.replace('✅ ', '')}"
                    else:
                        period_row[i].text = button.text.replace('✅ ', '')
                
                # Update message with new time period
                await callback_query.message.edit_text(
                    f"🔍 *Discussion Summary Generation*\n\n"
                    f"Please select a chat to analyze or choose 'All active chats'.\n"
                    f"Current time period: *{new_period}*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=current_keyboard)
                )
        
        elif data == "try_different_period":
            # Show period options
            await callback_query.answer("Select a different time period")
            
            keyboard = [
                [InlineKeyboardButton(text="24 hours", callback_data="retry_with_period:24h")],
                [InlineKeyboardButton(text="3 days", callback_data="retry_with_period:3d")],
                [InlineKeyboardButton(text="7 days", callback_data="retry_with_period:7d")],
                [InlineKeyboardButton(text="14 days", callback_data="retry_with_period:14d")],
                [InlineKeyboardButton(text="30 days", callback_data="retry_with_period:30d")]
            ]
            
            await callback_query.message.edit_text(
                "📅 *Select Different Time Period*\n\n"
                "No messages were found in the current time period.\n"
                "Please select a different time period to analyze:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        
        elif data.startswith("retry_with_period:"):
            # Extract new period
            new_period = data.split(":")[1]
            
            # Get chat ID from message context if available
            message_text = callback_query.message.text
            chat_id = None
            
            if "chat " in message_text and " failed" in message_text:
                # Try to extract chat ID from message
                try:
                    chat_match = re.search(r"chat (\d+)", message_text)
                    if chat_match:
                        chat_id = int(chat_match.group(1))
                except ValueError:
                    chat_id = None
            
            # Acknowledge the callback
            await callback_query.answer(f"Retrying with {new_period}")
            
            # Update message
            await callback_query.message.edit_text(
                f"🔄 *Retrying Summary*\n\n"
                f"Attempting to generate summary with new time period: {new_period}",
                parse_mode="Markdown"
            )
            
            # Start new analysis with different period
            asyncio.create_task(iterative_discussion_summary(chat_id, new_period))
            
            logger.info(f"Retrying iterative discussion summary for chat_id={chat_id}, period={new_period}")
        
        elif data.startswith("retry_") or data.startswith("continue_") or data.startswith("accept_") or data.startswith("refine_"):
            # These callbacks are handled directly by the iterative_discussion_summary function
            # Just acknowledge the callback
            await callback_query.answer("Processing...")
            
            # The actual handling is done by updating the state in the iterative_discussion_summary function
            # We'll just log the callback for now
            logger.info(f"Received '{data}' callback, will be processed by the summary function")
            
            # Special handling for refine_topics and refine_summary - show input prompt
            if data == "refine_topics":
                # Create a temporary state for this conversation
                state = dp.current_state(chat=callback_query.message.chat.id, user=callback_query.from_user.id)
                await state.set_state("waiting_for_topic_refinement")
                await state.update_data(message_id=callback_query.message.message_id)
                
                await callback_query.message.reply(
                    "✏️ *Refine Topics*\n\n"
                    "Please provide your suggestions for how to improve the topic analysis. For example:\n"
                    "- Add missing topics\n"
                    "- Remove irrelevant topics\n"
                    "- Refocus the analysis\n\n"
                    "Type your suggestions below:",
                    parse_mode="Markdown"
                )
            
            elif data == "refine_summary":
                # Create a temporary state for this conversation
                state = dp.current_state(chat=callback_query.message.chat.id, user=callback_query.from_user.id)
                await state.set_state("waiting_for_summary_refinement")
                await state.update_data(message_id=callback_query.message.message_id)
                
                await callback_query.message.reply(
                    "✏️ *Refine Summary*\n\n"
                    "Please provide your suggestions for how to improve the final summary. For example:\n"
                    "- Add missing information\n"
                    "- Focus on specific aspects\n"
                    "- Change the tone or style\n\n"
                    "Type your suggestions below:",
                    parse_mode="Markdown"
                )
            
    except Exception as e:
        logger.error(f"Error handling summary callback: {str(e)}")
        await callback_query.answer(f"Error: {str(e)}", show_alert=True)

# State handlers for refinement inputs
@dp.message(lambda message: message.text and message.from_user.id == ADMIN_USER_ID)
async def process_refinement_input(message: types.Message, state: FSMContext):
    """Process user input for topic or summary refinement"""
    current_state = await state.get_state()
    
    if current_state == "waiting_for_topic_refinement":
        # Process topic refinement
        user_input = message.text
        state_data = await state.get_data()
        message_id = state_data.get("message_id")
        
        await message.reply(
            "🔄 *Processing Topic Refinement*\n\n"
            "Thank you for your input. I'm updating the topic analysis with your suggestions.",
            parse_mode="Markdown"
        )
        
        # Reset the state
        await state.clear()
        
        # TODO: Process the refinement in the ongoing summary analysis
        logger.info(f"Received topic refinement: {user_input}")
        
    elif current_state == "waiting_for_summary_refinement":
        # Process summary refinement
        user_input = message.text
        state_data = await state.get_data()
        message_id = state_data.get("message_id")
        
        await message.reply(
            "🔄 *Processing Summary Refinement*\n\n"
            "Thank you for your input. I'm updating the final summary with your suggestions.",
            parse_mode="Markdown"
        )
        
        # Reset the state
        await state.clear()
        
        # TODO: Process the refinement in the ongoing summary analysis
        logger.info(f"Received summary refinement: {user_input}")

@dp.message()
async def handle_message(message: types.Message):
    """Process regular messages"""
    user_id = message.from_user.id
    
    # Prevent processing messages in groups unless bot is mentioned
    if message.chat.type in ['group', 'supergroup']:
        # Skip processing if not mentioned, not a reply to bot, and not a direct command
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        
        is_mentioned = False
        if message.text:
            is_mentioned = f"@{bot_username}" in message.text or message.text.startswith("/")
        
        is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == bot.id
        
        if not (is_mentioned or is_reply_to_bot):
            return
    
    # Skip processing for bot commands
    if message.text and message.text.startswith("/"):
        return
        
    # Only process task creation flow for any user
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
        return
    
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
        processing_msg = await message.reply("Creating task in Linear...")
        
        try:
            # Get team ID
            team_id = await linear_client.get_team_id_for_chat(message.chat.id)
            
            if not team_id:
                # Проверяем и загружаем конфигурацию LINEAR_TEAM_MAPPING
                from telegram_ai_assistant.config import LINEAR_TEAM_MAPPING
                
                logger.debug(f"LINEAR_TEAM_MAPPING: {LINEAR_TEAM_MAPPING}")
                
                if not LINEAR_TEAM_MAPPING or not isinstance(LINEAR_TEAM_MAPPING, dict):
                    error_msg = "❌ Ошибка: LINEAR_TEAM_MAPPING не настроен или некорректный формат. Проверьте .env файл."
                    logger.error(error_msg)
                    await processing_msg.edit_text(error_msg)
                    task_creation_data.pop(user_id, None)
                    return
                    
                # Проверяем наличие default команды
                if "default" not in LINEAR_TEAM_MAPPING:
                    error_msg = "❌ Ошибка: В LINEAR_TEAM_MAPPING отсутствует 'default' команда. Добавьте её в .env файл."
                    logger.error(error_msg)
                    await processing_msg.edit_text(error_msg)
                    task_creation_data.pop(user_id, None)
                    return
                    
                team_id = LINEAR_TEAM_MAPPING.get("default")
                
            if not team_id:
                await processing_msg.edit_text("❌ Error: Could not determine which Linear team to assign this task to.")
                task_creation_data.pop(user_id, None)
                return
            
            # Логируем данные для отладки
            title = task_creation_data[user_id]["title"]
            logger.info(f"Creating Linear task with title: '{title}', team_id: '{team_id}'")
            
            # Create issue in Linear
            issue = await linear_client.create_issue(
                title=title,
                description=task_description,
                team_id=team_id
            )
            
            # Send confirmation
            await processing_msg.edit_text(
                f"✅ Task created in Linear!\n\n"
                f"<b>Title:</b> {issue.get('title')}\n"
                f"<b>ID:</b> {issue.get('identifier')}\n"
                f"<b>URL:</b> {issue.get('url')}",
                parse_mode="HTML"
            )
            
            # Clean up
            del task_creation_data[user_id]
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error creating Linear task: {error_msg}", exc_info=True)
            
            # Добавляем более информативное сообщение в зависимости от типа ошибки
            if "Argument Validation Error" in error_msg:
                error_display = "❌ Ошибка при создании задачи: Ошибка валидации данных. Возможно, неверный ID команды или другие параметры.\n\nПроверьте настройки LINEAR_TEAM_MAPPING в файле .env"
            elif "authentication failed" in error_msg.lower():
                error_display = "❌ Ошибка аутентификации в Linear API. Проверьте токен LINEAR_API_KEY в файле .env"
            else:
                error_display = f"❌ Ошибка при создании задачи: {error_msg}"
            
            await processing_msg.edit_text(error_display)
            task_creation_data.pop(user_id, None)
        return
    
    # Process message using intent detection
    if message.text:
        # Get recent message history for context
        try:
            from telegram_ai_assistant.utils.db_utils import get_recent_chat_messages, execute_sql_query
            
            # Display a typing indicator while processing
            await bot.send_chat_action(message.chat.id, 'typing')
            
            # Generate SQL directly for common database queries
            processing_msg = await message.reply("Анализирую...")
            
            # Determine if this is a database query
            from telegram_ai_assistant.ai_module.ai_analyzer import generate_sql_from_question
            
            # 1. Try to generate SQL query directly
            sql_response = await generate_sql_from_question(message.text)
            
            # Check if we have a valid SQL query
            if sql_response and "sql_query" in sql_response and sql_response["sql_query"].strip():
                sql_query = sql_response["sql_query"]
                explanation = sql_response.get("explanation", "Выполняю SQL запрос")
                
                logger.info(f"Generated SQL query: {sql_query}")
                
                # Log generated SQL
                logger.info(f"AI generated SQL for question: {message.text}")
                logger.info(f"SQL: {sql_query}")
                
                # Fix common SQL errors
                if "chat_history" in sql_query.lower():
                    logger.info("Fixing reference to non-existent chat_history table")
                    sql_query = sql_query.lower().replace("chat_history", "messages")
                
                # Execute the query
                try:
                    logger.info("Executing SQL query...")
                    query_result = await execute_sql_query(sql_query)
                    
                    # Format results for display
                    if query_result:
                        # Create response message based on the query results
                        if isinstance(query_result, list) and len(query_result) > 0:
                            if "error" in query_result[0]:
                                # Error occurred
                                await processing_msg.edit_text(f"❌ Ошибка выполнения SQL запроса: {query_result[0]['error']}")
                                return
                                
                            # Format SQL results for better readability
                            if len(query_result) > 1:
                                # Format as table-like text for multiple rows
                                columns = list(query_result[0].keys())
                                
                                # Create a response with the query results
                                result_text = await client.chat.completions.create(
                                    model=OPENAI_MODEL,
                                    messages=[
                                        {"role": "system", "content": "Ты аналитик данных. Твоя задача объяснить результаты SQL запроса кратко и понятно. Не упоминай SQL или запросы в ответе, просто интерпретируй данные как обычный человек. Используй факты из данных, не придумывай информацию."},
                                        {"role": "user", "content": f"Вопрос пользователя: {message.text}\n\nРезультаты запроса ({len(query_result)} строк):\n{json.dumps(query_result, indent=2, ensure_ascii=False)}\n\nДай лаконичное объяснение этих данных на русском языке, не упоминая сам SQL запрос."}
                                    ]
                                )
                                
                                response_text = result_text.choices[0].message.content.strip()
                                await processing_msg.edit_text(response_text)
                            else:
                                # Single row result
                                result_text = await client.chat.completions.create(
                                    model=OPENAI_MODEL,
                                    messages=[
                                        {"role": "system", "content": "Ты аналитик данных. Твоя задача объяснить результаты SQL запроса кратко и понятно. Не упоминай SQL или запросы в ответе, просто интерпретируй данные как обычный человек. Используй факты из данных, не придумывай информацию."},
                                        {"role": "user", "content": f"Вопрос пользователя: {message.text}\n\nРезультаты запроса (1 строка):\n{json.dumps(query_result[0], indent=2, ensure_ascii=False)}\n\nДай лаконичное объяснение этих данных на русском языке, не упоминая сам SQL запрос."}
                                    ]
                                )
                                
                                response_text = result_text.choices[0].message.content.strip()
                                await processing_msg.edit_text(response_text)
                        else:
                            await processing_msg.edit_text("Не найдены данные, соответствующие запросу.")
                    else:
                        await processing_msg.edit_text("По вашему запросу не найдено данных в базе.")
                        
                    return
                except Exception as e:
                    logger.error(f"Error executing SQL query: {str(e)}")
                    # If SQL execution fails, fallback to context processor
            
            # 2. Fallback to analyze_message_intent for task creation/candidates
            # Get recent messages for context analysis
            recent_messages = await get_recent_chat_messages(message.chat.id, limit=10)
            
            # Analyze message intent
            intent_analysis = await analyze_message_intent(message.text, recent_messages)
            
            logger.info(f"Message intent analysis: task_creation={intent_analysis['task_creation_score']}, "
                        f"task_candidate={intent_analysis['task_candidate_score']}, "
                        f"db_query={intent_analysis['database_query_score']}")
            
            # Handle direct task creation request (high task_creation_score)
            if intent_analysis['primary_intent'] == 'task_creation' and intent_analysis['task_creation_score'] >= 7:
                # Extract title and description
                title = intent_analysis['task_title']
                description = intent_analysis['task_description']
                
                if not title:
                    title = "Untitled task"
                
                # Prepare task confirmation
                task_confirmation_data[user_id] = {
                    "title": title,
                    "description": description,
                    "chat_id": message.chat.id,
                    "original_message_id": message.message_id,
                    "context_analyzed": True
                }
                
                # Set state
                user_states[user_id] = AWAITING_TASK_CONFIRMATION
                
                # Create inline buttons
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Создать задачу", 
                            callback_data=f"confirm_task_{user_id}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Отмена", 
                            callback_data=f"cancel_task_{user_id}"
                        )
                    ]
                ])
                
                # Send confirmation message
                await processing_msg.edit_text(
                    f"Создать следующую задачу?\n\n"
                    f"<b>Название:</b> {title}\n\n"
                    f"<b>Описание:</b>\n{description}",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
                
            # Handle task candidate (problem description that could be a task)
            elif intent_analysis['primary_intent'] == 'task_candidate' and intent_analysis['task_candidate_score'] >= 7:
                # Extract suggested title and description
                title = intent_analysis['task_title']
                description = intent_analysis['task_description']
                
                if not title:
                    title = "Untitled task"
                
                # Prepare task confirmation
                task_confirmation_data[user_id] = {
                    "title": title,
                    "description": description,
                    "chat_id": message.chat.id,
                    "original_message_id": message.message_id,
                    "context_analyzed": True
                }
                
                # Set state
                user_states[user_id] = AWAITING_TASK_CONFIRMATION
                
                # Create inline buttons
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Создать задачу", 
                            callback_data=f"confirm_task_{user_id}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Отмена", 
                            callback_data=f"cancel_task_{user_id}"
                        )
                    ]
                ])
                
                # Send confirmation message with note that this was extracted from description
                await processing_msg.edit_text(
                    f"Похоже, вы описали проблему. Создать задачу на её основе?\n\n"
                    f"<b>Название:</b> {title}\n\n"
                    f"<b>Описание:</b>\n{description}",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
                
            # 3. Final fallback - process with context processor
            available_chats = await get_user_chats()
            
            # Process with context processor
            await processing_msg.edit_text("Анализирую вопрос...")
            
            result = await process_question_with_context(
                question=message.text, 
                chat_id=message.chat.id, 
                available_chats=available_chats
            )
            
            # Update message with result
            logger.info("Получен ответ с контекстом, обновляем сообщение")
            if "answer" in result:
                await processing_msg.edit_text(result["answer"])
            else:
                logger.warning("Missing 'answer' key in context processor result")
                await processing_msg.edit_text("Не удалось сформировать ответ на ваш вопрос. Пожалуйста, уточните запрос.")
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            await message.reply(f"Произошла ошибка при обработке сообщения: {str(e)}")
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
@dp.callback_query(lambda c: c.data.startswith('confirm_task_'))
async def callback_confirm_task(callback_query: types.CallbackQuery):
    """Handle confirm task button click"""
    parts = callback_query.data.split('_')
    if len(parts) != 3:
        await callback_query.answer("Неверный формат данных")
        return
        
    user_id = int(parts[2])
    
    # Проверяем, что у нас есть данные для этого пользователя
    if user_id not in task_confirmation_data:
        await callback_query.answer("Данные задачи не найдены или устарели")
        return
        
    # Получаем данные задачи
    task_data = task_confirmation_data[user_id]
    
    # Подтверждаем действие и изменяем текст кнопок
    await callback_query.answer("Создаю задачу...")
    
    # Изменяем сообщение, чтобы показать процесс создания
    await bot.edit_message_text(
        f"Создаю задачу «<b>{task_data['title']}</b>»...",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        parse_mode="HTML"
    )
    
    try:
        # Получаем team ID
        team_id = await linear_client.get_team_id_for_chat(task_data["chat_id"])
        
        if not team_id:
            # Проверяем и загружаем конфигурацию LINEAR_TEAM_MAPPING
            from telegram_ai_assistant.config import LINEAR_TEAM_MAPPING
            
            logger.debug(f"LINEAR_TEAM_MAPPING: {LINEAR_TEAM_MAPPING}")
            
            if not LINEAR_TEAM_MAPPING or not isinstance(LINEAR_TEAM_MAPPING, dict):
                error_msg = "❌ Ошибка: LINEAR_TEAM_MAPPING не настроен или некорректный формат. Проверьте .env файл."
                logger.error(error_msg)
                await bot.edit_message_text(
                    error_msg,
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id
                )
                return
                
            # Проверяем наличие default команды
            if "default" not in LINEAR_TEAM_MAPPING:
                error_msg = "❌ Ошибка: В LINEAR_TEAM_MAPPING отсутствует 'default' команда. Добавьте её в .env файл."
                logger.error(error_msg)
                await bot.edit_message_text(
                    error_msg,
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id
                )
                return
                
            team_id = LINEAR_TEAM_MAPPING.get("default")
            
        if not team_id:
            await bot.edit_message_text(
                "❌ Ошибка: Не удалось определить команду в Linear для назначения задачи.",
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id
            )
            return
        
        # Логируем данные для отладки
        logger.info(f"Creating Linear task with title: '{task_data['title']}', team_id: '{team_id}'")
        
        # Создаем задачу в Linear
        issue = await linear_client.create_issue(
            title=task_data["title"],
            description=task_data["description"],
            team_id=team_id
        )
        
        # Обновляем сообщение с результатом
        await bot.edit_message_text(
            f"✅ Задача успешно создана в Linear!\n\n"
            f"<b>Название:</b> {issue.get('title')}\n"
            f"<b>ID:</b> {issue.get('identifier')}\n"
            f"<b>URL:</b> {issue.get('url')}",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            parse_mode="HTML"
        )
        
        # Очищаем данные
        del task_confirmation_data[user_id]
        if user_id in user_states and user_states[user_id] == AWAITING_TASK_CONFIRMATION:
            user_states.pop(user_id)
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating Linear task: {error_msg}", exc_info=True)
        
        # Добавляем более информативное сообщение в зависимости от типа ошибки
        if "Argument Validation Error" in error_msg:
            error_display = "❌ Ошибка при создании задачи: Ошибка валидации данных. Возможно, неверный ID команды или другие параметры.\n\nПроверьте настройки LINEAR_TEAM_MAPPING в файле .env"
        elif "authentication failed" in error_msg.lower():
            error_display = "❌ Ошибка аутентификации в Linear API. Проверьте токен LINEAR_API_KEY в файле .env"
        else:
            error_display = f"❌ Ошибка при создании задачи: {error_msg}"
        
        await bot.edit_message_text(
            error_display,
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id
        )
        
        # Очищаем данные при ошибке
        task_confirmation_data.pop(user_id, None)
        if user_id in user_states and user_states[user_id] == AWAITING_TASK_CONFIRMATION:
            user_states.pop(user_id)

@dp.callback_query(lambda c: c.data.startswith('cancel_task_'))
async def callback_cancel_task(callback_query: types.CallbackQuery):
    """Handle cancel task button click"""
    parts = callback_query.data.split('_')
    if len(parts) != 3:
        await callback_query.answer("Неверный формат данных")
        return
        
    user_id = int(parts[2])
    
    # Подтверждаем отмену
    await callback_query.answer("Создание задачи отменено")
    
    # Обновляем сообщение
    await bot.edit_message_text(
        "❌ Создание задачи отменено.",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id
    )
    
    # Очищаем данные
    task_confirmation_data.pop(user_id, None)
    if user_id in user_states and user_states[user_id] == AWAITING_TASK_CONFIRMATION:
        user_states.pop(user_id)

@dp.message(Command("agent"))
async def cmd_ai_agent(message: types.Message):
    """Use the autonomous AI agent to answer any question by planning and executing DB queries"""
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    try:
        # Get the question from the message text (remove the /agent command)
        command_parts = message.text.split(maxsplit=1)
        if len(command_parts) < 2:
            await message.reply(
                "Please provide a question for the AI agent to answer.\n"
                "Example: /agent What were the most active chats in the last week?"
            )
            return
        
        question = command_parts[1].strip()
        
        # Let the user know we're starting the autonomous reasoning process
        await message.reply(
            "🤖 Starting autonomous AI agent process for your question...\n"
            "The agent will plan and execute database queries to find the answer."
        )
        
        # Start the autonomous agent
        asyncio.create_task(ai_agent_query(question))
        
        logger.info(f"Started autonomous AI agent for question: {question[:50]}...")
        
    except Exception as e:
        logger.error(f"Error starting AI agent: {str(e)}")
        await message.reply(f"Error starting the AI agent process: {str(e)}")

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