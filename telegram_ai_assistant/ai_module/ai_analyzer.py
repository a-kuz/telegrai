import sys
import os
import json
import asyncio
import base64
import io
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
import httpx
from openai import AsyncOpenAI
from PIL import Image
import re
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_MODEL
from utils.logging_utils import setup_ai_logger
logger = setup_ai_logger()
logger.info(f"AI Module initializing with model: {OPENAI_MODEL}")
logger.debug(f"OpenAI API Key: {OPENAI_API_KEY[:5]}...")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
async def analyze_message(message_data: Dict[str, Any]) -> Dict[str, Any]:
    text = message_data.get("text", "")
    attachments = message_data.get("attachments", [])
    chat_name = message_data.get("chat_name", "")
    sender_name = message_data.get("sender_name", "")
    logger.info(f"Analyzing message from {sender_name} in {chat_name}")
    logger.debug(f"Message text: {text[:50]}..." if text else "No text")
    logger.debug(f"Attachments: {attachments}")
    if not text and not attachments:
        logger.debug("Empty message, skipping detailed analysis")
        return {
            "category": "other",
            "is_important": False,
            "is_question": False,
            "has_task": False,
            "context_summary": "Empty message"
        }
    content = []
    if text:
        content.append({
            "type": "text", 
            "text": f"Message from {sender_name} in chat '{chat_name}': {text}"
        })
    for attachment in attachments:
        if attachment.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            try:
                with open(attachment, "rb") as img_file:
                    base64_image = base64.b64encode(img_file.read()).decode('utf-8')
                logger.debug(f"Processing image attachment: {attachment}")
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                })
            except Exception as e:
                logger.error(f"Error processing image attachment {attachment}: {str(e)}")
                content.append({
                    "type": "text",
                    "text": f"[There was an image attachment but it couldn't be processed: {str(e)}]"
                })
        else:
            logger.debug(f"Processing file attachment: {attachment}")
            content.append({
                "type": "text",
                "text": f"[There was a file attachment: {os.path.basename(attachment)}]"
            })
    system_prompt = """
    You are an AI assistant analyzing messages from Telegram work chats.
    Your task is to analyze the content and determine:
    1. The category of the message (question, task, status update, general discussion, etc.)
    2. Whether the message contains a question directed at someone
    3. Whether the message describes a task or work item that should be tracked
    4. Whether the message is important and requires prompt attention
    5. If it contains a task, extract structured information about the task
    Respond with a JSON object containing the analysis results.
    """
    try:
        logger.info(f"Calling OpenAI API to analyze message with ID {message_data.get('message_id')}")
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            response_format={"type": "json_object"}
        )
        analysis_text = response.choices[0].message.content
        analysis = json.loads(analysis_text)
        analysis["original_message"] = {
            "text": text,
            "chat_id": message_data.get("chat_id"),
            "message_id": message_data.get("message_id"),
            "sender_id": message_data.get("sender_id")
        }
        logger.info(f"Analysis complete for message ID {message_data.get('message_id')}: Category: {analysis.get('category', 'unknown')}")
        logger.debug(f"Full analysis result: {json.dumps(analysis)[:200]}...")
        return analysis
    except Exception as e:
        logger.error(f"Error analyzing message {message_data.get('message_id')}: {str(e)}", exc_info=True)
        return {
            "category": "error",
            "is_important": False,
            "is_question": False,
            "has_task": False,
            "error": str(e),
            "context_summary": "Error during analysis"
        }
async def extract_task_from_message(message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = message_data.get("text", "")
    chat_name = message_data.get("chat_name", "")
    system_prompt = """
    Extract task information from the provided message. 
    Include the following in your JSON response:
    - title: A concise title for the task (required)
    - description: Detailed description of what needs to be done (required)
    - assignee: Who should complete the task, if mentioned (optional)
    - due_date: When the task should be completed, if mentioned (optional, in YYYY-MM-DD format)
    - priority: Task priority if indicated (optional, one of: low, medium, high)
    If no task is detected, return {"is_task": false}
    """
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Message from chat '{chat_name}': {text}"}
            ],
            response_format={"type": "json_object"}
        )
        task_data = json.loads(response.choices[0].message.content)
        if task_data.get("is_task") is False:
            return None
        if "title" not in task_data or not task_data["title"]:
            return None
        return task_data
    except Exception as e:
        return None
async def detect_question_target(message_data: Dict[str, Any], admin_user_id: int) -> Optional[Dict[str, Any]]:
    text = message_data.get("text", "")
    sender_id = message_data.get("sender_id")
    chat_type = message_data.get("chat_type", "")
    
    # Skip processing if sender is admin or bot
    if sender_id == admin_user_id or message_data.get("is_bot", False):
        return None
    
    # Check if message is from a channel or channel comments (they have channel_type)
    if chat_type == "channel":
        return None
    
    # Check if message is a reply to admin or contains a mention of admin
    is_reply_to_admin = False
    has_admin_mention = False
    
    # Check for reply to admin
    original_event = message_data.get("original_event", {})
    if hasattr(original_event, "reply_to_msg_id") and original_event.reply_to_msg_id:
        try:
            # Get the message this is replying to
            reply_to_msg_id = original_event.reply_to_msg_id
            replied_msg = message_data.get("replied_message", {})
            if replied_msg and replied_msg.get("sender_id") == admin_user_id:
                is_reply_to_admin = True
        except Exception as e:
            logger.error(f"Error checking reply message: {str(e)}")
    
    # Check for admin mention (using a simplified approach - this could be enhanced with entity parsing)
    if "@admin" in text.lower() or f"@{admin_user_id}" in text:
        has_admin_mention = True
    
    # Only proceed if the message is directly engaging with the admin
    if not (is_reply_to_admin or has_admin_mention):
        return None
    
    system_prompt = """
    Analyze if this message contains a question directed at a specific person, especially the team lead or admin.
    Return a JSON with:
    - is_question: boolean indicating if this is a question
    - target_user_id: ID of the user being asked, if known (or null)
    - question_text: The specific question being asked
    - requires_answer: boolean indicating if this question needs a response
    """
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Message: {text}\nAdmin ID: {admin_user_id}"}
            ],
            response_format={"type": "json_object"}
        )
        question_data = json.loads(response.choices[0].message.content)
        if question_data.get("is_question") and question_data.get("requires_answer"):
            if question_data.get("target_user_id") == admin_user_id or question_data.get("target_user_id") is None:
                return {
                    "is_question": True,
                    "target_user_id": admin_user_id,
                    "question_text": question_data.get("question_text", text),
                    "message_id": message_data.get("message_id"),
                    "chat_id": message_data.get("chat_id"),
                    "sender_id": message_data.get("sender_id"),
                    "sender_name": message_data.get("sender_name", "Unknown")
                }
        return None
    except Exception as e:
        logger.error(f"Error in detect_question_target: {str(e)}")
        return None
async def generate_chat_summary(messages: List[Dict[str, Any]], chat_name: str) -> str:
    formatted_messages = []
    for msg in messages:
        sender = msg.get("sender_name", "Unknown")
        text = msg.get("text", "")
        timestamp = msg.get("timestamp", "")
        if isinstance(timestamp, str):
            timestamp_str = timestamp
        else:
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else ""
        formatted_messages.append(f"[{timestamp_str}] {sender}: {text}")
    messages_text = "\n".join(formatted_messages)
    system_prompt = """
    Create a concise summary of the conversation from the chat logs provided.
    Focus on:
    1. Key decisions made
    2. Action items discussed
    3. Important questions or issues raised
    4. Overall topic and progress of discussion
    Keep the summary structured, brief but comprehensive.
    """
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Chat name: {chat_name}\n\nMessages:\n{messages_text}"}
            ]
        )
        summary = response.choices[0].message.content
        return summary
    except Exception as e:
        return f"Error generating summary: {str(e)}"
