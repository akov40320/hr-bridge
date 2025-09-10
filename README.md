# hr-bridge

[![CI](https://github.com/OWNER/hr-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/hr-bridge/actions/workflows/ci.yml)

Сервис-посредник между Telegram и площадками по подбору персонала (AmoCRM, HH, Avito).
Он предоставляет HTTP API, фонового воркера для обработки задач из очереди и
Telegram-ботов для взаимодействия с кандидатами.

## Архитектура

- **API** — FastAPI-приложение, принимающее webhooks от внешних сервисов и
  предоставляющее административные эндпоинты.
- **Очередь** — задачи публикуются в RabbitMQ (основная, retry и DLQ-очереди).
- **Worker** — отдельный процесс, считывающий задачи из очереди и выполняющий
  операции с AmoCRM/HH/Avito.
- **Telegram-боты** — два бота (master и operator) регистрируются через
  webhooks и используются для общения с соискателями.

## Переменные окружения

### RabbitMQ
- `RABBITMQ_URL` — URL подключения к брокеру.
- `RMQ_EXCHANGE` — имя обменника.
- `RMQ_TASK_QUEUE` — основная очередь задач.
- `RMQ_RETRY_QUEUE` — очередь повторной обработки.
- `RMQ_DLQ_QUEUE` — очередь ошибок (dead-letter).
- `RMQ_RETRY_TTL_MS` — задержка перед повторной публикацией, мс.
- `RMQ_ENABLE_CONSUMER` — включение потребителя очереди.
- `RMQ_CONSUMERS` — число воркеров.
- `RMQ_PREFETCH` — количество сообщений, запрашиваемых заранее.
- `WORKER_MAX_ATTEMPTS` — максимальное число попыток перед отправкой в DLQ.

### База данных
- `DATABASE_URL` — строка подключения к Postgres/SQLite.

### AmoCRM
- `AMO_BASE_URL`, `AMO_CLIENT_ID`, `AMO_CLIENT_SECRET`, `AMO_REDIRECT_URI` — параметры OAuth.
- `AMO_ACCESS_TOKEN`, `AMO_REFRESH_TOKEN`, `AMO_EXPIRES_AT` — начальные токены.
- `AMO_PIPELINE_ID_MASTER`, `AMO_STAGE_ID_MASTER_NEW`, `AMO_STAGE_ID_MASTER_SURVEY` — воронка и стадии мастера.
- `AMO_PIPELINE_ID_OPERATOR`, `AMO_STAGE_ID_OPERATOR_NEW`, `AMO_STAGE_ID_OPERATOR_SURVEY` — воронка и стадии оператора.
- `AMO_TAG_WENT_TO_BOT`, `AMO_TAG_SURVEY_DONE` — теги для сделок.
- `ROUTING_KEYWORD_MASTER`, `ROUTING_KEYWORD_OPERATOR` — ключевые слова маршрутизации.

### HeadHunter (HH)
- `HH_CLIENT_ID`, `HH_CLIENT_SECRET`, `HH_REDIRECT_URI` — OAuth.
- `HH_ACCESS_TOKEN`, `HH_REFRESH_TOKEN`, `HH_EXPIRES_AT` — токены.
- `HH_API_BASE`, `HH_SET_STATE_PATH`, `HH_TOKEN_URL` — адреса API.
- `HH_USER_AGENT` — user-agent запросов.
- `HH_SYNC_ENABLED` — включение синхронизации.
- `HH_WEBHOOK_URL`, `HH_WEBHOOK_EVENTS` — настройка вебхуков HH.

### Avito
- `AVITO_CLIENT_ID`, `AVITO_CLIENT_SECRET`, `AVITO_REDIRECT_URI` — OAuth.
- `AVITO_ACCESS_TOKEN`, `AVITO_REFRESH_TOKEN`, `AVITO_EXPIRES_AT` — токены.
- `AVITO_AUTHORIZE_URL`, `AVITO_TOKEN_URL`, `AVITO_SCOPE` — параметры авторизации.
- `AVITO_API_BASE`, `AVITO_SEND_MESSAGE_PATH`, `AVITO_MARK_READ_PATH` — API.
- `AVITO_WEBHOOK_URL`, `AVITO_MESSENGER_EVENTS`, `AVITO_WEBHOOK_SECRET`, `AVITO_SIGNATURE_HEADER` — вебхуки.
- `AVITO_SYNC_ENABLED`, `AVITO_MARK_READ_ON_STAGE_CHANGE` — поведение.

### Telegram
- `TELEGRAM_MASTER_BOT_TOKEN`, `TELEGRAM_MASTER_BOT_USERNAME` — мастер-бот.
- `TELEGRAM_OPERATOR_BOT_TOKEN`, `TELEGRAM_OPERATOR_BOT_USERNAME` — оператор-бот.
- `TELEGRAM_WEBHOOK_SECRET` — секрет для вебхуков.
- `TELEGRAM_WEBHOOK_BASE` — базовый URL вебхуков.
- `TELEGRAM_WEBHOOK_MODE` — режим вебхуков (true) или polling.

### AmoChats
- `AMO_CHATS_BASE`, `AMO_CHATS_SCOPE_ID`, `AMO_CHATS_SECRET` — параметры подключения.
- `AMO_CHATS_CHANNEL_ID`, `AMO_CHATS_ACCOUNT_ID`, `AMO_CHATS_SENDER_USER_AMOJO_ID` — идентификаторы аккаунта.
- `AMOCHATS_ENABLED`, `AMO_CHATS_SENDER_NAME`, `AMO_CHATS_AUTOCONNECT` — управление подключением.
- `AMOCHATS_INCOMING_SECRET` — проверка входящих запросов.

### Прочее
- `ADMIN_TOKEN` — токен доступа к административным эндпоинтам.
- `AMO_CF_LEAD_CITY_ID`, `AMO_CF_LEAD_VACANCY_TITLE_ID`, `AMO_CF_LEAD_APPLICANT_PHONE_ID`,
  `AMO_CF_LEAD_APPLICANT_NAME_ID`, `AMO_CF_LEAD_APPLICANT_EMAIL_ID`, `AMO_CF_REFUSAL_REASON_ID` — кастомные поля AmoCRM.

## Запуск через Docker Compose

1. Создайте файл `.env` с переменными окружения.
2. Выполните миграции БД:
   ```sh
   docker-compose run --rm api alembic upgrade head
   ```
3. Соберите и запустите сервисы:
   ```sh
   docker-compose up --build
   ```

## Первоначальная настройка токенов

При первом запуске сервис считывает токены AmoCRM, HH и Avito из переменных
окружения (`*_ACCESS_TOKEN`, `*_REFRESH_TOKEN`, `*_EXPIRES_AT`) и сохраняет их
в базу данных. В дальнейшем токены можно обновлять через административные
эндпоинты.
