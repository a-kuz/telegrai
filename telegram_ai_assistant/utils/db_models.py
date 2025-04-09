from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_URI
Base = declarative_base()
class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False, unique=True)
    chat_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    last_summary_time = Column(DateTime, default=datetime.utcnow)
    linear_team_id = Column(String(50))
    messages = relationship("Message", back_populates="chat")
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255))
    last_name = Column(String(255))
    is_bot = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    messages = relationship("Message", back_populates="sender")
    tasks = relationship("Task", back_populates="assignee")
    unanswered_questions = relationship("UnansweredQuestion", back_populates="target_user")
class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, nullable=False)
    chat_id = Column(Integer, ForeignKey('chats.chat_id'))
    sender_id = Column(Integer, ForeignKey('users.user_id'))
    text = Column(Text)
    attachments = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_important = Column(Boolean, default=False)
    is_processed = Column(Boolean, default=False)
    category = Column(String(50))
    is_bot = Column(Boolean, default=False)
    chat = relationship("Chat", back_populates="messages")
    sender = relationship("User", back_populates="messages")
class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    linear_id = Column(String(50), unique=True)
    title = Column(String(255))
    description = Column(Text)
    status = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    due_date = Column(DateTime)
    assignee_id = Column(Integer, ForeignKey('users.user_id'))
    message_id = Column(Integer)
    chat_id = Column(Integer)
    assignee = relationship("User", back_populates="tasks")
class UnansweredQuestion(Base):
    __tablename__ = 'unanswered_questions'
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, nullable=False)
    chat_id = Column(Integer, nullable=False)
    target_user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    sender_id = Column(Integer, nullable=True)
    question = Column(Text)
    asked_at = Column(DateTime, default=datetime.utcnow)
    is_answered = Column(Boolean, default=False)
    answered_at = Column(DateTime, nullable=True)
    reminder_count = Column(Integer, default=0)
    is_bot = Column(Boolean, default=False)
    target_user = relationship("User", back_populates="unanswered_questions")
class TeamProductivity(Base):
    __tablename__ = 'team_productivity'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)
    tasks_created = Column(Integer, default=0)
    tasks_completed = Column(Integer, default=0)
    avg_response_time = Column(Integer)
def init_db():
    engine = create_engine(DB_URI)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()
if __name__ == "__main__":
    init_db() 