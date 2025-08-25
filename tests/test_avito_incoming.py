import logging

from app.api import avito_incoming


def test_webhook_logs(monkeypatch, client, caplog):
    async def fake_process(platform, raw, http_client, parse):
        return {"ok": True}

    monkeypatch.setattr(avito_incoming, "process_job_board_webhook", fake_process)

    with caplog.at_level(logging.INFO, logger=avito_incoming.logger.name):
        r = client.post("/webhooks/avito", data=b"payload")

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert any("Received Avito webhook" in record.message for record in caplog.records)
