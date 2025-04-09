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
    if sender_id == admin_user_id or message_data.get("is_bot", False):
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