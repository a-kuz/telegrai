# Telegram AI Assistant

<div align="center">
  <img src="https://i.ibb.co/k2nt5R1z/14ca1ab027ab74ee7b020aef9ca24eb3807cd270b59a11de8cb919f830507fae.png" alt="Telegram AI Assistant Logo" width="200"/>

  
  <br>
  <h3>Умный AI-ассистент для Telegram</h3>
  <p>Мониторит чаты, отслеживает задачи, напоминает о вопросах и создает сводки</p>
</div>

## 📱 Обзор

Telegram AI Assistant - это мощный инструмент для продуктивной работы с Telegram чатами. Он использует искусственный интеллект для анализа сообщений, отслеживания задач, вопросов и важной информации, что позволяет не упустить ничего важного в потоке сообщений.

## ✨ Основные возможности

- **Пассивный мониторинг чатов** - читает сообщения во всех или выбранных чатах без отправки сообщений от вашего имени
- **AI-анализ контента** - использует OpenAI GPT-4o для понимания контекста сообщений, изображений и ссылок
- **Управление задачами** - автоматически обнаруживает задачи в сообщениях и создает их в Linear
- **Отслеживание вопросов** - выявляет вопросы, адресованные вам, и напоминает о неотвеченных
- **Автоматические сводки** - генерирует краткие отчеты о обсуждениях в чатах
- **Аналитика активности** - отслеживает вовлеченность и активность команды
- **Двухкомпонентная архитектура**:
  - Userbot (клиент пользователя) для чтения сообщений из вашего аккаунта
  - Бот для взаимодействия с вами и отображения результатов

## 🏗️ Архитектура системы

