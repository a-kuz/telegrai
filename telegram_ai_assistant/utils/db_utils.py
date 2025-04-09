import sys
import os
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, func, and_, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.future import select
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telegram_ai_assistant.config import DB_URI
from utils.db_models import Chat, User, Message, Task, UnansweredQuestion, TeamProductivity, Base
from utils.logging_utils import setup_db_logger
logger = setup_db_logger()
engine = create_engine(DB_URI)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
async def store_message(chat_id, chat_name, message_id, sender_id, sender_name, 
                        text, attachments=None, timestamp=None, is_bot=False):
    session = SessionLocal()
    try:
        logger.debug(f"Storing message {message_id} from chat {chat_id}")
        chat = session.query(Chat).filter(Chat.chat_id == chat_id).first()
        if not chat:
            logger.info(f"Creating new chat record for chat_id {chat_id} ({chat_name})")
            chat = Chat(chat_id=chat_id, chat_name=chat_name)
            session.add(chat)
            session.flush()
        user = session.query(User).filter(User.user_id == sender_id).first()
        if not user:
            name_parts = sender_name.split(maxsplit=1)
            first_name = name_parts[0] if name_parts else ""
            last_name = name_parts[1] if len(name_parts) > 1 else ""
            
            # Extract username if present in sender_name (common format: first_name username)
            username = None
            if '@' in sender_name:
                # Try to extract username if it's in the format with @
                username_parts = [part for part in sender_name.split() if part.startswith('@')]
                if username_parts:
                    username = username_parts[0][1:]  # Remove @ symbol
            
            logger.info(f"Creating new user record for user_id {sender_id} ({sender_name})")
            user = User(
                user_id=sender_id, 
                first_name=first_name, 
                last_name=last_name,
                username=username,
                is_bot=is_bot
            )
            session.add(user)
            session.flush()
        else:
            # If user exists, make sure is_bot flag is set correctly
            if user.is_bot != is_bot:
                user.is_bot = is_bot
                logger.info(f"Updated is_bot status for user {sender_id} to {is_bot}")
                
        attachments_json = json.dumps(attachments) if attachments else "[]"
        message_time = timestamp if timestamp else datetime.utcnow()
        message = Message(
            message_id=message_id,
            chat_id=chat_id,
            sender_id=sender_id,
            text=text,
            attachments=attachments_json,
            timestamp=message_time,
            is_important=False,
            is_processed=False,
            category="default",
            is_bot=is_bot
        )
        session.add(message)
        today = datetime.utcnow().date()
        productivity = session.query(TeamProductivity).filter(
            TeamProductivity.user_id == sender_id,
            func.date(TeamProductivity.date) == today
        ).first()
        if productivity:
            productivity.message_count += 1
        else:
            logger.debug(f"Creating new productivity record for user_id {sender_id}")
            productivity = TeamProductivity(
                user_id=sender_id,
                date=datetime.utcnow(),
                message_count=1
            )
            session.add(productivity)
        session.commit()
        logger.debug(f"Successfully stored message {message_id} with internal ID {message.id}")
        return message.id
    except Exception as e:
        session.rollback()
        logger.error(f"Error storing message {message_id}: {str(e)}", exc_info=True)
        raise e
    finally:
        session.close()