async def analyze_productivity(productivity_data: List[Dict[str, Any]]) -> str:
    if not productivity_data:
        return "No productivity data available."
    formatted_data = []
    for item in productivity_data:
        name = item.get("name", "Unknown")
        messages = item.get("total_messages", 0)
        tasks_created = item.get("tasks_created", 0)
        tasks_completed = item.get("tasks_completed", 0)
        formatted_data.append(f"{name}: {messages} messages, {tasks_created} tasks created, {tasks_completed} tasks completed")
    data_text = "\n".join(formatted_data)
    system_prompt = """
    Analyze the team's productivity data and provide insights:
    1. Identify the most active team members
    2. Highlight potential issues (e.g., low participation, imbalance in workload)
    3. Suggest areas for improvement
    4. Recognize positive contributions
    Keep your analysis concise, objective, and action-oriented.
    """
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Team productivity data for the past week:\n{data_text}"}
            ]
        )
        analysis = response.choices[0].message.content
        return analysis
    except Exception as e:
        return f"Error analyzing productivity: {str(e)}"
async def extract_url_content(url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=10.0)
            if response.status_code != 200:
                return f"Failed to fetch URL: {response.status_code}"
            return f"Successfully fetched URL. Content length: {len(response.text)} characters"
    except Exception as e:
        return f"Error extracting URL content: {str(e)}"
async def suggest_response(question_text: str) -> str:
    system_prompt = """
    You are an AI assistant helping a team lead respond to questions from team members.
    Generate a concise, helpful response to the question.
    Keep your answer professional, actionable, and brief.
    """
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Question: {question_text}"}
            ]
        )
        suggested_response = response.choices[0].message.content
        return suggested_response
    except Exception as e:
        return f"Error generating response: {str(e)}"
