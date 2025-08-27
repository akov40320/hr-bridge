"""Configuration models and helpers for application settings."""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # RMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost/"
    RMQ_EXCHANGE: str = "bridge"
    RMQ_TASK_QUEUE: str = "bridge.tasks"
    RMQ_RETRY_QUEUE: str = "bridge.tasks.retry"
    RMQ_DLQ_QUEUE: str = "bridge.tasks.dlq"
    RMQ_RETRY_TTL_MS: int = 5_000
    RMQ_ENABLE_CONSUMER: bool = True
    RMQ_CONSUMERS: int = 1  # тестовый дефолт

    # DB (в тестах безопаснее sqlite in-memory)
    DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"

    # AmoCRM OAuth/база (дефолты пустые → не валимся в тестах)
    AMO_BASE_URL: str = ""
    AMO_CLIENT_ID: str = ""
    AMO_CLIENT_SECRET: str = ""
    AMO_REDIRECT_URI: str = ""

    AMO_ACCESS_TOKEN: str = ""
    AMO_REFRESH_TOKEN: str = ""
    AMO_EXPIRES_AT: int = 0

    # IDшники воронок/стадий — как Optional[int]
    AMO_PIPELINE_ID_MASTER: Optional[int] = None
    AMO_STAGE_ID_MASTER_NEW: Optional[int] = None
    AMO_STAGE_ID_MASTER_SURVEY: Optional[int] = None
    AMO_PIPELINE_ID_OPERATOR: Optional[int] = None
    AMO_STAGE_ID_OPERATOR_NEW: Optional[int] = None
    AMO_STAGE_ID_OPERATOR_SURVEY: Optional[int] = None

    # Теги/роутинг
    AMO_TAG_WENT_TO_BOT: str = "Перешел в бота"
    AMO_TAG_SURVEY_DONE: str = "Опрос пройден"
    ROUTING_KEYWORD_MASTER: str = "мастер"
    ROUTING_KEYWORD_OPERATOR: str = "оператор"

    # HH
    HH_CLIENT_ID: str = ""
    HH_CLIENT_SECRET: str = ""
    HH_REDIRECT_URI: str = ""
    HH_ACCESS_TOKEN: str = ""
    HH_REFRESH_TOKEN: str = ""
    HH_EXPIRES_AT: int = 0
    HH_API_BASE: str = "https://api.hh.ru"
    HH_SET_STATE_PATH: str = "/negotiations/{response_id}/status"
    HH_TOKEN_URL: str = "https://api.hh.ru/oauth/token"  # унифицировали
    HH_USER_AGENT: str = ""

    # Avito
    AVITO_CLIENT_ID: str = ""
    AVITO_CLIENT_SECRET: str = ""
    AVITO_REDIRECT_URI: str = ""
    AVITO_ACCESS_TOKEN: str = ""
    AVITO_REFRESH_TOKEN: str = ""
    AVITO_EXPIRES_AT: int = 0
    AVITO_AUTHORIZE_URL: str = "https://avito.ru/oauth"
    AVITO_TOKEN_URL: str = "https://api.avito.ru/token"
    AVITO_SCOPE: str = ""
    AVITO_API_BASE: str = "https://api.avito.ru"
    AVITO_SEND_MESSAGE_PATH: str = "/messenger/v1/accounts/me/chats/{negotiation_id}/messages"
    AVITO_MARK_READ_PATH: str = "/messenger/v1/accounts/me/chats/{negotiation_id}/read"
    AVITO_WEBHOOK_URL: str = ""
    AVITO_MESSENGER_EVENTS: str = "message"
    AVITO_WEBHOOK_SECRET: str | None = None
    AVITO_SIGNATURE_HEADER: str = "X-Avito-Signature"

    # Поведение
    HH_SYNC_ENABLED: bool = False
    AVITO_SYNC_ENABLED: bool = False
    AVITO_MARK_READ_ON_STAGE_CHANGE: bool = True

    # Telegram
    TELEGRAM_MASTER_BOT_TOKEN: str = ""
    TELEGRAM_MASTER_BOT_USERNAME: str = ""
    TELEGRAM_OPERATOR_BOT_TOKEN: str = ""
    TELEGRAM_OPERATOR_BOT_USERNAME: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_WEBHOOK_BASE: str = ""
    TELEGRAM_WEBHOOK_MODE: bool = True

    # Админ
    ADMIN_TOKEN: str = ""  # не обязателен для тестов; проверим в validate_required()

    # --- AmoChats (amojo) ---
    AMO_CHATS_BASE: str = "https://amojo.amocrm.ru"
    AMO_CHATS_SCOPE_ID: str = ""
    AMO_CHATS_SECRET: str = ""
    AMO_CHATS_CHANNEL_ID: str = ""
    AMO_CHATS_ACCOUNT_ID: str = ""
    AMO_CHATS_SENDER_USER_AMOJO_ID: str = ""
    AMOCHATS_ENABLED: bool = True
    AMO_CHATS_SENDER_NAME: str = "tg-bridge"
    AMO_CHATS_AUTOCONNECT: bool = True
    AMOCHATS_INCOMING_SECRET: str = ""

    # HH webhooks
    HH_WEBHOOK_URL: str = ""
    HH_WEBHOOK_EVENTS: str = ""

    # Amo кастомные поля (0 = нет)
    AMO_CF_LEAD_CITY_ID: int = 0
    AMO_CF_LEAD_VACANCY_TITLE_ID: int = 0
    AMO_CF_LEAD_APPLICANT_PHONE_ID: int = 0
    AMO_CF_LEAD_APPLICANT_NAME_ID: int = 0
    AMO_CF_LEAD_APPLICANT_EMAIL_ID: int = 0
    AMO_CF_REFUSAL_REASON_ID: int = 0

    def validate_required(self) -> None:
        """Жёсткая проверка для прод/старта сервиса (НЕ для тестов)."""
        required = [
            ("AMO_BASE_URL", self.AMO_BASE_URL),
            ("AMO_CLIENT_ID", self.AMO_CLIENT_ID),
            ("AMO_CLIENT_SECRET", self.AMO_CLIENT_SECRET),
            ("AMO_REDIRECT_URI", self.AMO_REDIRECT_URI),
            ("AMO_PIPELINE_ID_MASTER", self.AMO_PIPELINE_ID_MASTER),
            ("AMO_STAGE_ID_MASTER_NEW", self.AMO_STAGE_ID_MASTER_NEW),
            ("AMO_STAGE_ID_MASTER_SURVEY", self.AMO_STAGE_ID_MASTER_SURVEY),
            ("AMO_PIPELINE_ID_OPERATOR", self.AMO_PIPELINE_ID_OPERATOR),
            ("AMO_STAGE_ID_OPERATOR_NEW", self.AMO_STAGE_ID_OPERATOR_NEW),
            ("AMO_STAGE_ID_OPERATOR_SURVEY", self.AMO_STAGE_ID_OPERATOR_SURVEY),
            ("ADMIN_TOKEN", self.ADMIN_TOKEN),
            # AmoChats — если включено автоподключение/использование
            (
                "AMO_CHATS_SCOPE_ID",
                self.AMO_CHATS_SCOPE_ID if self.AMOCHATS_ENABLED else "ok",
            ),
            (
                "AMO_CHATS_SECRET",
                self.AMO_CHATS_SECRET if self.AMOCHATS_ENABLED else "ok",
            ),
            (
                "AMO_CHATS_CHANNEL_ID",
                self.AMO_CHATS_CHANNEL_ID if self.AMOCHATS_ENABLED else "ok",
            ),
            (
                "AMO_CHATS_ACCOUNT_ID",
                self.AMO_CHATS_ACCOUNT_ID if self.AMOCHATS_ENABLED else "ok",
            ),
            (
                "AMO_CHATS_SENDER_USER_AMOJO_ID",
                self.AMO_CHATS_SENDER_USER_AMOJO_ID if self.AMOCHATS_ENABLED else "ok",
            ),
        ]
        missing = [k for k, v in required if not v]
        if missing:
            raise RuntimeError(f"Missing required settings: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""

    return Settings()