async def get_recent_chat_messages(chat_id, hours=24, limit=100):
    """
    Retrieve recent messages from a specific chat
    Args:
        chat_id: Chat ID
        hours: Number of hours to look back (default 24)
        limit: Maximum number of messages to return
    Returns:
        List of message objects
    """
    try:
        # Construct the SQL query with parameters
        sql_query = text("""
        SELECT m.id, m.message_id, m.chat_id, m.sender_id, 
               m.text, m.timestamp, u.first_name, u.last_name, u.username, u.is_bot
        FROM messages m
        LEFT JOIN users u ON m.sender_id = u.user_id
        WHERE m.chat_id = :chat_id
        AND m.timestamp >= :timestamp
        ORDER BY m.timestamp DESC
        LIMIT :limit
        """)
        
        # Calculate the timestamp for the given hours ago
        timestamp = datetime.utcnow() - timedelta(hours=hours)
        
        # Log the query and parameters
        logger.info(f"Executing SQL query to get recent chat messages:")
        logger.info(f"SQL: {sql_query}")
        logger.info(f"Parameters: chat_id={chat_id}, timestamp={timestamp}, limit={limit}")
        
        # Create a new session
        session = SessionLocal()
        
        # Raw SQL query for better performance
        result = session.execute(
            sql_query,
            {
                "chat_id": chat_id,
                "timestamp": timestamp,
                "limit": limit
            }
        )
        
        # Process and format the results
        messages = []
        for row in result:
            # Construct sender name based on available information
            sender_name = f"{row.first_name or ''} {row.last_name or ''}".strip()
            if not sender_name and row.username:
                sender_name = row.username
            if not sender_name:
                sender_name = f"User {row.sender_id}"
                
            if row.is_bot:
                sender_name += " (bot)"
                
            messages.append({
                "id": row.id,
                "message_id": row.message_id,
                "chat_id": row.chat_id,
                "sender_id": row.sender_id,
                "sender_name": sender_name,
                "text": row.text,
                "timestamp": row.timestamp
            })
        
        # Log the number of messages retrieved
        logger.info(f"Retrieved {len(messages)} messages from chat {chat_id}")
        
        session.close()
        return messages
    except Exception as e:
        logger.error(f"Error retrieving recent chat messages: {str(e)}")
        return []
async def mark_question_as_answered(message_id, chat_id):
    session = SessionLocal()
    try:
        logger.debug(f"Marking question as answered for message {message_id} in chat {chat_id}")
        question = session.query(UnansweredQuestion).filter(
            UnansweredQuestion.message_id == message_id,
            UnansweredQuestion.chat_id == chat_id
        ).first()
        if question:
            question.is_answered = True
            session.commit()
            logger.info(f"Question {question.id} marked as answered")
            return True
        logger.debug(f"No matching question found for message {message_id} in chat {chat_id}")
        return False
    except Exception as e:
        logger.error(f"Error marking question as answered: {str(e)}", exc_info=True)
        raise e
    finally:
        session.close()
async def store_unanswered_question(message_id, chat_id, target_user_id, question_text, sender_id=None, is_bot=False):
    session = SessionLocal()
    try:
        logger.debug(f"Storing unanswered question from message {message_id} in chat {chat_id}")
        if is_bot:
            logger.info(f"Skipping question from bot (message {message_id})")
            return None
        question = UnansweredQuestion(
            message_id=message_id,
            chat_id=chat_id,
            target_user_id=target_user_id,
            question=question_text,
            asked_at=datetime.utcnow(),
            sender_id=sender_id,
            is_bot=is_bot
        )
        session.add(question)
        session.commit()
        logger.info(f"Stored unanswered question with ID {question.id}")
        return question.id
    except Exception as e:
        session.rollback()
        logger.error(f"Error storing unanswered question: {str(e)}", exc_info=True)
        raise e
    finally:
        session.close()
async def get_pending_reminders(user_id, hours_threshold=1):
    session = SessionLocal()
    try:
        logger.debug(f"Getting pending reminders for user {user_id}, threshold {hours_threshold} hours")
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_threshold)
        questions = session.query(UnansweredQuestion).filter(
            UnansweredQuestion.target_user_id == user_id,
            UnansweredQuestion.is_answered == False,
            UnansweredQuestion.asked_at <= cutoff_time
        ).all()
        result = [
            {
                "id": q.id,
                "message_id": q.message_id,
                "chat_id": q.chat_id,
                "question": q.question,
                "asked_at": q.asked_at,
                "reminder_count": q.reminder_count,
                "sender_id": q.sender_id,
                "is_bot": q.is_bot if hasattr(q, 'is_bot') else False
            }
            for q in questions
        ]
        logger.debug(f"Found {len(result)} pending reminders for user {user_id}")
        return result
    except Exception as e:
        logger.error(f"Error getting pending reminders: {str(e)}", exc_info=True)
        raise e
    finally:
        session.close()
async def update_reminder_sent(question_id):
    session = SessionLocal()
    try:
        logger.debug(f"Updating reminder count for question {question_id}")
        question = session.query(UnansweredQuestion).filter(
            UnansweredQuestion.id == question_id
        ).first()
        if question:
            question.last_reminder_at = datetime.utcnow()
            question.reminder_count += 1
            session.commit()
            logger.info(f"Updated reminder count to {question.reminder_count} for question {question_id}")
            return True
        logger.warning(f"Question {question_id} not found for reminder update")
        return False
    except Exception as e:
        logger.error(f"Error updating reminder: {str(e)}", exc_info=True)
        raise e
    finally:
        session.close()
