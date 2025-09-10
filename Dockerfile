FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /install /usr/local
# install runtime
COPY app ./app
COPY main.py .
COPY alembic ./alembic
COPY alembic.ini ./

# allow choosing service via docker command
ENTRYPOINT ["bash", "-c"]
CMD ["uvicorn main:app --host 0.0.0.0 --port 8000"]
