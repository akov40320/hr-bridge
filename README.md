# HR Bridge (Recruiting Bridge)

Интеграционный сервис для HR: связывает HeadHunter и Avito с AmoCRM и Telegram.
Принимает вебхуки, синхронизирует статусы и сообщения, выполняет фоновые задачи
через RabbitMQ. HTTP API — на FastAPI.

## Что умеет

- Интеграции: HeadHunter, Avito, AmoCRM, AmoChats, Telegram (два бота: master/operator).
- Вебхуки: прием входящих событий и авто-регистрация (HH, Telegram).
- Очереди: публикация и обработка задач через RabbitMQ (retry/DLQ).
- Фоновые джобы: обновление OAuth‑токенов, очистка дедуп‑таблицы, повтор задач.
- Метрики и здоровье: `/metrics`, `/health`.

## Стек

- Backend: FastAPI, httpx, aiogram, APScheduler.
- Очереди: RabbitMQ (aio‑пика).
- БД: Postgres (SQLAlchemy async) + Alembic. Для разработки по умолчанию доступна SQLite in‑memory.
- Контейнеры: Docker/Docker Compose.

## Быстрый старт (Docker)

1) Создайте файл `.env` и заполните ключевые переменные (см. пример ниже).
2) Поднимите локальный стек (Postgres + RabbitMQ + API/воркеры):

   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d

3) Проверка:
   - API: http://localhost:8000
   - RabbitMQ UI: http://localhost:15672 (guest/guest)
   - Postgres: localhost:5432 (user: app, password: app, db: app)

Подробности: docs/DOCKER.md

## Запуск без Docker

- Установите зависимости:

  python -m venv .venv && .\.venv\Scripts\activate  # Windows
  pip install -r requirements.txt

- Запустите API (по умолчанию SQLite in‑memory, без персистентности):

  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

- Отдельные процессы:
  - Воркер: python -u -m app.services.worker_rmq
  - Планировщик: python -u -m app.services.scheduler

Для персистентности укажите `DATABASE_URL` (Postgres) и `RABBITMQ_URL`.

## Переменные окружения (основные)

Минимальный набор для запуска и интеграций (значения примеры, замените на реальные):

```
# Доступ к админ‑эндпоинтам
ADMIN_TOKEN=super-secret

# БД и очереди
DATABASE_URL=postgresql+asyncpg://app:app@postgres:5432/app
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/

# AmoCRM OAuth
AMO_BASE_URL=https://your.amocrm.ru
AMO_CLIENT_ID=...
AMO_CLIENT_SECRET=...
AMO_REDIRECT_URI=https://your.app/oauth/amo/callback

# Настройки воронок/стадий (обязательны)
AMO_PIPELINE_ID_MASTER=...
AMO_STAGE_ID_MASTER_NEW=...
AMO_STAGE_ID_MASTER_SURVEY=...
AMO_PIPELINE_ID_OPERATOR=...
AMO_STAGE_ID_OPERATOR_NEW=...
AMO_STAGE_ID_OPERATOR_SURVEY=...

# HeadHunter OAuth
HH_CLIENT_ID=...
HH_CLIENT_SECRET=...
HH_REDIRECT_URI=https://your.app/oauth/hh/callback
HH_USER_AGENT=your-app/1.0

# Avito OAuth
AVITO_CLIENT_ID=...
AVITO_CLIENT_SECRET=...
AVITO_REDIRECT_URI=https://your.app/oauth/avito/callback
AVITO_AUTHORIZE_URL=https://avito.ru/oauth
AVITO_TOKEN_URL=https://api.avito.ru/token
AVITO_SCOPE=messenger.read,messenger.write

# Telegram боты и вебхуки
TELEGRAM_MASTER_BOT_TOKEN=...
TELEGRAM_OPERATOR_BOT_TOKEN=...
TELEGRAM_WEBHOOK_BASE=https://your.app
TELEGRAM_WEBHOOK_SECRET=optional-shared-secret
TELEGRAM_WEBHOOK_MODE=true

# AmoChats (если включено)
AMOCHATS_ENABLED=true
AMO_CHATS_SCOPE_ID=...
AMO_CHATS_SECRET=...
AMO_CHATS_CHANNEL_ID=...
AMO_CHATS_ACCOUNT_ID=...
AMO_CHATS_SENDER_USER_AMOJO_ID=...

# Вебхуки HH/Avito (базовые URL для авто‑регистрации/провайдера)
HH_WEBHOOK_URL=https://your.app/webhooks/hh
HH_WEBHOOK_EVENTS=negotiation.created,negotiation.status_changed
AVITO_WEBHOOK_URL=https://your.app/webhooks/avito
AVITO_WEBHOOK_SECRET=change-me

# Прочее
HH_AUTOFILL_INTERVAL_HOURS=0
```

