"""Промежуточное ПО (middleware) для логирования запросов и метрик Prometheus."""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Определения метрик Prometheus
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds", ["method", "path"]
)


class LoggingMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """ASGI‑middleware для структурированного логирования запросов/ответов и метрик."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response: StarletteResponse = await call_next(request)
        process_time = time.time() - start_time

        log = logging.getLogger("app.request")
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration": process_time,
            },
        )

        REQUEST_COUNT.labels(
            request.method, request.url.path, str(response.status_code)
        ).inc()
        REQUEST_LATENCY.labels(request.method, request.url.path).observe(process_time)
        return response


async def metrics_endpoint() -> StarletteResponse:
    """Отдавать метрики Prometheus."""
    return StarletteResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
