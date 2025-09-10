FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- runtime ---
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
# для psycopg2 и TLS к CloudAMQP/Neon
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY . /app

# по умолчанию — API; для воркеров команда переопределяется в compose
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
