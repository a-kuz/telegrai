import sys
import os
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, func, and_
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
            logger.info(f"Creating new user record for user_id {sender_id} ({sender_name})")
            user = User(user_id=sender_id, first_name=first_name, last_name=last_name, is_bot=is_bot)
            session.add(user)
            session.flush()
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
    session = SessionLocal()
    try:
        logger.debug(f"Retrieving recent messages for chat {chat_id}, past {hours} hours, limit {limit}")
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        messages = session.query(Message).filter(
            Message.chat_id == chat_id,
            Message.timestamp >= cutoff_time
        ).order_by(Message.timestamp.desc()).limit(limit).all()
        result = [
            {
                "id": msg.id,
                "message_id": msg.message_id,
                "sender_id": msg.sender_id,
                "sender_name": f"{msg.sender.first_name} {msg.sender.last_name}".strip() if msg.sender else "Unknown",
                "text": msg.text,
                "timestamp": msg.timestamp,
                "category": msg.category,
                "is_important": msg.is_important
            }
            for msg in messages
        ]
        logger.debug(f"Retrieved {len(result)} messages for chat {chat_id}")
        return result
    except Exception as e:
        logger.error(f"Error retrieving messages for chat {chat_id}: {str(e)}", exc_info=True)
        raise e
    finally:
        session.close()
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
            user_name = f"{user.first_name} {user.last_name}".strip() if user else "Unknown"
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