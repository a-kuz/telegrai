import sys
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from openai import AsyncOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_MODEL
from utils.logging_utils import setup_ai_logger

logger = setup_ai_logger()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

async def analyze_message_intent(message_text: str, context_messages: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Analyzes a message to determine its intent:
    - Is it a request to create a task
    - Is it a potential candidate to become a task
    - Is it a question requiring database access
    
    Args:
        message_text: The text message to analyze
        context_messages: Optional recent messages for context
        
    Returns:
        Dictionary with scores and analysis
    """
    
    # Format context if provided
    context_text = ""
    if context_messages:
        formatted_messages = []
        for msg in context_messages[:10]:  # Use up to 10 recent messages for context
            sender = msg.get("sender_name", "Unknown")
            text = msg.get("text", "")
            timestamp = msg.get("timestamp", "")
            if isinstance(timestamp, str):
                timestamp_str = timestamp
            else:
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else ""
            
            formatted_messages.append(f"[{timestamp_str}] {sender}: {text}")
        
        context_text = "\n".join(formatted_messages)
    
    try:
        logger.info(f"Analyzing message intent: {message_text[:50]}...")
        
        system_prompt = """You are an AI assistant for a development team, working through Telegram.
        
        You analyze messages to determine their intent for a task management system connected to Linear.
        
        You need to determine if the message is:
        1. A direct request to create a task (like "create task to fix bug X")
        2. A potential candidate to become a task (like describing a problem that needs fixing)
        3. A question requiring database query (like asking about team stats or development history)
        
        Score each category from 1-10:
        - Task Creation Request: How clearly the message asks to create a task
        - Task Candidate: How suitable the message is to be converted into a task
        - Database Query: How likely the message needs database information to answer
        
        Also provide:
        - If it's a task request/candidate, extract a clear title and description suitable for development tracking
        - If it needs a database query, provide the SQL query text
        
        Focus on PRACTICAL DEVELOPMENT TASKS such as:
        - Bug fixes
        - Feature implementations
        - Performance improvements
        - Code refactoring
        - Testing requirements
        - Documentation needs
        
        Respond in a way that would be helpful for a software development team.
        """
        
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "analyze_message",
                    "description": "Analyze the intent of a message",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_creation_score": {
                                "type": "integer", 
                                "description": "Score 1-10 on how clearly this is a request to create a task",
                                "minimum": 1,
                                "maximum": 10
                            },
                            "task_candidate_score": {
                                "type": "integer",
                                "description": "Score 1-10 on how suitable this message is to become a task",
                                "minimum": 1,
                                "maximum": 10
                            },
                            "database_query_score": {
                                "type": "integer",
                                "description": "Score 1-10 on how likely this needs database information",
                                "minimum": 1,
                                "maximum": 10
                            },
                            "primary_intent": {
                                "type": "string",
                                "enum": ["task_creation", "task_candidate", "database_query", "other"],
                                "description": "The primary intent of the message based on highest score"
                            },
                            "task_title": {
                                "type": "string",
                                "description": "If task-related, a clear concise title"
                            },
                            "task_description": {
                                "type": "string",
                                "description": "If task-related, a clear technical description"
                            },
                            "sql_query": {
                                "type": "string",
                                "description": "If database query needed, the SQL query text"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Brief explanation of the analysis"
                            }
                        },
                        "required": [
                            "task_creation_score", 
                            "task_candidate_score", 
                            "database_query_score", 
                            "primary_intent",
                            "reasoning"
                        ]
                    }
                }
            }
        ]
        
        # Create prompt with context if available
        user_content = f"Message to analyze: {message_text}"
        if context_text:
            user_content = f"Recent context:\n{context_text}\n\nMessage to analyze: {message_text}"
        
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "analyze_message"}}
        )
        
        # Extract analysis results
        if hasattr(response.choices[0].message, 'tool_calls') and response.choices[0].message.tool_calls:
            tool_call = response.choices[0].message.tool_calls[0]
            if tool_call.function.name == "analyze_message":
                function_args = json.loads(tool_call.function.arguments)
                
                # Add empty strings for optional properties if not present
                if "task_title" not in function_args:
                    function_args["task_title"] = ""
                if "task_description" not in function_args:
                    function_args["task_description"] = ""
                if "sql_query" not in function_args:
                    function_args["sql_query"] = ""
                    
                logger.info(f"Message intent analysis complete - primary intent: {function_args['primary_intent']}")
                return function_args
        
        # Fallback if tool calls don't work
        logger.warning("Tool call didn't return expected data, using fallback")
        return {
            "task_creation_score": 1,
            "task_candidate_score": 1,
            "database_query_score": 1,
            "primary_intent": "other",
            "task_title": "",
            "task_description": "",
            "sql_query": "",
            "reasoning": "Failed to analyze message intent"
        }
        
    except Exception as e:
        logger.error(f"Error analyzing message intent: {str(e)}")
        return {
            "task_creation_score": 1,
            "task_candidate_score": 1,
            "database_query_score": 1, 
            "primary_intent": "other",
            "task_title": "",
            "task_description": "",
            "sql_query": "",
            "reasoning": f"Error: {str(e)}"
        }

async def get_required_context(message_text: str, available_chats: List[Dict[str, Any]], current_chat_messages: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Определяет, какие данные из базы данных или истории сообщений могут быть полезны для ответа на вопрос пользователя.
    
    Args:
        message_text: Текст сообщения пользователя
        available_chats: Список доступных чатов с их базовой информацией
        current_chat_messages: Последние сообщения из текущего чата (если есть)
        
    Returns:
        Словарь с информацией о требуемых данных и дополнительном контексте
    """
    # Проверяем наличие временных указаний в вопросе
    time_indicators = {
        "сегодня": "today",
        "вчера": "yesterday",
        "неделю": "week",
        "неделя": "week",
        "этой неделе": "week",
        "на этой неделе": "week",
        "за неделю": "week", 
        "месяц": "month",
        "за месяц": "month",
        "в этом месяце": "month",
        "текущий месяц": "month",
        "прошлый месяц": "last_month",
        "прошлой неделе": "last_week",
        "на прошлой неделе": "last_week",
        "за прошлую неделю": "last_week",
        "год": "year",
        "за год": "year",
        "в этом году": "year"
    }
    
    time_period = None
    for indicator, period in time_indicators.items():
        if indicator in message_text.lower():
            time_period = period
            break
    
    # Форматируем информацию о доступных чатах
    chats_info = []
    for chat in available_chats:
        chat_name = chat.get("chat_name", "Unnamed chat")
        chat_id = chat.get("chat_id", "unknown")
        message_count = chat.get("message_count", 0)
        chats_info.append(f"- {chat_name} (ID: {chat_id}, сообщений: {message_count})")
    
    chats_context = "\n".join(chats_info)
    
    # Форматируем контекст текущего чата, если он есть
    current_chat_context = ""
    if current_chat_messages:
        messages_formatted = []
        for msg in current_chat_messages[:5]:  # Добавляем только 5 последних сообщений в контекст запроса
            sender = msg.get("sender_name", "Unknown")
            text = msg.get("text", "")
            timestamp = msg.get("timestamp", "")
            if isinstance(timestamp, str):
                timestamp_str = timestamp
            else:
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else ""
            
            messages_formatted.append(f"[{timestamp_str}] {sender}: {text}")
        
        current_chat_context = "\n".join(messages_formatted)
    
    # Добавляем информацию о выявленном временном периоде
    time_period_info = ""
    if time_period:
        time_period_info = f"\n\nВ вопросе указан временной период: {time_period}"
    
    # Определение функций для OpenAI
    functions = [
        {
            "type": "function",
            "function": {
                "name": "request_database_data",
                "description": "Запрашивает данные из базы данных для ответа на вопрос пользователя",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql_query": {
                            "type": "string",
                            "description": "SQL запрос для получения необходимых данных"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Объяснение, почему эти данные нужны для ответа"
                        }
                    },
                    "required": ["sql_query", "explanation"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "request_chat_history",
                "description": "Запрашивает дополнительную историю сообщений из определенных чатов",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chat_ids": {
                            "type": "array",
                            "items": {
                                "type": "integer"
                            },
                            "description": "Список ID чатов, история которых требуется"
                        },
                        "message_count": {
                            "type": "integer",
                            "description": "Количество последних сообщений для каждого чата"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Объяснение, почему история этих чатов нужна для ответа"
                        }
                    },
                    "required": ["chat_ids", "message_count", "explanation"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "answer_from_available_context",
                "description": "Отвечает на вопрос, используя только уже доступный контекст",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reasoning": {
                            "type": "string",
                            "description": "Пояснение логики ответа на основе имеющегося контекста"
                        }
                    },
                    "required": ["reasoning"]
                }
            }
        }
    ]
    
    # Описание схемы базы данных для подсказки LLM - ОБНОВЛЕННАЯ И ТОЧНАЯ СХЕМА
    db_schema = """
    Точная схема базы данных (используйте именно эти таблицы и поля):
    
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
       
    Примечания:
    - Таблицы 'chat_history' НЕ существует
    - Все запросы к чатам должны идти через таблицу messages, используя поле chat_id
    - Для связи пользователей используйте соединение messages.sender_id = users.user_id
    - Для статистики общения рекомендуется использовать таблицу team_productivity
    - Для фильтрации по дате используйте messages.timestamp или team_productivity.date
    """
    
    try:
        logger.info(f"Определение необходимого контекста для сообщения: {message_text[:50]}...")
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": f"""Ты опытный аналитик, который помогает пользователям получать информацию о коммуникациях и задачах команды.