Полный список и значения по умолчанию смотрите в `app/core/config.py`.

## Процессы и очереди

- `web` (API): FastAPI приложение, точки входа и вебхуки. См. main.py
- `worker`: обработчик фоновых задач из RMQ. См. app/services/worker_rmq.py
- `scheduler`: периодические задачи (обновление токенов, cleanup, retry). См. app/services/scheduler.py
- Очереди: основной, retry и DLQ объявляются автоматически. Имена управляются переменными `RMQ_*`.

## OAuth и вебхуки

- Старт OAuth:
  - AmoCRM: GET `/oauth/amo/start`
  - HeadHunter: GET `/oauth/hh/start`
  - Avito: GET `/oauth/avito/start`
  Настройте redirect URI у провайдеров на соответствующие `/oauth/*/callback`.

- Входящие вебхуки:
  - HH: POST `/webhooks/hh/{owner_id}` (авторегистрация через HH API при наличии `HH_WEBHOOK_URL`).
  - Avito: POST `/webhooks/avito` (проверка HMAC‑подписи, заголовок `X-Avito-Signature`).
  - Telegram: POST `/tg/webhook/master`, `/tg/webhook/operator` (секрет в `X-Telegram-Bot-Api-Secret-Token`).
  - AmoChats: POST `/webhooks/amo-chats/in/{scope_id}` (HMAC‑SHA1, заголовок `X-Signature`).

## Админ и диагностика

- Хедер авторизации: `Authorization: Bearer <ADMIN_TOKEN>` или `X-Admin-Token: <ADMIN_TOKEN>`.
- Эндпоинты:
  - `/health` — статус сервиса и токенов.
  - `/metrics` — Prometheus‑метрики.
  - `/admin/hh-mapping` GET/PUT — просмотреть/заменить маппинг статусов HH.
  - `/admin/rmq-test` — отправить тестовое сообщение в очередь.
  - `/admin/dedup-clean?hours=72` — очистка дедуп‑таблицы.
  - `/admin/hh-states` — справочник статусов HH (по токену/owner).
  - `/admin/hh-autofill` — поставить задачу авто‑заполнения маппинга HH.
  - `/admin/tg/*` — управление вебхуками Telegram (set/delete/info).

## База данных и миграции

- Модели: app/db/models.py
- Инициализация для разработки: SQLite in‑memory (создается на старте).
- Прод: Alembic миграции (`alembic upgrade head`). В локальном compose миграции запускаются отдельным сервисом `migrate`.

## Тесты

Запуск тестов (локально):

pytest -q

## Текущее размещение (staging)

- API: Render — <RENDER_API_URL>
- Очередь: RabbitMQ (CloudAMQP) — <CLOUDAMQP_INSTANCE_URL>
- База данных: PostgreSQL (Neon) — <NEON_CONNECTION_STRING>
- Фоновые задачи: `worker` и `scheduler` запущены в Docker и подключены к тем же CloudAMQP/Neon.

Схема работы: API принимает запросы/вебхуки → публикует задачи в RabbitMQ → `worker` обрабатывает, `scheduler` планирует периодические задачи → данные хранятся в БД на Neon.

Для on‑prem развёртывания у заказчика см. `docs/DOCKER.md` (Compose для Postgres, RabbitMQ, API, worker, scheduler).

## Развёртывание

- API процесс: `web: gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:$PORT` (Procfile)
- Воркеры/планировщик — как отдельные процессы/сервисы с теми же переменными окружения.

---

Подсказки по коду:
- Точки входа: `main.py`, воркер `app/services/worker_rmq.py`, планировщик `app/services/scheduler.py`.
- Настройки и обязательные переменные: `app/core/config.py`.
- Регистрация HH вебхуков: `app/api/hh_webhooks.py`, входящие: `app/api/hh_incoming.py`.
- Вебхуки Avito: `app/api/avito_webhooks.py` (регистрация), `app/api/avito_incoming.py` (прием).
- Интеграция AmoChats: `app/api/api_amochats.py`.
