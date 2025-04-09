import sys
import os
import json
import asyncio
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import schedule

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from utils.logging_utils import bot_logger as logger
from utils.db_utils import session_scope, Task, Question, Reminder
from utils.config import BOT_TOKEN, ADMIN_USER_ID, REMINDER_INTERVAL, SUMMARY_HOUR
from ai_module.ai_summarizer import generate_daily_summary

# Setup logging
# Removed basic logging setup as we're now using the logger from logging_utils

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the command /start is issued."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    logger.info(f"User {username} (ID: {user_id}) started the bot")
    
    await update.message.reply_text(
        f"Hello, {update.effective_user.first_name}! I am your Telegram Assistant Bot.\n\n"
        f"I am here to help you manage tasks, questions, and reminders."
    )

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all tasks."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if str(user_id) != ADMIN_USER_ID:
        logger.warning(f"Unauthorized access attempt to /tasks by user {username} (ID: {user_id})")
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    
    logger.info(f"User {username} (ID: {user_id}) requested task list")
    
    with session_scope() as session:
        tasks = session.query(Task).order_by(Task.created_at.desc()).all()
        
        if not tasks:
            await update.message.reply_text("No tasks found.")
            return
        
        response = "📋 *Tasks:*\n\n"
        for i, task in enumerate(tasks, 1):
            status = "✅" if task.completed else "⏳"
            response += f"{i}. {status} *{task.title}*\n"
            if task.description:
                response += f"   _{task.description}_\n"
            response += f"   Created: {task.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
        
        # Add inline keyboard for task management
        keyboard = [
            [InlineKeyboardButton("Mark Task Complete", callback_data="complete_task")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(response, parse_mode="Markdown", reply_markup=reply_markup)
        logger.debug(f"Sent task list with {len(tasks)} tasks to user {username}")

async def questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all questions."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if str(user_id) != ADMIN_USER_ID:
        logger.warning(f"Unauthorized access attempt to /questions by user {username} (ID: {user_id})")
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    
    logger.info(f"User {username} (ID: {user_id}) requested question list")
    
    with session_scope() as session:
        questions = session.query(Question).order_by(Question.created_at.desc()).all()
        
        if not questions:
            await update.message.reply_text("No questions found.")
            return
        
        response = "❓ *Questions:*\n\n"
        for i, question in enumerate(questions, 1):
            status = "✅" if question.answered else "❓"
            response += f"{i}. {status} *{question.text}*\n"
            if question.answer:
                response += f"   Answer: _{question.answer}_\n"
            response += f"   Asked by: {question.sender_name} on {question.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
        
        await update.message.reply_text(response, parse_mode="Markdown")
        logger.debug(f"Sent question list with {len(questions)} questions to user {username}")

async def reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all reminders."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if str(user_id) != ADMIN_USER_ID:
        logger.warning(f"Unauthorized access attempt to /reminders by user {username} (ID: {user_id})")
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    
    logger.info(f"User {username} (ID: {user_id}) requested reminder list")
    
    with session_scope() as session:
        reminders = session.query(Reminder).order_by(Reminder.due_at.asc()).all()
        
        if not reminders:
            await update.message.reply_text("No reminders found.")
            return
        
        response = "⏰ *Reminders:*\n\n"
        for i, reminder in enumerate(reminders, 1):
            status = "🔄" if reminder.recurring else "⏰"
            response += f"{i}. {status} *{reminder.text}*\n"
            response += f"   Due: {reminder.due_at.strftime('%Y-%m-%d %H:%M')}\n"
            if reminder.recurring:
                response += f"   Recurring: Every {reminder.interval} seconds\n"
            response += "\n"
        
        # Add inline keyboard for reminder management
        keyboard = [
            [InlineKeyboardButton("Delete Reminder", callback_data="delete_reminder")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(response, parse_mode="Markdown", reply_markup=reply_markup)
        logger.debug(f"Sent reminder list with {len(reminders)} reminders to user {username}")

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new reminder."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if str(user_id) != ADMIN_USER_ID:
        logger.warning(f"Unauthorized access attempt to /remind by user {username} (ID: {user_id})")
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    
    # Check if there are arguments
    if not context.args:
        await update.message.reply_text(
            "Please provide the reminder text and optional due time.\n"
            "Example: /remind Call John tomorrow at 2pm"
        )
        return
    
    reminder_text = ' '.join(context.args)
    logger.info(f"User {username} created reminder: {reminder_text}")
    
    # For simplicity, just create a reminder due in the default interval
    with session_scope() as session:
        now = datetime.now()
        reminder = Reminder(
            text=reminder_text,
            due_at=now.timestamp() + REMINDER_INTERVAL,
            recurring=False,
            interval=0
        )
        session.add(reminder)
    
    await update.message.reply_text(f"Reminder set: {reminder_text}")
    logger.info(f"Reminder created by user {username}: {reminder_text}")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send a daily summary."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if str(user_id) != ADMIN_USER_ID:
        logger.warning(f"Unauthorized access attempt to /summary by user {username} (ID: {user_id})")
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    
    logger.info(f"User {username} (ID: {user_id}) requested summary")
    
    # Generate the summary
    summary_text = await generate_daily_summary()
    
    # Send the summary
    await update.message.reply_text(summary_text, parse_mode="Markdown")
    logger.info(f"Sent summary to user {username}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks from inline keyboards."""
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username
    
    if str(user_id) != ADMIN_USER_ID:
        logger.warning(f"Unauthorized button press by user {username} (ID: {user_id})")
        await query.answer("You are not authorized to use this button.")
        return
    
    await query.answer()
    
    callback_data = query.data
    logger.debug(f"Button pressed by user {username}: {callback_data}")
    
    # Handle different button actions
    if callback_data == "complete_task":
        # Ask which task to complete
        await query.edit_message_text("Please send the number of the task to mark as complete.")
    elif callback_data == "delete_reminder":
        # Ask which reminder to delete
        await query.edit_message_text("Please send the number of the reminder to delete.")
    
    logger.debug(f"Handled button press for {callback_data}")

async def check_reminders(context):
    """Check for due reminders and send notifications."""
    logger.debug("Checking for due reminders")
    
    now = datetime.now().timestamp()
    with session_scope() as session:
        due_reminders = session.query(Reminder).filter(Reminder.due_at <= now).all()
        
        for reminder in due_reminders:
            # Send notification to admin
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text=f"⏰ *Reminder:* {reminder.text}",
                    parse_mode="Markdown"
                )
                logger.info(f"Sent reminder notification: {reminder.text}")
                
                # Handle recurring reminders
                if reminder.recurring and reminder.interval > 0:
                    # Update due time to next occurrence
                    reminder.due_at = now + reminder.interval
                    logger.debug(f"Updated recurring reminder to next occurrence: {reminder.text}")
                else:
                    # Delete non-recurring reminders
                    session.delete(reminder)
                    logger.debug(f"Deleted completed reminder: {reminder.text}")
            except Exception as e:
                logger.error(f"Error sending reminder notification: {str(e)}")

async def generate_daily_summary():
    """Generate a daily summary of activities."""
    logger.info("Generating daily summary")
    
    with session_scope() as session:
        # Get today's tasks
        today = datetime.now().date()
        tasks = session.query(Task).filter(
            Task.created_at >= today
        ).all()
        
        # Get today's questions
        questions = session.query(Question).filter(
            Question.created_at >= today
        ).all()
        
        # Get upcoming reminders
        reminders = session.query(Reminder).order_by(Reminder.due_at.asc()).limit(5).all()
        
        # Build summary text
        summary = "📊 *Daily Summary*\n\n"
        
        # Tasks summary
        summary += f"*Tasks Today:* {len(tasks)}\n"
        completed = sum(1 for t in tasks if t.completed)
        summary += f"- Completed: {completed}\n"
        summary += f"- Pending: {len(tasks) - completed}\n\n"
        
        # Questions summary
        summary += f"*Questions Today:* {len(questions)}\n"
        answered = sum(1 for q in questions if q.answered)
        summary += f"- Answered: {answered}\n"
        summary += f"- Pending: {len(questions) - answered}\n\n"
        
        # Upcoming reminders
        summary += "*Upcoming Reminders:*\n"
        if reminders:
            for i, reminder in enumerate(reminders, 1):
                due_date = datetime.fromtimestamp(reminder.due_at).strftime('%Y-%m-%d %H:%M')
                summary += f"{i}. {reminder.text} (Due: {due_date})\n"
        else:
            summary += "No upcoming reminders.\n"
    
    logger.debug("Daily summary generated successfully")
    return summary

async def daily_summary_job(context):
    """Send the daily summary at the scheduled time."""
    logger.info("Sending scheduled daily summary")
    
    summary_text = await generate_daily_summary()
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=summary_text,
            parse_mode="Markdown"
        )
        logger.info("Daily summary sent successfully")
    except Exception as e:
        logger.error(f"Error sending daily summary: {str(e)}")

def run_scheduler(application):
    """Set up and run the scheduler for recurring tasks."""
    logger.info("Setting up scheduler for recurring tasks")
    
    # Check for reminders every minute
    job_queue = application.job_queue
    job_queue.run_repeating(check_reminders, interval=60, first=10)
    logger.debug("Scheduled reminder check job (every 60 seconds)")
    
    # Schedule daily summary
    summary_time = f"{SUMMARY_HOUR:02d}:00:00"
    job_queue.run_daily(daily_summary_job, time=datetime.strptime(summary_time, "%H:%M:%S").time())
    logger.debug(f"Scheduled daily summary job at {summary_time}")

def main():
    """Start the bot."""
    logger.info("Starting Telegram bot")
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tasks", tasks))
    application.add_handler(CommandHandler("questions", questions))
    application.add_handler(CommandHandler("reminders", reminders))
    application.add_handler(CommandHandler("remind", remind))
    application.add_handler(CommandHandler("summary", summary))
    logger.debug("Command handlers registered")
    
    # Add callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(button_handler))
    logger.debug("Callback query handler registered")
    
    # Set up the scheduler
    run_scheduler(application)
    
    # Start the Bot
    application.run_polling(drop_pending_updates=True)
    logger.info("Bot polling started")

if __name__ == "__main__":
    main() 