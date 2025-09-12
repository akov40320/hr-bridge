Docker: run locally and with managed services

Local full stack (API + worker + scheduler + Postgres + RabbitMQ)

1) Copy `.env.example` to `.env` and fill required values (`ADMIN_TOKEN`, Amo/HH/Avito, Telegram, etc.).
2) Start stack:

   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d

3) Endpoints:
   - API: http://localhost:8000
   - RabbitMQ UI: http://localhost:15672 (guest/guest)
   - Postgres: localhost:5432 (user: app, password: app, db: app)

Migrations: `docker-compose.local.yml` contains a one-shot `migrate` service that runs `alembic upgrade head` before the API starts.

Remote-managed mode (Neon + CloudAMQP)

- Set `DATABASE_URL` and `RABBITMQ_URL` in `.env` to your Neon/CloudAMQP URLs.
- Start only app services locally if needed:

  docker compose up -d worker scheduler

- Deploy the API separately (e.g. Render) pointing to the same URLs. Worker and scheduler can run anywhere with network access to CloudAMQP and Neon.
