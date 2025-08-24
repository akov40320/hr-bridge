FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . /app
CMD ["python", "-u", "-m", "app.services.worker_rmq"]