async def store_task(title, description, linear_id, status, assignee_id=None, 
                    due_date=None, message_id=None, chat_id=None):
    session = SessionLocal()
    try:
        task = Task(
            linear_id=linear_id,
            title=title,
            description=description,
            status=status,
            assignee_id=assignee_id,
            due_date=due_date,
            message_id=message_id,
            chat_id=chat_id,
            created_at=datetime.utcnow()
        )
        session.add(task)
        if assignee_id:
            today = datetime.utcnow().date()
            productivity = session.query(TeamProductivity).filter(
                TeamProductivity.user_id == assignee_id,
                func.date(TeamProductivity.date) == today
            ).first()
            if productivity:
                productivity.tasks_created += 1
            else:
                productivity = TeamProductivity(
                    user_id=assignee_id,
                    date=datetime.utcnow(),
                    message_count=0,
                    tasks_created=1
                )
                session.add(productivity)
        session.commit()
        return task.id
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
async def update_task_status(linear_id, new_status):
    session = SessionLocal()
    try:
        task = session.query(Task).filter(Task.linear_id == linear_id).first()
        if task:
            old_status = task.status
            task.status = new_status
            if new_status.lower() in ["done", "completed", "merged"] and old_status.lower() not in ["done", "completed", "merged"]:
                if task.assignee_id:
                    today = datetime.utcnow().date()
                    productivity = session.query(TeamProductivity).filter(
                        TeamProductivity.user_id == task.assignee_id,
                        func.date(TeamProductivity.date) == today
                    ).first()
                    if productivity:
                        productivity.tasks_completed += 1
                    else:
                        productivity = TeamProductivity(
                            user_id=task.assignee_id,
                            date=datetime.utcnow(),
                            message_count=0,
                            tasks_completed=1
                        )
                        session.add(productivity)
            session.commit()
            return True
        return False
    finally:
        session.close()
async def get_tasks_by_due_date(days=1):
    session = SessionLocal()
    try:
        today = datetime.utcnow().date()
        cutoff_date = today + timedelta(days=days)
        tasks = session.query(Task).filter(
            Task.due_date <= cutoff_date,
            Task.due_date >= today,
            Task.status.notin_(["Done", "Completed", "Merged"])
        ).all()
        return [
            {
                "id": task.id,
                "linear_id": task.linear_id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "due_date": task.due_date,
                "assignee_id": task.assignee_id,
                "assignee_name": f"{task.assignee.first_name} {task.assignee.last_name}".strip() if task.assignee else "Unassigned"
            }
            for task in tasks
        ]
    finally:
        session.close()
async def get_team_productivity(days=7):
    session = SessionLocal()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        productivity_data = session.query(
            TeamProductivity.user_id,
            func.sum(TeamProductivity.message_count).label("total_messages"),
            func.sum(TeamProductivity.tasks_created).label("total_tasks_created"),
            func.sum(TeamProductivity.tasks_completed).label("total_tasks_completed"),
            func.avg(TeamProductivity.avg_response_time).label("avg_response_time")
        ).filter(
            TeamProductivity.date >= cutoff_date
        ).group_by(
            TeamProductivity.user_id
        ).all()
        result = []
        for item in productivity_data:
            user = session.query(User).filter(User.user_id == item.user_id).first()
            
            # Skip bots
            if user and user.is_bot:
                continue
                
            # Fix user name formatting
            if user:
                first_name = user.first_name or ""
                last_name = user.last_name or ""
                username = user.username or ""
                
                if username and not (first_name or last_name):
                    user_name = username
                else:
                    user_name = f"{first_name} {last_name}".strip()
                
                if not user_name:
                    user_name = f"User {user.user_id}"
            else:
                user_name = f"Unknown User {item.user_id}"
            
            result.append({
                "user_id": item.user_id,
                "name": user_name,
                "total_messages": item.total_messages,
                "tasks_created": item.total_tasks_created,
                "tasks_completed": item.total_tasks_completed,
                "avg_response_time": item.avg_response_time
            })
        return result
    finally:
        session.close()
