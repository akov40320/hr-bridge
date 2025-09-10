from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from app.core.middleware import LoggingMiddleware, REQUEST_COUNT, REQUEST_LATENCY


def test_metrics_aggregated_by_route_template():
    REQUEST_COUNT.clear()
    REQUEST_LATENCY.clear()

    app = FastAPI()
    app.add_middleware(LoggingMiddleware)

    @app.get("/items/{item_id}")
    async def read_item(item_id: int):
        return {"id": item_id}

    client = TestClient(app)
    client.get("/items/1")
    client.get("/items/2")

    metrics = generate_latest().decode()
    families = list(text_string_to_metric_families(metrics))
    family = next(f for f in families if f.name == "http_requests")
    samples = [s for s in family.samples if s.name == "http_requests_total"]

    paths = {s.labels["path"] for s in samples}
    assert "/items/{item_id}" in paths
    assert "/items/1" not in paths
    assert "/items/2" not in paths

    sample = next(
        s
        for s in samples
        if s.labels["path"] == "/items/{item_id}" and s.labels["status"] == "200"
    )
    assert sample.value == 2