async def determine_and_execute_query(user_question: str) -> Dict[str, Any]:
    """
    Использует OpenAI function calling для определения, требуется ли SQL запрос к базе данных
    и генерирует его при необходимости.
    
    Args:
        user_question: Вопрос пользователя
        
    Returns:
        Dictionary с информацией о типе ответа, SQL запросе и результатами
    """
    # Описание доступных таблиц
    db_schema = """
    Доступные таблицы в базе данных:
    
    1. users (Пользователи):
       - id: Integer, первичный ключ
       - user_id: Integer, ID пользователя Telegram
       - username: String, имя пользователя (может быть NULL)
       - first_name: String, имя пользователя
       - last_name: String, фамилия пользователя
       - is_bot: Boolean, флаг бота
       - created_at: DateTime, время создания записи
    
    2. messages (Сообщения):
       - id: Integer, первичный ключ
       - message_id: Integer, ID сообщения Telegram
       - chat_id: Integer, внешний ключ на chats.chat_id
       - sender_id: Integer, внешний ключ на users.user_id
       - text: Text, текст сообщения
       - attachments: JSON, прикрепленные файлы
       - timestamp: DateTime, время сообщения
       - is_important: Boolean, важное ли сообщение
       - is_processed: Boolean, обработано ли сообщение
       - category: String, категория сообщения
       - is_bot: Boolean, отправлено ли ботом
    
    3. chats (Чаты):
       - id: Integer, первичный ключ
       - chat_id: Integer, ID чата Telegram
       - chat_name: String, название чата
       - is_active: Boolean, активен ли чат
       - last_summary_time: DateTime, время последнего суммирования
       - linear_team_id: String, ID команды в Linear
       
    4. tasks (Задачи):
       - id: Integer, первичный ключ
       - linear_id: String, ID задачи в Linear
       - title: String, заголовок задачи
       - description: Text, описание задачи
       - status: String, статус задачи
       - created_at: DateTime, время создания
       - due_date: DateTime, срок исполнения
       - assignee_id: Integer, внешний ключ на users.user_id
       - message_id: Integer, ID сообщения, из которого создана задача
       - chat_id: Integer, ID чата, из которого создана задача
       
    5. unanswered_questions (Неотвеченные вопросы):
       - id: Integer, первичный ключ
       - message_id: Integer, ID сообщения с вопросом
       - chat_id: Integer, ID чата с вопросом
       - target_user_id: Integer, внешний ключ на users.user_id (кому адресован вопрос)
       - sender_id: Integer, ID пользователя, задавшего вопрос
       - question: Text, текст вопроса
       - asked_at: DateTime, время вопроса
       - is_answered: Boolean, отвечен ли вопрос
       - answered_at: DateTime, время ответа
       - reminder_count: Integer, сколько напоминаний отправлено
       - is_bot: Boolean, задан ли вопрос ботом
       
    6. team_productivity (Продуктивность команды):
       - id: Integer, первичный ключ
       - user_id: Integer, внешний ключ на users.user_id
       - date: DateTime, дата записи
       - message_count: Integer, количество сообщений
       - tasks_created: Integer, количество созданных задач
       - tasks_completed: Integer, количество завершенных задач
       - avg_response_time: Integer, среднее время ответа
    """
    
    # Определение функций для OpenAI
    functions = [
        {
            "type": "function",
            "function": {
                "name": "generate_sql_query",
                "description": "Генерирует SQL-запрос к базе данных для получения запрошенной информации",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql_query": {
                            "type": "string",
                            "description": "SQL запрос для извлечения данных из базы данных"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Объяснение, какие данные запрашиваются и для чего"
                        }
                    },
                    "required": ["sql_query", "explanation"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "answer_without_database",
                "description": "Отвечает на вопрос без запроса к базе данных, когда информация может быть предоставлена напрямую",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {
                            "type": "string",
                            "description": "Ответ на вопрос пользователя"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Причина, почему запрос к базе данных не требуется"
                        }
                    },
                    "required": ["answer", "reason"]
                }
            }
        }
    ]
    
    try:
        # Отправляем запрос в OpenAI
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": f"""Ты ИИ-помощник для команды разработчиков, работающий через Telegram.
                
                Твоя задача - определить, требуется ли SQL-запрос к базе данных для ответа на вопрос пользователя о разработке или управлении проектами.
                
                {db_schema}
                
                Если вопрос пользователя требует получения информации из базы данных (например, статистика разработки, активность команды, задачи и сроки), 
                используй функцию generate_sql_query и создай SQL-запрос.
                
                Фокусируйся на данных, связанных с разработкой и управлением проектами:
                - Статистика задач и их статусы
                - Активность разработчиков
                - Тренды производительности команды
                - Сроки выполнения задач
                - Анализ коммуникаций команды
                
                Если вопрос не требует обращения к базе данных или содержит просьбу о чем-то, что не связано с данными (например, 'привет', 'как дела', 
                'что ты умеешь', просьба о помощи, общие вопросы), используй функцию answer_without_database.
                
                Важно: не используй устаревшие шаблоны запросов и не угадывай структуру базы. Основывайся только на предоставленной схеме."""},
                {"role": "user", "content": user_question}
            ],
            tools=functions,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        
        # Проверяем, была ли вызвана функция
        if message.tool_calls:
            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            if function_name == "generate_sql_query":
                # Нужен запрос к базе данных
                sql_query = function_args.get("sql_query")
                explanation = function_args.get("explanation")
                
                # Выполняем SQL запрос
                from sqlalchemy import text
                from utils.db_utils import engine
                
                result = None
                error = None
                
                try:
                    with engine.connect() as connection:
                        result_proxy = connection.execute(text(sql_query))
                        columns = result_proxy.keys()
                        result_data = result_proxy.fetchall()
                        
                        # Преобразуем в список словарей
                        result = [dict(zip(columns, row)) for row in result_data]
                        
                    # Генерируем человеческое объяснение результатов
                    result_explanation_response = await client.chat.completions.create(
                        model=OPENAI_MODEL,
                        messages=[
                            {"role": "system", "content": """Ты ИИ-аналитик для команды разработчиков, специализирующийся на управлении проектами.
                            Твоя задача - объяснить результаты запроса к базе данных понятным языком, делая акцент на аспектах разработки ПО.
                            
                            Объясняя результаты команде разработчиков, делай акцент на:
                            1. Прогресс по задачам и соблюдение сроков
                            2. Продуктивность команды и отдельных разработчиков
                            3. Тренды в коммуникации и сотрудничестве
                            4. Приоритеты в работе и распределение нагрузки
                            
                            Важно:
                            1. Отвечай только на заданный вопрос, без лишних деталей о SQL запросе
                            2. Не объясняй, как работает запрос или как он был написан
                            3. Просто дай краткий ответ по сути вопроса на основе данных из БД
                            4. Если данных нет или результат пустой, так и скажи кратко
                            5. Избегай технических терминов и джаргона SQL
                            6. Не упоминай таблицы, соединения и SQL синтаксис в ответе
                            7. Пиши так, как будто просто отвечаешь на вопрос пользователя
                            8. Если в результатах есть конкретные имена, цифры или даты, включи их в ответ
                            
                            Плохой пример:
                            "Запрос, представленный в вопросе, предназначен для поиска пользователей, которые не имеют назначенных задач..."
                            
                            Хороший пример:
                            "В настоящее время три разработчика не имеют назначенных задач: Александр, Юлия и Максим. Это может быть хорошей возможностью перераспределить рабочую нагрузку в команде."
                            """},
                            {"role": "user", "content": f"Вопрос пользователя: '{user_question}'\nРезультаты: {result}"}
                        ]
                    )
                    
                    result_explanation = result_explanation_response.choices[0].message.content
                    
                    return {
                        "type": "database_query",
                        "question": user_question,
                        "sql_query": sql_query,
                        "explanation": explanation,
                        "result": result,
                        "user_friendly_answer": result_explanation,
                        "error": None
                    }
                except Exception as e:
                    error = str(e)
                    # Пытаемся объяснить ошибку
                    error_explanation_response = await client.chat.completions.create(
                        model=OPENAI_MODEL,
                        messages=[
                            {"role": "system", "content": """Ты ИИ-помощник для команды разработчиков, объясняющий проблемы с получением данных.
                            Объясни простым языком, почему не удалось получить запрошенную информацию о разработке или проекте.
                            
                            Важно:
                            1. Говори как менеджер проектов, обращаясь к команде разработчиков
                            2. Предложи альтернативные способы получить нужную информацию о проекте
                            3. Не вдавайся в технические детали SQL ошибок
                            4. Сфокусируйся на практической ценности для команды
                            
                            Плохой пример:
                            "Ошибка, с которой вы столкнулись, связана с использованием оператора `ILIKE` в вашем SQL-запросе..."
                            
                            Хороший пример:
                            "Не удалось получить информацию о статусе задач в текущем спринте. Попробуйте уточнить названия проектов или временной период, который вас интересует."
                            """},
                            {"role": "user", "content": f"Вопрос пользователя: '{user_question}'\nОшибка: {error}"}
                        ]
                    )
                    
                    error_explanation = error_explanation_response.choices[0].message.content
                    error_explanation += "\n\nДля просмотра технических деталей используйте команду /ask с флагом --details."
                    
                    return {
                        "type": "database_query_error",
                        "question": user_question,
                        "sql_query": sql_query,
                        "explanation": explanation,
                        "error": error,
                        "error_explanation": error_explanation,
                        "result": None,
                        "user_friendly_answer": error_explanation
                    }
            else:
                # Не требуется запрос к базе данных
                answer = function_args.get("answer")
                reason = function_args.get("reason")
                
                return {
                    "type": "direct_answer",
                    "question": user_question,
                    "answer": answer,
                    "reason": reason
                }
        else:
            # Если функция не была вызвана, возвращаем обычный ответ
            return {
                "type": "general_answer",
                "question": user_question,
                "answer": message.content
            }
    except Exception as e:
        return {
            "type": "error",
            "question": user_question,
            "error": str(e),
            "answer": f"Произошла ошибка при обработке вопроса: {str(e)}"
        }
async def generate_sql_from_question(question: str) -> Dict[str, Any]:
    """
    Generate SQL query from natural language question and execute it to get results
    
    Args:
        question: Natural language question about data
        
    Returns:
        Dictionary with generated SQL, results and explanation
    """
    # Используем новый метод с function calling
    return await determine_and_execute_query(question)

async def iterative_reasoning(question: str, max_attempts: int = 3) -> Dict[str, Any]:
    """
    Performs iterative reasoning on a complex question or problem.
    Shows reasoning steps as editable bubbles in Telegram.
    If an error or inconsistency is detected, it will retry with a different approach.
    
    Args:
        question: The question or problem to solve
        max_attempts: Maximum number of reasoning attempts
        
    Returns:
        Dictionary with reasoning process, result, and attempt history
    """
    logger.info(f"Starting iterative reasoning process for: {question[:50]}...")
    
    attempts = []
    final_result = None
    is_success = False
    
    system_prompt = """
    You are an AI reasoning assistant solving a complex problem step by step.
    Think through this problem carefully in a structured way:
    
    1. First, break down the problem into clear sub-problems
    2. For each step, explain your thinking process, any assumptions made, and your conclusion
    3. If you realize a mistake in earlier reasoning, acknowledge it and correct your path
    4. End with a clear final answer if possible
    
    Your reasoning will be shown visually to the user, so organize your thoughts clearly.
    """
    
    # Create initial message for Telegram that will be updated with reasoning steps
    try:
        from telegram_ai_assistant.bot.telegram_bot import bot, ADMIN_USER_ID
        intro_message = f"🧠 *Thinking about:* {question}\n\n_Starting reasoning process..._"
        message_obj = await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=intro_message,
            parse_mode="Markdown"
        )
        message_id = message_obj.message_id
        logger.debug(f"Created initial reasoning message with ID: {message_id}")
    except Exception as e:
        logger.error(f"Error creating initial message: {str(e)}")
        message_id = None
    
    for attempt in range(1, max_attempts + 1):
        logger.info(f"Reasoning attempt {attempt}/{max_attempts}")
        
        try:
            # If not the first attempt, modify the system prompt to learn from previous errors
            if attempt > 1:
                previous_attempts_text = "\n\n".join([f"Attempt {i+1}: {a['reasoning']}" for i, a in enumerate(attempts)])
                system_prompt += f"\n\nPrevious attempts had issues:\n{previous_attempts_text}\n\nTry a different approach and avoid these mistakes."
            
            # Call the model with thinking steps format
            response = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Question: {question}\n\nShow your full reasoning process step by step, noting any uncertainties or assumptions."}
                ]
            )
            
            reasoning = response.choices[0].message.content
            
            # Record this attempt
            current_attempt = {
                "attempt_number": attempt,
                "reasoning": reasoning,
                "timestamp": datetime.utcnow().isoformat()
            }
            attempts.append(current_attempt)
            
            # Update the message in Telegram with the latest reasoning
            if message_id:
                try:
                    # Format with step numbers and thinking emojis
                    formatted_reasoning = reasoning.replace("Step ", "🔹 Step ")
                    formatted_reasoning = re.sub(r"(\d+\.\s)", r"🔸 \1", formatted_reasoning)
                    
                    # Add attempt number for anything beyond the first attempt
                    attempt_header = f"*Reasoning Attempt {attempt}/{max_attempts}*\n\n" if attempt > 1 else "*Reasoning Process:*\n\n"
                    
                    # Create message with all attempts
                    full_message = f"🧠 *Thinking about:* {question}\n\n{attempt_header}{formatted_reasoning}"
                    
                    # Keep message under Telegram's limit
                    if len(full_message) > 4000:
                        full_message = full_message[:3950] + "...\n_(reasoning truncated due to length)_"
                    
                    await bot.edit_message_text(
                        chat_id=ADMIN_USER_ID,
                        message_id=message_id,
                        text=full_message,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error updating reasoning message: {str(e)}")
            
            # Verify reasoning for errors or contradictions
            verification_prompt = """
            Analyze the reasoning provided and determine if it contains:
            1. Logical errors or contradictions
            2. Mathematical mistakes
            3. False assumptions
            4. Incomplete logic
            
            Respond with a JSON:
            {
                "is_valid": true/false,
                "errors": ["error1", "error2"],
                "needs_another_attempt": true/false,
                "final_answer": "The clear final answer extracted from the reasoning (only if valid)"
            }
            """
            
            verification_response = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": verification_prompt},
                    {"role": "user", "content": reasoning}
                ],
                response_format={"type": "json_object"}
            )
            
            verification = json.loads(verification_response.choices[0].message.content)
            
            # Add verification to attempt record
            current_attempt["verification"] = verification
            
            # If reasoning is valid, we can stop
            if verification.get("is_valid", False) and not verification.get("needs_another_attempt", True):
                final_result = verification.get("final_answer")
                is_success = True
                
                # Update final message with success
                if message_id:
                    final_message = f"🧠 *Thinking about:* {question}\n\n"
                    final_message += f"*Reasoning Process:*\n\n{formatted_reasoning}\n\n"
                    final_message += f"✅ *Final Answer:* {final_result}"
                    
                    if len(final_message) > 4000:
                        final_message = final_message[:3950] + "...\n_(message truncated due to length)_"
                    
                    await bot.edit_message_text(
                        chat_id=ADMIN_USER_ID,
                        message_id=message_id,
                        text=final_message,
                        parse_mode="Markdown"
                    )
                
                logger.info(f"Successful reasoning after {attempt} attempts")
                break
            
            # If this was the last attempt and still not valid, use best effort
            if attempt == max_attempts:
                # Extract final answer even if reasoning isn't perfect
                extraction_response = await client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": "Extract the most likely answer from this reasoning, even if it contains some errors. Provide the best possible answer based on the parts of reasoning that are correct."},
                        {"role": "user", "content": reasoning}
                    ]
                )
                
                final_result = extraction_response.choices[0].message.content
                
                # Update final message with partial success notice
                if message_id:
                    final_message = f"🧠 *Thinking about:* {question}\n\n"
                    final_message += f"*Reasoning Process (Attempt {attempt}/{max_attempts}):*\n\n{formatted_reasoning}\n\n"
                    final_message += f"⚠️ *Best Effort Answer:* {final_result}\n\n"
                    final_message += "_(Note: Maximum attempts reached, providing best available answer)_"
                    
                    if len(final_message) > 4000:
                        final_message = final_message[:3950] + "...\n_(message truncated due to length)_"
                    
                    await bot.edit_message_text(
                        chat_id=ADMIN_USER_ID,
                        message_id=message_id,
                        text=final_message,
                        parse_mode="Markdown"
                    )
                
                logger.info(f"Reached max attempts ({max_attempts}), providing best effort answer")
            else:
                # Update message to show we're trying again
                if message_id:
                    error_points = "\n".join([f"• {error}" for error in verification.get("errors", ["Uncertain reasoning"])])
                    retry_message = f"🧠 *Thinking about:* {question}\n\n"
                    retry_message += f"*Reasoning Attempt {attempt}/{max_attempts}:*\n\n{formatted_reasoning}\n\n"
                    retry_message += f"⚠️ *Issues detected:*\n{error_points}\n\n"
                    retry_message += f"_Trying again with attempt {attempt+1}/{max_attempts}..._"
                    
                    if len(retry_message) > 4000:
                        retry_message = retry_message[:3950] + "...\n_(message truncated due to length)_"
                    
                    await bot.edit_message_text(
                        chat_id=ADMIN_USER_ID,
                        message_id=message_id,
                        text=retry_message,
                        parse_mode="Markdown"
                    )
                
                logger.info(f"Issues found in attempt {attempt}, will try again")
                
        except Exception as e:
            logger.error(f"Error in reasoning attempt {attempt}: {str(e)}")
            error_message = str(e)
            
            # Record this failed attempt
            current_attempt = {
                "attempt_number": attempt,
                "reasoning": "Error occurred during reasoning",
                "error": error_message,
                "timestamp": datetime.utcnow().isoformat()
            }
            attempts.append(current_attempt)
            
            # Update message to show the error
            if message_id:
                try:
                    error_update = f"🧠 *Thinking about:* {question}\n\n"
                    
                    # Include previous attempts if they exist
                    if attempt > 1 and len(attempts) > 1:
                        prev_formatted = attempts[-2].get("reasoning", "").replace("Step ", "🔹 Step ")
                        prev_formatted = re.sub(r"(\d+\.\s)", r"🔸 \1", prev_formatted)
                        error_update += f"*Previous Reasoning (Attempt {attempt-1}/{max_attempts}):*\n\n{prev_formatted}\n\n"
                    
                    error_update += f"❌ *Error in attempt {attempt}/{max_attempts}:*\n{error_message}\n\n"
                    
                    if attempt < max_attempts:
                        error_update += f"_Trying again with attempt {attempt+1}/{max_attempts}..._"
                    else:
                        error_update += "_Maximum attempts reached. Unable to provide reasoning._"
                    
                    await bot.edit_message_text(
                        chat_id=ADMIN_USER_ID,
                        message_id=message_id,
                        text=error_update,
                        parse_mode="Markdown"
                    )
                except Exception as msg_e:
                    logger.error(f"Error updating error message: {str(msg_e)}")
    
    # Create the final result dictionary
    result = {
        "question": question,
        "attempts": attempts,
        "final_result": final_result,
        "is_success": is_success,
        "num_attempts": len(attempts),
        "message_id": message_id
    }
    
    return result

async def answer_with_reasoning(question: str) -> Dict[str, Any]:
    """
    Wrapper function to use iterative reasoning to answer a question
    
    Args:
        question: The question to answer
        
    Returns:
        Dictionary with the answer and reasoning process
    """
    logger.info(f"Starting reasoning process for question: {question}")
    
    try:
        result = await iterative_reasoning(question, max_attempts=3)
        return {
            "question": question,
            "answer": result.get("final_result"),
            "reasoning_process": [a.get("reasoning") for a in result.get("attempts", [])],
            "success": result.get("is_success", False)
        }
    except Exception as e:
        logger.error(f"Error in answer_with_reasoning: {str(e)}")
        return {
            "question": question,
            "answer": f"Error: {str(e)}",
            "reasoning_process": [],
            "success": False
        }

async def iterative_discussion_summary(chat_id: int = None, time_period: str = "24h", max_attempts: int = 3) -> Dict[str, Any]:
    """
    Generate discussion summary with multiple steps and error correction.
    Shows the thought process in editable bubbles for each step.
    
    Args:
        chat_id: Optional specific chat ID to summarize (None for all monitored chats)
        time_period: Time period to summarize (24h, 7d, 30d)
        max_attempts: Maximum number of attempts per step
        
    Returns:
        Dictionary with summary results and process details
    """
    logger.info(f"Starting iterative discussion summary process for chat_id={chat_id}, period={time_period}")
    
    # Convert time period to hours
    hours = 24
    if time_period == "7d":
        hours = 24 * 7
    elif time_period == "30d":
        hours = 24 * 30
    
    # Create initial message for Telegram
    try:
        from telegram_ai_assistant.bot.telegram_bot import bot, ADMIN_USER_ID
        chat_info = f"chat {chat_id}" if chat_id else "all monitored chats"
        intro_message = f"🔍 *Generating summary for {chat_info}*\n\n_Time period: {time_period}_\n\n_Initializing analysis..._"
        message_obj = await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=intro_message,
            parse_mode="Markdown"
        )
        main_message_id = message_obj.message_id
        logger.debug(f"Created initial summary message with ID: {main_message_id}")
    except Exception as e:
        logger.error(f"Error creating initial message: {str(e)}")
        return {"error": str(e), "completed": False}
    
    # Step 1: Data collection
    data_message = await bot.send_message(
        chat_id=ADMIN_USER_ID,
        text="📊 *Step 1/4: Collecting message data*\n\n_Retrieving messages..._",
        parse_mode="Markdown"
    )
    data_message_id = data_message.message_id
    
    # Track analysis state
    state = {
        "completed_steps": 0,
        "total_steps": 4,
        "current_step": "data_collection",
        "messages": [],
        "participants": [],
        "topics": [],
        "summary": "",
        "status": "in_progress",
        "errors": []
    }
    
    # Step 1: Data Collection
    try:
        # Update message to show we're collecting data
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=data_message_id,
            text="📊 *Step 1/4: Collecting message data*\n\n_Retrieving messages from database..._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏱️ Working...", callback_data="working")]
            ])
        )
        
        # Get messages from database
        from telegram_ai_assistant.utils.db_utils import get_recent_chat_messages
        
        chat_messages = await get_recent_chat_messages(chat_id, hours=hours, limit=100)
        if not chat_messages:
            # No messages found
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=data_message_id,
                text="📊 *Step 1/4: Collecting message data*\n\n❌ *Error:* No messages found for this time period.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Try different period", callback_data="try_different_period")]
                ])
            )
            
            # Update main message
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=main_message_id,
                text=f"🔍 *Summary for {chat_info}*\n\n❌ *Failed:* No messages found for time period: {time_period}",
                parse_mode="Markdown"
            )
            
            state["status"] = "failed"
            state["errors"].append("No messages found for the specified time period")
            return state
        
        # Success - update message with data stats
        state["messages"] = chat_messages
        state["participants"] = list(set([msg.get("sender_name", "Unknown") for msg in chat_messages]))
        message_count = len(chat_messages)
        participant_count = len(state["participants"])
        
        # Calculate time range
        timestamps = [msg.get("timestamp") for msg in chat_messages if msg.get("timestamp")]
        if timestamps:
            earliest = min(timestamps)
            latest = max(timestamps)
            if isinstance(earliest, str):
                earliest = datetime.fromisoformat(earliest)
            if isinstance(latest, str):
                latest = datetime.fromisoformat(latest)
            time_range = f"{earliest.strftime('%Y-%m-%d %H:%M')} to {latest.strftime('%Y-%m-%d %H:%M')}"
        else:
            time_range = "Unknown time range"
        
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=data_message_id,
            text=f"📊 *Step 1/4: Data Collection Complete*\n\n✅ Retrieved {message_count} messages from {participant_count} participants\n📅 Time range: {time_range}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Continue to Topic Analysis", callback_data="continue_topic_analysis")]
            ])
        )
        
        state["completed_steps"] = 1
        state["current_step"] = "topic_analysis"
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in data collection step: {error_msg}")
        
        # Update message with error
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=data_message_id,
            text=f"📊 *Step 1/4: Collecting message data*\n\n❌ *Error:* {error_msg}\n\nPlease check database connection or try a different time period.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Retry", callback_data="retry_data_collection")]
            ])
        )
        
        state["status"] = "error"
        state["errors"].append(f"Data collection error: {error_msg}")
        return state
    
    # Step 2: Topic Analysis
    topic_message = await bot.send_message(
        chat_id=ADMIN_USER_ID,
        text="🔍 *Step 2/4: Topic Analysis*\n\n_Identifying main discussion topics..._",
        parse_mode="Markdown"
    )
    topic_message_id = topic_message.message_id
    
    try:
        # Format messages for analysis
        formatted_messages = []
        for i, msg in enumerate(chat_messages[:50]):  # Limit to first 50 messages to avoid token limits
            sender = msg.get("sender_name", "Unknown")
            text = msg.get("text", "")
            timestamp = msg.get("timestamp", "")
            if isinstance(timestamp, datetime):
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M")
            else:
                timestamp_str = str(timestamp)
            
            formatted_messages.append(f"[{timestamp_str}] {sender}: {text}")
        
        messages_text = "\n".join(formatted_messages)
        
        # Update message to show we're analyzing
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=topic_message_id,
            text="🔍 *Step 2/4: Topic Analysis*\n\n_Analyzing message content to identify main topics..._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏱️ Analyzing...", callback_data="analyzing")]
            ])
        )
        
        # Get topics using AI
        system_prompt = """
        Analyze the conversation and identify the main discussion topics.
        Return the results as a well-formatted JSON:
        {
            "main_topics": ["Topic 1", "Topic 2", ...],
            "topic_summary": "A brief description of the topics discussed",
            "key_participants": {
                "Person1": "Their main contributions",
                "Person2": "Their main contributions"
            }
        }
        """
        
        topic_analysis = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Chat messages:\n{messages_text}"}
            ],
            response_format={"type": "json_object"}
        )
        
        try:
            analysis_data = json.loads(topic_analysis.choices[0].message.content)
            state["topics"] = analysis_data.get("main_topics", [])
            
            # Format for display
            topics_text = "\n".join([f"• {topic}" for topic in state["topics"]])
            participants_text = ""
            
            for person, contribution in analysis_data.get("key_participants", {}).items():
                participants_text += f"• *{person}:* {contribution}\n"
            
            # Update message with topics
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=topic_message_id,
                text=f"🔍 *Step 2/4: Topic Analysis Complete*\n\n*Main Topics:*\n{topics_text}\n\n*Key Participants:*\n{participants_text}\n\n*Summary:*\n{analysis_data.get('topic_summary', 'No summary available')}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Accept Topics", callback_data="accept_topics"),
                     InlineKeyboardButton(text="🔄 Refine Topics", callback_data="refine_topics")]
                ])
            )
            
            state["completed_steps"] = 2
            state["current_step"] = "detailed_analysis"
            
        except json.JSONDecodeError:
            # Invalid JSON response
            logger.error("Invalid JSON response from topic analysis")
            
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=topic_message_id,
                text="🔍 *Step 2/4: Topic Analysis*\n\n❌ *Error:* Invalid response format. Please try again.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Retry Topic Analysis", callback_data="retry_topic_analysis")]
                ])
            )
            
            state["status"] = "error"
            state["errors"].append("Topic analysis error: Invalid JSON response")
            return state
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in topic analysis step: {error_msg}")
        
        # Update message with error
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=topic_message_id,
            text=f"🔍 *Step 2/4: Topic Analysis*\n\n❌ *Error:* {error_msg}\n\nPlease try again with different parameters.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Retry Analysis", callback_data="retry_topic_analysis")]
            ])
        )
        
        state["status"] = "error"
        state["errors"].append(f"Topic analysis error: {error_msg}")
        return state
    
    # Step 3: Detailed Analysis
    analysis_message = await bot.send_message(
        chat_id=ADMIN_USER_ID,
        text="📈 *Step 3/4: Detailed Analysis*\n\n_Generating detailed discussion analysis..._",
        parse_mode="Markdown"
    )
    analysis_message_id = analysis_message.message_id
    
    try:
        # Update message to show we're analyzing in detail
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=analysis_message_id,
            text="📈 *Step 3/4: Detailed Analysis*\n\n_Analyzing discussions in detail based on identified topics..._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏱️ Generating analysis...", callback_data="analyzing")]
            ])
        )
        
        # Get detailed analysis
        topics_list = ", ".join(state["topics"])
        system_prompt = f"""
        Create a detailed analysis of the conversation based on these main topics: {topics_list}.
        
        Analyze:
        1. Key decisions made
        2. Action items identified
        3. Important questions or issues raised
        4. Overall progress of discussions
        
        Return the analysis as a well-formatted JSON:
        {{
            "key_decisions": ["Decision 1", "Decision 2", ...],
            "action_items": ["Action 1", "Action 2", ...],
            "important_questions": ["Question 1", "Question 2", ...],
            "progress_assessment": "Assessment of progress in discussions"
        }}
        """
        
        detailed_analysis = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Chat messages:\n{messages_text}"}
            ],
            response_format={"type": "json_object"}
        )
        
        try:
            analysis_data = json.loads(detailed_analysis.choices[0].message.content)
            
            # Format for display
            decisions_text = "\n".join([f"• {item}" for item in analysis_data.get("key_decisions", [])])
            if not decisions_text:
                decisions_text = "None identified"
                
            actions_text = "\n".join([f"• {item}" for item in analysis_data.get("action_items", [])])
            if not actions_text:
                actions_text = "None identified"
                
            questions_text = "\n".join([f"• {item}" for item in analysis_data.get("important_questions", [])])
            if not questions_text:
                questions_text = "None identified"
            
            progress = analysis_data.get("progress_assessment", "No assessment available")
            
            # Update message with detailed analysis
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=analysis_message_id,
                text=f"📈 *Step 3/4: Detailed Analysis Complete*\n\n*Key Decisions:*\n{decisions_text}\n\n*Action Items:*\n{actions_text}\n\n*Important Questions:*\n{questions_text}\n\n*Progress Assessment:*\n{progress}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Accept Analysis", callback_data="accept_analysis"),
                     InlineKeyboardButton(text="🔄 Refine Analysis", callback_data="refine_analysis")]
                ])
            )
            
            state["completed_steps"] = 3
            state["current_step"] = "final_summary"
            state["analysis"] = analysis_data
            
        except json.JSONDecodeError:
            # Invalid JSON response
            logger.error("Invalid JSON response from detailed analysis")
            
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=analysis_message_id,
                text="📈 *Step 3/4: Detailed Analysis*\n\n❌ *Error:* Invalid response format. Please try again.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Retry Analysis", callback_data="retry_detailed_analysis")]
                ])
            )
            
            state["status"] = "error"
            state["errors"].append("Detailed analysis error: Invalid JSON response")
            return state
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in detailed analysis step: {error_msg}")
        
        # Update message with error
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=analysis_message_id,
            text=f"📈 *Step 3/4: Detailed Analysis*\n\n❌ *Error:* {error_msg}\n\nPlease try again with refined parameters.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Retry Analysis", callback_data="retry_detailed_analysis")]
            ])
        )
        
        state["status"] = "error"
        state["errors"].append(f"Detailed analysis error: {error_msg}")
        return state
    
    # Step 4: Final Summary
    summary_message = await bot.send_message(
        chat_id=ADMIN_USER_ID,
        text="📝 *Step 4/4: Final Summary*\n\n_Generating concise summary of discussions..._",
        parse_mode="Markdown"
    )
    summary_message_id = summary_message.message_id
    
    try:
        # Update message to show we're generating summary
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=summary_message_id,
            text="📝 *Step 4/4: Final Summary*\n\n_Consolidating all analysis into final summary..._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏱️ Generating summary...", callback_data="generating")]
            ])
        )
        
        # Prepare input for final summary
        topics = ", ".join(state["topics"])
        decisions = ", ".join(state["analysis"].get("key_decisions", []))
        actions = ", ".join(state["analysis"].get("action_items", []))
        questions = ", ".join(state["analysis"].get("important_questions", []))
        progress = state["analysis"].get("progress_assessment", "")
        
        summary_prompt = f"""
        Create a concise, professional summary of the discussion based on the analysis results.
        
        Include:
        - A brief overview of the discussion topics: {topics}
        - Key decisions: {decisions}
        - Action items: {actions}
        - Important questions: {questions}
        - Overall progress: {progress}
        
        Format the summary to be clear, readable and professional with proper paragraphs and structure.
        """
        
        final_summary = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a professional summarizer for business communications. Create clear, concise, well-structured summaries."},
                {"role": "user", "content": summary_prompt}
            ]
        )
        
        summary_text = final_summary.choices[0].message.content
        state["summary"] = summary_text
        
        # Update message with final summary
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=summary_message_id,
            text=f"📝 *Step 4/4: Final Summary*\n\n{summary_text}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Accept Summary", callback_data="accept_summary"),
                 InlineKeyboardButton(text="🔄 Refine Summary", callback_data="refine_summary")]
            ])
        )
        
        # Update main message with completion status
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=main_message_id,
            text=f"✅ *Summary Process Complete*\n\nDiscussion analyzed for {chat_info}\nTime period: {time_period}\nMessages analyzed: {len(state['messages'])}\n\nYou can view the results in the message threads below.",
            parse_mode="Markdown"
        )
        
        state["completed_steps"] = 4
        state["current_step"] = "completed"
        state["status"] = "completed"
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in final summary step: {error_msg}")
        
        # Update message with error
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=summary_message_id,
            text=f"📝 *Step 4/4: Final Summary*\n\n❌ *Error:* {error_msg}\n\nYou can still use previous analysis steps.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Retry Summary", callback_data="retry_summary")]
            ])
        )
        
        state["status"] = "error"
        state["errors"].append(f"Final summary error: {error_msg}")
    
    return state 

async def ai_agent_query(question: str) -> Dict[str, Any]:
    """
    Autonomous AI agent that plans and executes a series of database queries
    to answer any question, showing its reasoning process in Telegram.
    
    Args:
        question: The user's question
        
    Returns:
        Dictionary with the result of the query process
    """
    logger.info(f"Starting autonomous AI agent for question: {question}")
    
    # Create initial message for Telegram that will be updated with reasoning steps
    try:
        from telegram_ai_assistant.bot.telegram_bot import bot, ADMIN_USER_ID
        intro_message = f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n_Initiating thought process..._"
        message_obj = await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=intro_message,
            parse_mode="Markdown"
        )
        message_id = message_obj.message_id
        logger.debug(f"Created initial agent message with ID: {message_id}")
        
        # Update message to show thinking process
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=message_id,
            text=f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Initial Thoughts:*\n• Analyzing question to determine what information is needed\n• Examining database schema to identify relevant tables\n• Considering how to structure queries for optimal results\n• Planning execution steps to answer efficiently\n\n_Developing query plan..._",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error creating initial message: {str(e)}")
        message_id = None
    
    # Database schema description
    db_schema = """
    Available database tables:
    
    1. users
       - id (INTEGER PRIMARY KEY)
       - user_id (INTEGER) - Telegram user ID
       - username (TEXT) - Telegram username
       - first_name (TEXT) - User's first name
       - last_name (TEXT) - User's last name
       - is_bot (BOOLEAN) - Whether user is a bot
       - created_at (TIMESTAMP) - When user was added to DB
    
    2. messages
       - id (INTEGER PRIMARY KEY)
       - message_id (INTEGER) - Telegram message ID
       - chat_id (INTEGER) - ID of the chat where message was sent
       - sender_id (INTEGER) - User ID who sent the message
       - text (TEXT) - Message content
       - attachments (TEXT) - JSON string with attachments
       - timestamp (TIMESTAMP) - When message was sent
       - is_important (BOOLEAN) - Important flag
       - is_processed (BOOLEAN) - Processed flag
       - category (TEXT) - Message category
       - is_bot (BOOLEAN) - Whether sent by bot
    
    3. chats
       - id (INTEGER PRIMARY KEY)
       - chat_id (INTEGER) - Telegram chat ID
       - chat_name (TEXT) - Chat name
       - is_active (BOOLEAN) - Active status
       - last_summary_time (TIMESTAMP) - Last summary generation time
       - linear_team_id (TEXT) - Associated Linear team ID
    
    4. tasks
       - id (INTEGER PRIMARY KEY)
       - linear_id (TEXT) - Linear task ID
       - title (TEXT) - Task title
       - description (TEXT) - Task description
       - status (TEXT) - Task status
       - created_at (TIMESTAMP) - Creation time
       - due_date (TIMESTAMP) - Due date
       - assignee_id (INTEGER) - Assigned user ID
       - message_id (INTEGER) - Origin message ID
       - chat_id (INTEGER) - Origin chat ID
    
    5. unanswered_questions
       - id (INTEGER PRIMARY KEY)
       - message_id (INTEGER) - Question message ID
       - chat_id (INTEGER) - Chat where question was asked
       - target_user_id (INTEGER) - User who should answer
       - sender_id (INTEGER) - User who asked
       - question (TEXT) - Question text
       - asked_at (TIMESTAMP) - When asked
       - is_answered (BOOLEAN) - Answered status
       - answered_at (TIMESTAMP) - When answered
       - reminder_count (INTEGER) - Reminder count
       - last_reminder_at (TIMESTAMP) - Last reminder time
       - is_bot (BOOLEAN) - Whether from bot
    
    6. team_productivity
       - id (INTEGER PRIMARY KEY)
       - user_id (INTEGER) - User ID
       - date (TIMESTAMP) - Record date
       - message_count (INTEGER) - Message count
       - tasks_created (INTEGER) - Tasks created
       - tasks_completed (INTEGER) - Tasks completed
       - avg_response_time (INTEGER) - Average response time
    """
    
    # First, update message to show we're analyzing the question
    if message_id:
        await bot.edit_message_text(
            chat_id=ADMIN_USER_ID,
            message_id=message_id,
            text=f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Analyzing Question:*\n• Breaking down the question to understand key information needs\n• Identifying entities mentioned (users, chats, time periods, etc.)\n• Determining metrics or statistics required\n• Considering potential constraints or filters\n\n_Mapping question to database structure..._",
            parse_mode="Markdown"
        )
    
    # Using JSON mode for function calling to make the agent's planning explicit
    try:
        # Show we're identifying tables
        if message_id:
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=message_id,
                text=f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Analyzing Database Schema:*\n• Examining tables that contain relevant information\n• Determining relationships between tables\n• Identifying fields needed for filters, sorting and display\n• Planning JOINs to connect related data and get human-readable names\n\n_Designing query approach..._",
                parse_mode="Markdown"
            )
        
        # Step 1: Plan the approach
        planning_prompt = f"""
        You are an AI agent that plans and executes database queries to answer questions.
        
        User question: {question}
        
        Based on this database schema:
        {db_schema}
        
        IMPORTANT: Always use names instead of IDs in your final answers. When querying:
        1. ALWAYS join the 'users' table when you need user information, to show usernames/first_name/last_name
        2. ALWAYS join the 'chats' table when you need chat information, to show chat_name
        3. DO NOT return raw IDs in your final results, always display readable names
        
        For all queries involving users, include:
        - u.username as username
        - COALESCE(NULLIF(u.first_name || ' ' || IFNULL(u.last_name, ''), ' '), u.username, 'Unknown') as full_name
        
        For all queries involving chats, include:
        - c.chat_name as chat_name
        
        Plan a series of steps to answer the question, including:
        1. Which tables are relevant
        2. What specific data needs to be queried
        3. How to structure the SQL queries with proper JOINs to show names
        4. How to interpret the results
        
        Return a JSON with the following structure:
        {{
            "question_analysis": "Your understanding of the question",
            "tables_needed": ["table1", "table2"],
            "plan_steps": [
                {{
                    "step": 1,
                    "description": "Description of step 1",
                    "sql_query": "SQL query for step 1",
                    "reasoning": "Why this query is needed and what it will tell us"
                }},
                {{
                    "step": 2,
                    "description": "Description of step 2",
                    "sql_query": "SQL query for step 2 (or null if not a query step)",
                    "reasoning": "Why this step is necessary and what insights it provides"
                }}
            ]
        }}
        """
        
        # Update message to show we're planning
        if message_id:
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=message_id,
                text=f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Planning Query Strategy:*\n• Determining the most efficient sequence of queries\n• Designing queries to extract required information\n• Ensuring all user and chat IDs are mapped to names\n• Planning how results will be analyzed and presented\n\n_Creating comprehensive query plan..._",
                parse_mode="Markdown"
            )
        
        planning_response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are an AI agent specialized in planning database queries to answer questions. Always include user names and chat names instead of IDs."},
                {"role": "user", "content": planning_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        plan = json.loads(planning_response.choices[0].message.content)
        
        # Update message with the plan
        if message_id:
            plan_text = f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Question Analysis:*\n_{plan.get('question_analysis')}_\n\n"
            plan_text += f"*Tables Needed:* {', '.join(plan.get('tables_needed', []))}\n\n"
            plan_text += "*Execution Plan:*\n"
            
            for step in plan.get('plan_steps', []):
                plan_text += f"*Step {step.get('step')}:* {step.get('description')}\n"
                if step.get('reasoning'):
                    plan_text += f"_Reasoning:_ {step.get('reasoning')}\n"
                if 'sql_query' in step and step['sql_query']:
                    plan_text += f"```{step.get('sql_query')}```\n"
            
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=message_id,
                text=plan_text,
                parse_mode="Markdown"
            )
        
        # Step 2: Execute each step in the plan
        all_results = []
        from telegram_ai_assistant.utils.db_utils import execute_sql_query
        
        for i, step in enumerate(plan.get('plan_steps', [])):
            step_num = step.get('step')
            step_desc = step.get('description')
            sql_query = step.get('sql_query')
            step_reasoning = step.get('reasoning', '')
            
            step_result = {
                "step": step_num,
                "description": step_desc,
                "reasoning": step_reasoning,
                "query": sql_query,
                "data": None,
                "error": None
            }
            
            # Update message to show current step with reasoning
            if message_id:
                current_step_text = f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Executing Step {step_num}:*\n{step_desc}\n"
                if step_reasoning:
                    current_step_text += f"*Reasoning:* _{step_reasoning}_\n\n"
                if sql_query:
                    current_step_text += f"*SQL Query:*\n```{sql_query}```\n\n"
                    current_step_text += "_Executing query and analyzing patterns in the data..._"
                
                await bot.edit_message_text(
                    chat_id=ADMIN_USER_ID,
                    message_id=message_id,
                    text=current_step_text,
                    parse_mode="Markdown"
                )
            
            # Execute SQL query if this step has one
            if sql_query:
                try:
                    start_time = datetime.now()
                    
                    # Show query processing status
                    if message_id:
                        await bot.edit_message_text(
                            chat_id=ADMIN_USER_ID,
                            message_id=message_id,
                            text=f"{current_step_text}\n\n*Query Status:*\n• Sending query to database\n• Processing SQL statements\n• Retrieving result set\n• Preparing data for analysis",
                            parse_mode="Markdown"
                        )
                    
                    result = await execute_sql_query(sql_query)
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                    # Check if we need to enrich the results with names
                    if message_id:
                        await bot.edit_message_text(
                            chat_id=ADMIN_USER_ID,
                            message_id=message_id,
                            text=f"{current_step_text}\n\n*Query Status:*\n• Query executed successfully\n• Retrieved {len(result) if result else 0} rows\n• Enriching results with user and chat names\n• Formatting data for readability",
                            parse_mode="Markdown"
                        )
                    
                    result = await enrich_query_results(result)
                    
                    step_result["data"] = result
                    step_result["execution_time"] = f"{execution_time:.2f} seconds"
                    step_result["row_count"] = len(result) if result else 0
                    
                    # Update message with query results and analysis
                    if message_id:
                        result_text = f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Step {step_num} Complete:*\n{step_desc}\n\n"
                        if step_reasoning:
                            result_text += f"*Reasoning:* _{step_reasoning}_\n\n"
                        result_text += f"*Execution Results:*\n• Query executed in {execution_time:.2f} seconds\n• Retrieved {len(result) if result else 0} rows of data\n"
                        
                        if result and len(result) > 0:
                            result_text += "\n*Data Patterns:*\n"
                            # Try to extract some basic patterns from the data
                            if len(result) == 1:
                                result_text += "• Found a single matching record\n"
                            else:
                                result_text += f"• Found {len(result)} matching records\n"
                            
                            # Check for some basic patterns in the data
                            columns = list(result[0].keys())
                            
                            # Sample results section
                            result_text += "\n*Sample Results:*\n"
                            # Format as table for display
                            result_text += "| " + " | ".join(columns) + " |\n"
                            result_text += "| " + " | ".join(["---" for _ in columns]) + " |\n"
                            
                            # Show up to 5 rows
                            for row in result[:5]:
                                result_text += "| " + " | ".join([str(row.get(col, "")) for col in columns]) + " |\n"
                            
                            if len(result) > 5:
                                result_text += f"\n_...and {len(result) - 5} more rows..._\n"
                        else:
                            result_text += "\n*Results:* _No data returned from query._\n"
                            result_text += "• This could indicate that there are no matching records\n• May need to adjust query parameters or check different tables\n"
                        
                        await bot.edit_message_text(
                            chat_id=ADMIN_USER_ID,
                            message_id=message_id,
                            text=result_text,
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error executing query in step {step_num}: {error_msg}")
                    step_result["error"] = error_msg
                    
                    # Update message with error and reasoning
                    if message_id:
                        error_text = f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Error in Step {step_num}:*\n{step_desc}\n\n"
                        error_text += f"*SQL Error:* ```{error_msg}```\n\n"
                        error_text += "*Analysis:*\n• The query failed to execute\n• This may be due to syntax errors, invalid table/column references, or access permissions\n• Attempting to continue with remaining steps for partial insights\n"
                        error_text += "_Proceeding to next steps to gather available information..._"
                        
                        await bot.edit_message_text(
                            chat_id=ADMIN_USER_ID,
                            message_id=message_id,
                            text=error_text,
                            parse_mode="Markdown"
                        )
            
            all_results.append(step_result)
        
        # Update message to show we're analyzing all results
        if message_id:
            analysis_text = f"🤖 *AI Agent Processing*\n\n*Question:* {question}\n\n*Synthesizing Results:*\n"
            analysis_text += "• Combining insights from all queries\n"
            analysis_text += "• Mapping relationships between different data points\n"
            analysis_text += "• Identifying key patterns and trends\n"
            analysis_text += "• Formulating comprehensive answer\n\n"
            analysis_text += "_Generating final answer based on {success_count} successful queries..._"
            
            success_count = sum(1 for result in all_results if result.get("error") is None and result.get("query") is not None)
            analysis_text = analysis_text.replace("{success_count}", str(success_count))
            
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=message_id,
                text=analysis_text,
                parse_mode="Markdown"
            )
        
        # Step 3: Generate the final answer based on all results
        answer_prompt = f"""
        Based on the following query results, provide a comprehensive answer to the user's question.
        
        User question: {question}
        
        Query steps and results:
        {json.dumps(all_results, indent=2)}
        
        IMPORTANT REQUIREMENTS:
        1. ALWAYS use usernames or full names instead of user IDs in your answer
        2. ALWAYS use chat names instead of chat IDs in your answer
        3. Format any dates in a user-friendly way (e.g., "January 15, 2023" or "15 Jan 2023")
        4. If showing metrics, include percentages where appropriate
        
        Provide a clear, detailed answer that directly addresses the user's question.
        If the results don't contain enough information to answer the question completely, acknowledge that and explain what information is missing.
        """
        
        answer_response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are an AI assistant specialized in interpreting database query results to answer questions. Always use names instead of IDs in your answers. Format data in a human-readable way."},
                {"role": "user", "content": answer_prompt}
            ]
        )
        
        final_answer = answer_response.choices[0].message.content
        
        # Update message with final answer
        if message_id:
            final_text = f"🤖 *AI Agent Results*\n\n*Question:* {question}\n\n*Answer:*\n{final_answer}\n\n"
            
            # Add a summary of queries executed
            final_text += "*Query Process Summary:*\n"
            for step_result in all_results:
                if step_result.get("query"):
                    status = "✅" if step_result.get("error") is None else "❌"
                    rows = step_result.get("row_count", 0)
                    exec_time = step_result.get("execution_time", "N/A")
                    final_text += f"{status} Step {step_result.get('step')}: {rows} rows in {exec_time}\n"
            
            await bot.edit_message_text(
                chat_id=ADMIN_USER_ID,
                message_id=message_id,
                text=final_text,
                parse_mode="Markdown"
            )
        
        # Return the final result
        return {
            "question": question,
            "plan": plan,
            "query_results": all_results,
            "answer": final_answer,
            "success": True
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in AI agent query process: {error_msg}")
        
        # Update message with error
        if message_id:
            try:
                error_text = f"🤖 *AI Agent Error*\n\n*Question:* {question}\n\n*Error Analysis:*\n• Processing encountered an unexpected error\n• This may be due to invalid input, system limitations, or temporary issues\n• Error details are provided below\n\n❌ *Error:* {error_msg}"
                
                await bot.edit_message_text(
                    chat_id=ADMIN_USER_ID,
                    message_id=message_id,
                    text=error_text,
                    parse_mode="Markdown"
                )
            except Exception as msg_e:
                logger.error(f"Error updating error message: {str(msg_e)}")
        
        return {
            "question": question,
            "error": error_msg,
            "success": False
        }

async def enrich_query_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Enrich query results by adding human-readable names for IDs
    
    Args:
        results: Original query results
        
    Returns:
        Enriched results with human-readable names
    """
    if not results:
        return results
    
    # Create a copy of the results to avoid modifying the original
    enriched_results = []
    
    # Check if we need to look up chat or user information
    chat_ids_to_lookup = set()
    user_ids_to_lookup = set()
    
    for row in results:
        # Check for chat IDs
        for key in row.keys():
            if 'chat_id' in key and row[key] and isinstance(row[key], (int, str)):
                chat_ids_to_lookup.add(str(row[key]))
            elif ('user_id' in key or 'sender_id' in key) and row[key] and isinstance(row[key], (int, str)):
                user_ids_to_lookup.add(str(row[key]))
    
    # Look up chat names
    chat_names = {}
    if chat_ids_to_lookup:
        try:
            from telegram_ai_assistant.utils.db_utils import execute_sql_query
            chat_query = f"""
            SELECT chat_id, chat_name
            FROM chats
            WHERE chat_id IN ({','.join(chat_ids_to_lookup)})
            """
            chat_results = await execute_sql_query(chat_query)
            for chat in chat_results:
                chat_id = chat.get('chat_id')
                chat_name = chat.get('chat_name')
                if chat_id and chat_name:
                    chat_names[str(chat_id)] = chat_name
        except Exception as e:
            logger.error(f"Error looking up chat names: {str(e)}")
    
    # Look up user names
    user_names = {}
    if user_ids_to_lookup:
        try:
            from telegram_ai_assistant.utils.db_utils import execute_sql_query
            user_query = f"""
            SELECT user_id, username, first_name, last_name
            FROM users
            WHERE user_id IN ({','.join(user_ids_to_lookup)})
            """
            user_results = await execute_sql_query(user_query)
            for user in user_results:
                user_id = user.get('user_id')
                username = user.get('username')
                first_name = user.get('first_name', '')
                last_name = user.get('last_name', '')
                
                # Create a full name display
                full_name = ''
                if first_name:
                    full_name = first_name
                    if last_name:
                        full_name += f" {last_name}"
                
                display_name = username if username else full_name if full_name else f"User {user_id}"
                
                if user_id:
                    user_names[str(user_id)] = display_name
        except Exception as e:
            logger.error(f"Error looking up user names: {str(e)}")
    
    # Enrich the results
    for row in results:
        enriched_row = row.copy()
        
        # Add chat names
        for key in row.keys():
            # Handle chat IDs
            if 'chat_id' in key and row[key] and isinstance(row[key], (int, str)):
                chat_id = str(row[key])
                if chat_id in chat_names:
                    chat_name_key = 'chat_name'
                    if key != 'chat_id':
                        # Create a specific name key for this column (e.g., source_chat_name for source_chat_id)
                        chat_name_key = key.replace('chat_id', 'chat_name')
                    
                    # Only add if the name key doesn't already exist
                    if chat_name_key not in enriched_row:
                        enriched_row[chat_name_key] = chat_names[chat_id]
            
            # Handle user IDs
            elif ('user_id' in key or 'sender_id' in key) and row[key] and isinstance(row[key], (int, str)):
                user_id = str(row[key])
                if user_id in user_names:
                    user_name_key = 'username' if 'user_id' in key else 'sender_name'
                    if key != 'user_id' and key != 'sender_id':
                        # Create a specific name key for this column (e.g., target_username for target_user_id)
                        user_name_key = key.replace('user_id', 'username').replace('sender_id', 'sender_name')
                    
                    # Only add if the name key doesn't already exist
                    if user_name_key not in enriched_row:
                        enriched_row[user_name_key] = user_names[user_id]
        
        enriched_results.append(enriched_row)
    
    return enriched_results