Твоя основная задача - определить, какую информацию запросить для полного ответа на вопрос пользователя.

{db_schema}

Помни, что вопросы о статистике, количестве сообщений, активности пользователей или задачах почти всегда требуют запроса к базе данных. Предпочитай получать актуальные и точные данные из базы, а не из ограниченного контекста сообщений.

При определении источника данных руководствуйся следующими принципами:

1. Для статистических вопросов (кто, сколько, когда, какие тренды) почти ВСЕГДА требуется запрос к БД
2. Для любых вопросов со словами "больше всех", "меньше всех", "чаще всего", "самый активный" - всегда нужна база данных
3. История сообщений полезна для контекста обсуждений и тем, но не для точной статистики
4. Для вопросов с указанием на период времени ("сегодня", "за неделю", "в этом месяце") ВСЕГДА используй базу данных

Выбери один из трех вариантов:
1. Запросить данные из базы данных (если нужна точная информация)
2. Запросить дополнительную историю чатов (если нужен контекст обсуждения)
3. Использовать имеющийся контекст (только если вопрос не требует специфических данных)

При составлении SQL-запросов:
- Используй только существующие таблицы и поля, указанные в схеме выше
- НИКОГДА не обращайся к таблице 'chat_history', ее не существует
- Для фильтрации по сегодняшней дате используй: DATE(messages.timestamp) = DATE('now') или DATE(team_productivity.date) = DATE('now')
- Для фильтрации по текущей неделе: DATE(messages.timestamp) >= DATE('now', 'weekday 0', '-7 days')
- Для фильтрации по месяцу: DATE(messages.timestamp) >= DATE('now', 'start of month')
- Для подсчета сообщений от пользователей соединяй таблицы messages и users
- При поиске "лучших" или "больше всех" обязательно используй ORDER BY и GROUP BY

