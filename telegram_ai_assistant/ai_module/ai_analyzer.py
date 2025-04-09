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