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
    generate_sql_from_question
)
from telegram_ai_assistant.ai_module.context_processor import process_question_with_context, analyze_message_intent
from telegram_ai_assistant.linear_integration.linear_client import LinearClient
from telegram_ai_assistant.userbot.telegram_client import send_message_as_user
from telegram_ai_assistant.utils.task_utils import pending_tasks
from telegram_ai_assistant.utils.logging_utils import setup_bot_logger, log_startup
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
        "/ask [question] - Query the database using natural language\n"
        "  • Добавьте флаг --details или -d для просмотра деталей контекста\n\n"
        
        "🧠 <b>Улучшенные возможности:</b>\n"
        "• Бот теперь анализирует 40 сообщений из текущего чата для контекста\n"
        "• При необходимости запрашивает историю других чатов или данные из БД\n"
        "• Автоматически определяет, какая информация нужна для ответа\n"
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
    """Handle /ask command to query the database with natural language"""
    command_parts = message.text.split(maxsplit=1)
    
    # Проверка наличия флага технических деталей
    show_details = False
    question = ""
    
    if len(command_parts) < 2:
        await message.reply("Пожалуйста, укажите вопрос после команды /ask.")
        return
    
    # Проверяем наличие флага --details или -d
    if "--details" in command_parts[1] or "-d" in command_parts[1]:
        show_details = True
        # Удаляем флаг из вопроса
        question = command_parts[1].replace("--details", "").replace("-d", "").strip()
        if not question:
            await message.reply("Пожалуйста, укажите вопрос после команды и флага.")
            return
    else:
        question = command_parts[1]
    
    processing_msg = await message.reply("Анализирую ваш вопрос...")
    
    try:
        # Получаем список доступных чатов
        available_chats = await get_user_chats()
        
        # Обрабатываем вопрос с учетом контекста
        result = await process_question_with_context(
            question=question, 
            chat_id=message.chat.id, 
            available_chats=available_chats
        )
        
        # Если нужно показать детали и контекста
        if show_details:
            detailed_info = []
            
            # Информация о типе контекста
            context_type = result.get("context_type", "unknown")
            if context_type == "database_query":
                detailed_info.append("🔍 <b>Запрос к базе данных</b>")
            elif context_type == "chat_history":
                detailed_info.append("📜 <b>Использование истории чатов</b>")
            elif context_type == "use_available_context":
                detailed_info.append("📝 <b>Использование доступного контекста</b>")
            
            # Дополнительная информация об использованных данных
            if result.get("additional_data_used"):
                detailed_info.append("📊 Использованы данные из базы данных")
            
            if result.get("additional_chat_history_used"):
                detailed_info.append("💬 Использована дополнительная история чатов")
                
            # Собираем детальный ответ
            detailed_response = [
                f"<b>Ваш вопрос:</b> {question}\n",
                "\n".join(detailed_info),
                "\n\n<b>Ответ:</b>",
                result.get("answer", "Не удалось сформировать ответ на ваш вопрос. Пожалуйста, уточните запрос.")
            ]
            
            await processing_msg.edit_text("\n".join(detailed_response), parse_mode="HTML")
        else:
            # Простой ответ без деталей
            if "answer" in result:
                await processing_msg.edit_text(result["answer"])
            else:
                logger.warning("Missing 'answer' key in context processor result")
                await processing_msg.edit_text("Не удалось сформировать ответ на ваш вопрос. Пожалуйста, уточните запрос.")
            
            # Логируем детали использованного контекста
            logger.debug(f"Тип использованного контекста: {result.get('context_type')}")
            logger.debug(f"Использованы данные из БД: {result.get('additional_data_used', False)}")
            logger.debug(f"Использована история чатов: {result.get('additional_chat_history_used', False)}")
            
    except Exception as e:
        logger.error(f"Error processing contextual question: {str(e)}")
        await processing_msg.edit_text(f"Произошла ошибка: {str(e)}")
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