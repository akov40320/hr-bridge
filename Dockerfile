FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml poetry.lock* requirements.txt* /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
CMD ["python", "-m", "app.worker_rmq"]
