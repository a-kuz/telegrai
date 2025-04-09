from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="telegram_ai_assistant",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="An AI-powered Telegram assistant for work chats",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/telegram-ai-assistant",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        "telethon>=1.28.5",
        "aiogram>=3.0.0",
        "aiosqlite>=0.19.0",
        "openai>=1.3.0",
        "requests>=2.28.2",
        "python-dotenv>=1.0.0",
        "httpx>=0.24.1",
        "pydantic>=2.0.0",
        "SQLAlchemy>=2.0.0",
        "asyncpg>=0.27.0",
        "aiohttp>=3.8.4",
        "pytz>=2023.3",
        "websockets>=11.0.3",
        "beautifulsoup4>=4.11.2"
    ],
    entry_points={
        "console_scripts": [
            "telegram-ai-assistant=telegram_ai_assistant.main:main",
        ],
    },
) 