![Архитектура](https://i.imgur.com/jUw5XTl.png)

Система состоит из нескольких компонентов:

1. **Telegram Userbot** - использует Telethon для чтения сообщений из вашего аккаунта
2. **AI-модуль** - анализирует содержимое сообщений с помощью OpenAI GPT-4o
3. **Linear-интеграция** - управляет задачами в трекере Linear
4. **Telegram Бот** - предоставляет интерфейс для взаимодействия с системой
5. **База данных** - хранит сообщения, задачи и другие данные

## 📊 Структура базы данных

Система использует SQLite для хранения всех данных со следующими таблицами:

### 1. Users (Пользователи)
- `id` - Первичный ключ
- `user_id` - ID пользователя в Telegram
- `username` - Имя пользователя в Telegram
- `first_name` - Имя пользователя
- `last_name` - Фамилия пользователя
- `is_bot` - Является ли ботом
- `created_at` - Когда пользователь был добавлен в БД

### 2. Messages (Сообщения)
- `id` - Первичный ключ
- `message_id` - ID сообщения в Telegram
- `chat_id` - ID чата, где было отправлено сообщение
- `sender_id` - ID пользователя, отправившего сообщение
- `text` - Содержимое сообщения
- `attachments` - JSON-строка с вложениями
- `timestamp` - Когда сообщение было отправлено
- `is_important` - Флаг важности
- `is_processed` - Флаг обработки
- `category` - Категория сообщения
- `is_bot` - Отправлено ли ботом

### 3. Chats (Чаты)
- `id` - Первичный ключ
- `chat_id` - ID чата в Telegram
- `chat_name` - Название чата
- `is_active` - Статус активности
- `last_summary_time` - Время последней сводки
- `linear_team_id` - ID связанной команды в Linear

### 4. Tasks (Задачи)
- `id` - Первичный ключ
- `linear_id` - ID задачи в Linear
- `title` - Заголовок задачи
- `description` - Описание задачи
- `status` - Статус задачи
- `created_at` - Время создания
- `due_date` - Срок выполнения
- `assignee_id` - ID назначенного пользователя
- `message_id` - ID исходного сообщения
- `chat_id` - ID исходного чата

### 5. Unanswered Questions (Неотвеченные вопросы)
- `id` - Первичный ключ
- `message_id` - ID сообщения с вопросом
- `chat_id` - Чат, где был задан вопрос
- `target_user_id` - Пользователь, который должен ответить
- `sender_id` - Пользователь, задавший вопрос
- `question` - Текст вопроса
- `asked_at` - Когда был задан
- `is_answered` - Статус ответа
- `answered_at` - Когда был дан ответ
- `reminder_count` - Количество напоминаний
- `last_reminder_at` - Время последнего напоминания
- `is_bot` - От бота ли вопрос

### 6. Team Productivity (Продуктивность команды)
- `id` - Первичный ключ
- `user_id` - ID пользователя
- `date` - Дата записи
- `message_count` - Количество сообщений
- `tasks_created` - Создано задач
- `tasks_completed` - Выполнено задач
- `avg_response_time` - Среднее время ответа

## 📝 Классификация сообщений

ИИ анализирует каждое сообщение и классифицирует его по разным категориям:

### Категории сообщений
- **Вопрос** - Сообщение содержит вопрос, адресованный кому-то
- **Задача** - Сообщение описывает работу, которую нужно выполнить
- **Обновление статуса** - Сообщение предоставляет обновление по текущей работе
- **Общее обсуждение** - Обычный разговор
- **Ошибка** - Сообщение не удалось правильно проанализировать

### Анализ намерения сообщения
Система оценивает сообщения по трем измерениям:
1. **Запрос на создание задачи** (1-10) - Насколько явно оно просит создать задачу
2. **Кандидат в задачи** (1-10) - Насколько подходит для преобразования в задачу
3. **Запрос к базе данных** (1-10) - Насколько вероятно, что требуется информация из базы данных

### Важные флаги
- **is_important** - Сообщения, требующие срочного внимания
- **is_question** - Сообщения, содержащие вопросы
- **has_task** - Сообщения, описывающие задачи

### Условия для напоминаний о вопросах
Напоминания отправляются только когда:
- Администратор напрямую упоминается/тегается в сообщении
- Кто-то отвечает на сообщение администратора
- Отфильтрованы сообщения из каналов и комментарии к постам каналов

## 🧩 Примеры использования

### Мониторинг чатов

Ассистент может мониторить все ваши чаты или только выбранные:

```
# Мониторинг всех чатов
MONITORED_CHATS=[]

# Мониторинг конкретных чатов
MONITORED_CHATS=[-100123456789, -100987654321]
```

### Команды бота

![Примеры команд бота](https://i.imgur.com/bQVyZIw.png)

Бот поддерживает следующие команды:

- `/start` - Инициализация бота
- `/help` - Показать доступные команды
- `/summary [chat_name]` - Получить сводку последних разговоров (опционально из конкретного чата)
- `/tasks` - Показать ожидающие задачи из Linear
- `/reminders` - Проверить неотвеченные вопросы
- `/teamreport` - Посмотреть отчет о продуктивности команды
- `/createtask` - Вручную создать новую задачу в Linear

### Пример получения сводки 

```
🤖 @assistant_akuz3_bot

/summary

📊 Summary for All Chats
Period: Last 24 hours

Main topics discussed:
1. Product roadmap for Q3
2. Design review for homepage update
3. Bug fixes for authentication system

Key updates:
- Maria shared the new marketing plan
- Alex fixed the login issue
- Team agreed to postpone the API update

Questions for you:
1. "Can you review the latest pull request?"
2. "What do you think about the new color scheme?"

Tasks identified:
- Implement user settings page by Friday
- Schedule a meeting with the client next week
```

### Пример отслеживания вопросов

```
🤖 @assistant_akuz3_bot

/reminders

❓ Unanswered Questions

Question: Could you share your thoughts on the new landing page design?
Asked: 2 hours ago
Reminder count: 1

[Respond] [Ignore]
```

### Пример автоматического обнаружения задач

```
🤖 @assistant_akuz3_bot

📋 Potential Task Detected

Title: Update API documentation for v2.0
Description: Need to update the API docs to reflect the new endpoints and parameters added in version 2.0
Assignee: Not specified
Due Date: Next Friday

From chat: Dev Team

[Create Task] [Ignore]
```

## 🛠️ Требования

- Python 3.8+
- API-ключи Telegram (из [my.telegram.org/apps](https://my.telegram.org/apps))
- Токен бота Telegram (от [@BotFather](https://t.me/BotFather))
- OpenAI API ключ с доступом к GPT-4o
- Linear API ключ (опционально, для интеграции с задачами)

## 📦 Установка

1. Клонировать репозиторий:

```bash
git clone https://github.com/yourusername/telegram-ai-assistant.git
cd telegram-ai-assistant
```

2. Установить необходимые пакеты:

```bash
pip install -r requirements.txt
```

3. Создать файл `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

4. Отредактировать файл `.env` с вашими учетными данными.

5. Инициализировать базу данных:

```bash
python -m telegram_ai_assistant.utils.db_models
```

## 🚀 Запуск

### Запуск с помощью screen для работы в фоновом режиме

```bash
# Запуск userbot (чтение сообщений)
screen -S telegram_assistant -d -m bash -c "cd /path/to/telegram_ai_assistant && source venv/bin/activate && python -m telegram_ai_assistant.main --mode userbot"

# Запуск бота (интерфейс взаимодействия)
screen -S telegram_bot -d -m bash -c "cd /path/to/telegram_ai_assistant && source venv/bin/activate && python -m telegram_ai_assistant.main --mode bot"
```

### Управление screen-сессиями

```bash
# Просмотр списка запущенных сессий
screen -ls

# Подключение к сессии
screen -r telegram_assistant

# Отключение от сессии (без остановки)
# Нажмите Ctrl+A, затем D

# Завершение сессии
screen -S telegram_assistant -X quit
```

## 🔧 Настройка

### Настройка переменных окружения (.env)

```
# Telegram API credentials
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

# Telegram Bot token
BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ

# Session name for user client
USERBOT_SESSION=user_session

# Chat IDs to monitor (пустой массив для мониторинга всех чатов)
MONITORED_CHATS=[]

# OpenAI API key
OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890

# OpenAI model
OPENAI_MODEL=gpt-4o

# Linear API key
LINEAR_API_KEY=lin_abcdefghijklmnopqrstuvwxyz

# Linear team mapping
LINEAR_TEAM_MAPPING={"default": "TEAM_NAME"}

# Admin user ID (your Telegram user ID)
ADMIN_USER_ID=1234567890
```

### Поиск ID чатов

Используйте утилиту для получения ID чатов:

```bash
python -m telegram_ai_assistant.utils.get_chat_ids
```

## 📋 Часто задаваемые вопросы

### Как узнать мой Telegram User ID?
Отправьте сообщение боту [@userinfobot](https://t.me/userinfobot) в Telegram

### Будут ли видны другим пользователям действия ассистента?
Нет, ассистент только читает сообщения с помощью userbot-клиента и не выполняет никаких видимых действий в чатах

### Безопасно ли использовать ассистента с моим Telegram-аккаунтом?
Да, если использовать его в рамках личного использования. Однако злоупотребление API Telegram может привести к ограничениям аккаунта

### Что делать, если другие клиенты Telegram разлогиниваются?
Это может происходить из-за подозрительной активности. Используйте ассистента умеренно и убедитесь, что в коде userbot-клиента установлены правильные параметры device_model, system_version и app_version

## 🛡️ Безопасность

- Userbot имеет доступ ко всем сообщениям в мониторируемых чатах
- Учетные данные хранятся в файле .env
- Данные хранятся в локальной базе данных
- Убедитесь, что сервер защищен и доступ ограничен
- Соблюдайте конфиденциальность и нормы защиты данных

## 📄 Лицензия

MIT License

## ⚠️ Отказ от ответственности

Этот проект не связан с Telegram, OpenAI или Linear.
Функциональность userbot использует API Telegram в соответствии с их условиями использования для личного использования, но имейте в виду, что неправильное использование может привести к ограничениям аккаунта. 