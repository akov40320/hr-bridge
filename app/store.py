import json, os, time, datetime as dt
from typing import Optional

DATA_DIR = "data"
LEADS_MAP = os.path.join(DATA_DIR, "leads_map.jsonl")
PENDING = os.path.join(DATA_DIR, "pending_sync.jsonl")

os.makedirs(DATA_DIR, exist_ok=True)


def save_link(lead_id: int, platform: str, vacancy_id: str, external_id: Optional[str]):
    """Сохраняем связь lead ↔ внешний отклик (response_id/negotiation_id)."""
    with open(LEADS_MAP, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "lead_id": lead_id,
            "platform": platform,
            "vacancy_id": vacancy_id,
            "external_id": external_id
        }, ensure_ascii=False) + "\n")


def find_link(lead_id: int) -> Optional[dict]:
    if not os.path.exists(LEADS_MAP):
        return None
    with open(LEADS_MAP, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("lead_id") == lead_id:
                return row
    return None


def enqueue_pending(task: dict):
    """Кладём отложенную задачу синхры (hh/avito)."""
    task = dict(task)
    task.setdefault("created_at", dt.datetime.now(dt.timezone.utc).isoformat())
    with open(PENDING, "a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")


def replay_pending(hh_enabled: bool, avito_enabled: bool, handler_hh, handler_avito) -> dict:
    """Пытаемся выполнить накопленные задачи. Невыполненные оставляем в файле."""
    if not os.path.exists(PENDING):
        return {"total": 0, "done": 0, "left": 0}

    left: list[str] = []
    total = 0
    done = 0

    with open(PENDING, "r", encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()]

    for ln in lines:
        total += 1
        task = json.loads(ln)
        platform = task.get("platform")
        try:
            if platform == "hh":
                if not hh_enabled:
                    left.append(ln)  # оставляем до включения ключей
                    continue
                handler_hh(task)  # вызываем обработчик hh
                done += 1
            elif platform == "avito":
                if not avito_enabled:
                    left.append(ln)
                    continue
                handler_avito(task)  # обработчик avito
                done += 1
            else:
                # неизвестная платформа — пропустим
                done += 1
        except Exception:
            # при ошибке — оставим задачу
            left.append(ln)

    # перезаписываем очередь оставшимися
    with open(PENDING, "w", encoding="utf-8") as f:
        for ln in left:
            f.write(ln.rstrip() + "\n")

    return {"total": total, "done": done, "left": len(left)}
