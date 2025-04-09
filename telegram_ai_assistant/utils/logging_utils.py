import os
import logging
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DEFAULT_LOG_LEVEL = logging.INFO
DEBUG_LOG_LEVEL = logging.DEBUG
os.makedirs(LOG_DIR, exist_ok=True)
def setup_logger(name, log_file=None):
    """
    Set up a logger with both console and file handlers
    Args:
        name (str): Logger name
        log_file (str, optional): Log file path. If None, no file handler is added
    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(DEFAULT_LOG_LEVEL)
    formatter = logging.Formatter(LOG_FORMAT)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    if log_file:
        log_path = os.path.join(LOG_DIR, log_file)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
def setup_main_logger():
    """Set up the main application logger"""
    return setup_logger('telegram_ai_assistant', 'main.log')
def setup_bot_logger():
    """Set up the bot component logger"""
    return setup_logger('telegram_ai_assistant.bot', 'bot.log')
def setup_userbot_logger():
    """Set up the userbot component logger"""
    return setup_logger('telegram_ai_assistant.userbot', 'userbot.log')
def setup_ai_logger():
    """Set up the AI component logger"""
    return setup_logger('telegram_ai_assistant.ai', 'ai.log')
def setup_db_logger():
    """Set up the database component logger"""
    return setup_logger('telegram_ai_assistant.db', 'db.log')
def setup_linear_logger():
    """Set up the Linear integration logger"""
    return setup_logger('telegram_ai_assistant.linear', 'linear.log')
def setup_reminders_logger():
    """Set up the reminders component logger"""
    return setup_logger('telegram_ai_assistant.reminders', 'reminders.log')
def log_startup(app_name):
    """Log application startup"""
    logger = logging.getLogger('telegram_ai_assistant')
    logger.info("="*50)
    logger.info(f"{app_name} starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("-"*50)
def log_shutdown(app_name):
    """Log application shutdown"""
    logger = logging.getLogger('telegram_ai_assistant')
    logger.info("-"*50)
    logger.info(f"{app_name} shutting down at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*50)
def enable_debug_mode():
    """Enable debug logging for all loggers"""
    logging.getLogger().setLevel(DEBUG_LOG_LEVEL)
    for logger_name in [
        'telegram_ai_assistant',
        'telegram_ai_assistant.bot',
        'telegram_ai_assistant.userbot',
        'telegram_ai_assistant.ai',
        'telegram_ai_assistant.db',
        'telegram_ai_assistant.linear',
        'telegram_ai_assistant.reminders'
    ]:
        logging.getLogger(logger_name).setLevel(DEBUG_LOG_LEVEL)
    main_logger = logging.getLogger('telegram_ai_assistant')
    main_logger.debug("Debug logging enabled for all components") 