Запросы должны быть конкретными и осмысленными, учитывать все нюансы вопроса.
"""},
                {"role": "user", "content": f"""Вопрос пользователя: {message_text}
                
                Доступные чаты:
                {chats_context}
                
                {f"История текущего чата (последние сообщения):\n{current_chat_context}" if current_chat_context else ""}
                {time_period_info}
                """}
            ],
            tools=functions,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        logger.debug(f"Получен ответ от модели о необходимом контексте")
        
        # Проверяем, была ли вызвана функция
        if message.tool_calls:
            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            if function_name == "request_database_data":
                logger.info(f"Требуется SQL запрос: {function_args.get('sql_query')[:50]}...")
                return {
                    "type": "database_query",
                    "context_type": "database_query",
                    "sql_query": function_args.get("sql_query"),
                    "explanation": function_args.get("explanation"),
                    "note": function_args.get("explanation")
                }
            elif function_name == "request_chat_history":
                chat_ids = function_args.get("chat_ids", [])
                logger.info(f"Требуется история чатов: {chat_ids}")
                return {
                    "type": "chat_history",
                    "context_type": "chat_history",
                    "chat_ids": chat_ids,
                    "message_count": function_args.get("message_count"),
                    "explanation": function_args.get("explanation"),
                    "note": function_args.get("explanation")
                }
            else:  # answer_from_available_context
                logger.info("Достаточно имеющегося контекста")
                return {
                    "type": "use_available_context",
                    "context_type": "use_available_context",
                    "reasoning": function_args.get("reasoning"),
                    "note": function_args.get("reasoning")
                }
        else:
            # Если функция не была вызвана, считаем, что достаточно текущего контекста
            logger.info("Достаточно имеющегося контекста (нет вызова функции)")
            return {
                "type": "use_available_context",
                "context_type": "use_available_context",
                "reasoning": "Доступной информации достаточно для ответа на вопрос.",
                "note": "Доступной информации достаточно для ответа на вопрос."
            }
    except Exception as e:
        logger.error(f"Ошибка определения необходимого контекста: {str(e)}")
        return {
            "type": "error",
            "context_type": "error",
            "error": str(e),
            "message": "Произошла ошибка при определении необходимых данных."
        }

async def process_question_with_context(question, chat_id, available_chats=None):
    """
    Process a question with appropriate context from chat history or database
    
    Args:
        question: The question text
        chat_id: Current chat ID
        available_chats: List of available chats (optional)
        
    Returns:
        Answer text based on the available context
    """
    try:
        from telegram_ai_assistant.utils.db_utils import get_recent_chat_messages, execute_sql_query
        
        logger.info(f"Processing question: {question}")
        processing_result = {"context_used": None, "answer": None, "details": None}
        
        # Get messages from the current chat for context - always get 30 messages
        current_chat_messages = await get_recent_chat_messages(chat_id, hours=48, limit=30)
        logger.info(f"Retrieved {len(current_chat_messages)} context messages from chat {chat_id}")
        
        if not available_chats:
            # Get list of available chats from database
            logger.info("No available_chats provided, attempting to fetch recent chats")
            try:
                # Simple query to get 10 most recent active chats
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
                available_chats = await execute_sql_query(chats_query) or []
                logger.info(f"Retrieved {len(available_chats)} available chats for context")
            except Exception as e:
                logger.error(f"Error retrieving available chats: {str(e)}")
                available_chats = []
        
        # Database schema to ensure accurate SQL queries
        db_schema = """
        Точная схема базы данных (используйте именно эти таблицы и поля):
        
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
           
        Примечания:
        - Таблицы 'chat_history' НЕ существует
        - Все запросы к чатам должны идти через таблицу messages, используя поле chat_id
        - Для связи пользователей используйте соединение messages.sender_id = users.user_id
        - Для статистики общения рекомендуется использовать таблицу team_productivity
        - Для фильтрации по дате используйте messages.timestamp или team_productivity.date
        """
        
        # Determine what context is needed to answer the question
        context_analysis_result = await get_required_context(
            message_text=question,
            available_chats=available_chats or [],
            current_chat_messages=current_chat_messages
        )
        
        logger.info(f"Context analysis result: {context_analysis_result.get('context_type', 'unknown')}")
        
        # Extract information from the context analysis
        context_type = context_analysis_result.get("context_type")
        sql_query = context_analysis_result.get("sql_query", "")
        chat_history_info = context_analysis_result.get("chat_history_info", {})
        other_chats = context_analysis_result.get("other_chats", [])
        note = context_analysis_result.get("note", "")
        context_text = ""
        
        if context_type == "database_query":
            logger.info(f"Требуется SQL запрос: {sql_query[:50]}...")
            
            # Log full SQL query for debugging
            logger.info("FULL SQL QUERY:")
            logger.info(sql_query)
            
            # Check if query references the non-existent chat_history table and fix it
            if "chat_history" in sql_query.lower():
                logger.error("SQL query contains reference to non-existent 'chat_history' table")
                
                # Try to replace with appropriate messages table query
                fixed_query = sql_query.lower().replace(
                    "chat_history", 
                    "messages"
                )
                
                logger.info("Attempting to fix query by replacing 'chat_history' with 'messages':")
                logger.info(fixed_query)
                
                # Update the query
                sql_query = fixed_query
            
            # Создаем переменную для хранения результата запроса
            query_result = None
            
            try:
                # Log attempt to execute SQL query
                logger.info(f"Attempting to execute SQL query")
                
                # Выполняем SQL запрос
                query_result = await execute_sql_query(sql_query)
                
                # Log result summary
                if query_result:
                    logger.info(f"SQL query executed successfully, returned {len(query_result)} rows")
                else:
                    logger.info("SQL query executed but returned no results")
                
            except Exception as e:
                logger.error(f"Ошибка выполнения SQL запроса: {str(e)}")
                query_result = [{"error": str(e)}]
            
            # Формируем ответ на основе результатов запроса
            answer_system_prompt = """Ты профессиональный аналитик, который отвечает на вопросы на основе данных.
            Твоя задача - объяснить результаты SQL запроса пользователю в понятной форме.
            
            ВАЖНО: Таблицы 'chat_history' НЕ существует в базе данных. 
            Работать нужно с существующими таблицами: users, messages, chats, tasks, unanswered_questions, team_productivity.
            
            Данные получены из базы данных Telegram чатов и содержат информацию о сообщениях, пользователях и задачах.
            
            Формируй ответ так, чтобы он был:
            1. Содержательным и точным
            2. Лаконичным, но полным
            3. Структурированным для удобства восприятия
            4. С указанием конкретных чисел и фактов
            
            Если в данных нет ответа на вопрос или есть ошибка SQL, честно скажи об этом и объясни, что таблица 'chat_history' 
            не существует, данные нужно искать в таблице messages с фильтрацией по chat_id.
            """
            
            context_analysis_result = {
                "type": "database_query",
                "context_type": "database_query",
                "sql_query": sql_query,
                "explanation": note,
                "result": query_result
            }
        elif context_type == "chat_history":
            logger.info("Используем контекст чата для ответа")
            
            # Collect messages from current chat
            chat_messages = []
            time_frame = chat_history_info.get("time_frame", 24)
            limit = chat_history_info.get("message_limit", 40)
            
            # Use messages we already retrieved
            if current_chat_messages:
                chat_messages = current_chat_messages
                
                # Format chat messages for context
                formatted_messages = []
                for msg in chat_messages:
                    sender = msg.get("sender_name", "Unknown")
                    text = msg.get("text", "")
                    timestamp = msg.get("timestamp", "")
                    if isinstance(timestamp, datetime):
                        timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M")
                    else:
                        timestamp_str = str(timestamp)
                    
                    formatted_messages.append(f"[{timestamp_str}] {sender}: {text}")
                
                context_text = "История сообщений:\n" + "\n".join(formatted_messages)
            else:
                context_text = "История сообщений отсутствует."
            
            context_analysis_result = {
                "type": "chat_history",
                "context_type": "chat_history",
                "messages": chat_messages,
                "explanation": note
            }
        else:
            # No specific context needed, just use the current chat messages
            logger.info("Специальный контекст не требуется, используем общую информацию")
            
            if current_chat_messages:
                # Format a few recent messages for general context
                formatted_messages = []
                for msg in current_chat_messages[:5]:  # Use just a few most recent messages
                    sender = msg.get("sender_name", "Unknown")
                    text = msg.get("text", "")
                    formatted_messages.append(f"{sender}: {text}")
                
                context_text = "Недавние сообщения:\n" + "\n".join(formatted_messages)
            else:
                context_text = "Контекст отсутствует."
                
            context_analysis_result = {
                "type": "no_special_context",
                "context_type": "general",
                "explanation": "Для ответа не требуется специальный контекст."
            }
            
        # Now generate an answer based on the available context
        answer_system_prompt = """Ты ИИ-помощник в Telegram, который специализируется на управлении разработкой и управлении проектами.
        Твоя задача - помогать команде разработчиков организовывать работу, отслеживать задачи и анализировать данные проекта.
        
        Ты работаешь в Telegram и можешь:
        1. Создавать задачи в Linear (система управления задачами)
        2. Анализировать продуктивность команды
        3. Отвечать на вопросы на основе данных чатов и базы данных
        4. Предоставлять сводку по текущим дискуссиям
        
        ВАЖНО: База данных содержит следующие таблицы - users, messages, chats, tasks, unanswered_questions, team_productivity.
        Таблицы 'chat_history' НЕ существует! 
        
        Для получения истории сообщений используется таблица messages с фильтрацией по chat_id.
        
        Ты всегда получаешь последние 30 сообщений из текущего чата и список 10 последних чатов для контекста.
        
        Отвечай как опытный менеджер проектов - прямо, содержательно и полезно.
        Фокусируйся на практической помощи команде разработчиков.
        
        Если в контексте не хватает информации для полного ответа, скажи об этом и предложи, какую дополнительную информацию можно было бы собрать.
        Твои ответы должны быть конкретными и полезными для разработчиков.
        """
        
        # Prepare context for answer generation
        answer_context = f"Контекст:\n\n{context_text}"
        
        # Always add information about available chats
        if available_chats:
            chats_info = "\n\nДоступные чаты:\n"
            for chat in available_chats[:10]:  # Limit to 10 chats
                chat_name = chat.get("chat_name") if chat.get("chat_name") else f"Chat {chat.get('chat_id')}"
                last_activity = "Неизвестно"
                if chat.get("last_message_time"):
                    try:
                        if isinstance(chat["last_message_time"], str):
                            last_message_time = datetime.fromisoformat(chat.get("last_message_time"))
                        else:
                            last_message_time = chat.get("last_message_time")
                        delta = datetime.utcnow() - last_message_time
                        if delta.days > 0:
                            last_activity = f"{delta.days} дней назад"
                        elif delta.seconds >= 3600:
                            last_activity = f"{delta.seconds // 3600} часов назад"
                        else:
                            last_activity = f"{delta.seconds // 60} минут назад"
                    except Exception as e:
                        last_activity = "Ошибка форматирования времени"
                
                chats_info += f"• {chat_name} (ID: {chat.get('chat_id')}), сообщений: {chat.get('message_count', 0)}, последняя активность: {last_activity}\n"
            
            answer_context += chats_info
        
        # Always explicitly include the current messages for context
        if current_chat_messages:
            messages_info = "\n\nПоследние сообщения текущего чата:\n"
            for msg in current_chat_messages[:30]:  # Limit to 30 messages
                sender = msg.get("sender_name", "Unknown")
                text = msg.get("text", "")
                timestamp = msg.get("timestamp", "")
                if isinstance(timestamp, datetime):
                    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M")
                else:
                    timestamp_str = str(timestamp)
                
                messages_info += f"[{timestamp_str}] {sender}: {text}\n"
            
            answer_context += messages_info
        
        # Add SQL query results if available
        if context_analysis_result.get('context_type') == 'database_query' and 'result' in context_analysis_result:
            sql_results = context_analysis_result.get('result', [])
            
            if sql_results:
                # Format SQL results for better readability
                if isinstance(sql_results, list) and len(sql_results) > 0:
                    # Check if there's an error
                    if len(sql_results) == 1 and 'error' in sql_results[0]:
                        sql_results_text = f"⚠️ Ошибка выполнения SQL запроса: {sql_results[0]['error']}"
                    else:
                        # Format as table if multiple rows
                        if len(sql_results) > 1:
                            # Get column names from first row
                            columns = list(sql_results[0].keys())
                            
                            # Create header
                            sql_results_text = "Результаты SQL запроса:\n\n"
                            
                            # Add column headers
                            sql_results_text += " | ".join(columns) + "\n"
                            sql_results_text += "-" * (len(" | ".join(columns))) + "\n"
                            
                            # Add rows (limit to 10 rows to avoid too long context)
                            max_rows = min(10, len(sql_results))
                            for i in range(max_rows):
                                row = sql_results[i]
                                row_values = [str(row.get(col, "")) for col in columns]
                                sql_results_text += " | ".join(row_values) + "\n"
                                
                            if len(sql_results) > 10:
                                sql_results_text += f"\n... и еще {len(sql_results) - 10} строк (всего {len(sql_results)})"
                        else:
                            # Format as key-value pairs for single row
                            sql_results_text = "Результаты SQL запроса:\n\n"
                            for key, value in sql_results[0].items():
                                sql_results_text += f"{key}: {value}\n"
                
                    # Add SQL results to context
                    answer_context += f"\n\nРезультаты запроса к базе данных:\n{sql_results_text}"
                    
                    # Also add the original SQL query for reference
                    answer_context += f"\n\nИспользованный SQL запрос:\n{context_analysis_result.get('sql_query', '')}"
        
        # Generate the answer
        answer_response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": answer_system_prompt},
                {"role": "user", "content": f"{answer_context}\n\nВопрос пользователя: {question}\n\nДай развернутый и полезный ответ."}
            ]
        )
        
        answer = answer_response.choices[0].message.content.strip()
        
        # Add context details for debugging if needed
        processing_result = {
            "context_used": context_type,
            "answer": answer,
            "details": context_analysis_result
        }
        
        logger.info(f"Generated answer for question (first 50 chars): {answer[:50]}...")
        return processing_result
        
    except Exception as e:
        logger.error(f"Error processing question with context: {str(e)}", exc_info=True)
        return {
            "context_used": "error",
            "answer": f"Извините, произошла ошибка при обработке вашего вопроса: {str(e)}",
            "details": {"error": str(e)}
        } 