async def get_user_chats(user_id=None):
    """
    Get all chats for a user or all chats if user_id is None
    
    Args:
        user_id (int, optional): The user ID to filter chats for. If None, returns all chats.
    
    Returns:
        list: List of chat objects with their details
    """
    session = SessionLocal()
    try:
        logger.debug(f"Getting chats for user {user_id if user_id else 'all users'}")
        
        # If user_id provided, get only chats where the user has messages
        if user_id:
            # Get all chat_ids where user has sent messages
            chat_ids_query = session.query(Message.chat_id).filter(
                Message.sender_id == user_id
            ).distinct()
            
            # Log the query for debugging
            logger.debug(f"Query for user's chat_ids: {str(chat_ids_query)}")
            
            # Execute the query
            chat_ids_result = chat_ids_query.all()
            chat_ids = [chat_id[0] for chat_id in chat_ids_result]
            
            logger.debug(f"Found {len(chat_ids)} chat_ids for user {user_id}: {chat_ids}")
            
            if not chat_ids:
                logger.warning(f"No chats found for user {user_id}")
                return []
            
            # Fetch all chats that exist in the database
            chats = session.query(Chat).filter(Chat.chat_id.in_(chat_ids)).all()
            
            # Check for any chat_ids that don't have corresponding Chat records
            existing_chat_ids = [chat.chat_id for chat in chats]
            missing_chat_ids = set(chat_ids) - set(existing_chat_ids)
            
            logger.debug(f"Missing chat records for chat_ids: {missing_chat_ids}")
            
            # Create placeholder Chat objects for missing chats
            for chat_id in missing_chat_ids:
                placeholder_chat = Chat(
                    chat_id=chat_id,
                    chat_name=f"Unknown Chat {chat_id}",
                    is_active=True,
                    last_summary_time=datetime.utcnow()
                )
                chats.append(placeholder_chat)
        else:
            # Get all chats
            chats = session.query(Chat).order_by(Chat.chat_name).all()
        
        # Get message counts for each chat
        result = []
        for chat in chats:
            # Count messages in this chat
            message_count = session.query(func.count(Message.id)).filter(
                Message.chat_id == chat.chat_id
            ).scalar() or 0
            
            # Get last message time
            last_message = session.query(Message).filter(
                Message.chat_id == chat.chat_id
            ).order_by(Message.timestamp.desc()).first()
            
            last_message_time = last_message.timestamp if last_message else None
            
            result.append({
                "id": chat.id if hasattr(chat, 'id') else None,
                "chat_id": chat.chat_id,
                "chat_name": chat.chat_name or f"Chat {chat.chat_id}",
                "is_active": chat.is_active,
                "last_summary_time": chat.last_summary_time,
                "linear_team_id": chat.linear_team_id if hasattr(chat, 'linear_team_id') else None,
                "message_count": message_count,
                "last_message_time": last_message_time
            })
        
        logger.debug(f"Retrieved {len(result)} chats")
        return result
    except Exception as e:
        logger.error(f"Error retrieving chats: {str(e)}", exc_info=True)
        return []  # Return empty list instead of raising exception
    finally:
        session.close()
async def execute_sql_query(sql_query: str):
    """
    Execute an arbitrary SQL query and return the results
    
    Args:
        sql_query: SQL query string to execute
        
    Returns:
        List of dictionaries with the query results
    """
    logger.info(f"Executing raw SQL query:")
    logger.info(sql_query)
    
    try:
        # Create a new session
        session = SessionLocal()
        
        # Wrap the query string in SQLAlchemy text() function
        sql_text = text(sql_query)
        
        # Execute the query directly
        result = session.execute(sql_text)
        
        # Convert result to a list of dictionaries
        columns = result.keys()
        rows = []
        
        for row in result:
            row_dict = {}
            for i, column in enumerate(columns):
                # Handle different data types appropriately
                value = row[i]
                if isinstance(value, datetime):
                    value = value.isoformat()
                row_dict[column] = value
            rows.append(row_dict)
        
        # Log the results (limited to avoid huge logs)
        if rows:
            row_count = len(rows)
            logger.info(f"Query returned {row_count} rows")
            if row_count > 0:
                # Log column names
                logger.info(f"Columns: {', '.join(columns)}")
                # Log first row as sample
                if row_count > 0:
                    logger.info(f"Sample row: {rows[0]}")
        else:
            logger.info("Query returned no results")
        
        session.close()
        return rows
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error executing SQL query: {error_msg}")
        logger.error(f"Query was: {sql_query}")
        return [{"error": error_msg}] 