from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    RABBITMQ_URL: str = "amqp://guest:guest@localhost/"
    RMQ_EXCHANGE: str = "bridge"
    RMQ_TASK_QUEUE: str = "bridge.tasks"
    RMQ_RETRY_QUEUE: str = "bridge.tasks.retry"
    RMQ_RETRY_TTL_MS: int = 5000
    RMQ_ENABLE_CONSUMER: bool = True
    # DB
    DATABASE_URL: str = "postgresql+asyncpg://hr:hr@localhost:5432/hr"

    # AmoCRM
    AMO_BASE_URL: str
    AMO_CLIENT_ID: str
    AMO_CLIENT_SECRET: str
    AMO_REDIRECT_URI: str

    AMO_PIPELINE_ID_MASTER: int
    AMO_STAGE_ID_MASTER_NEW: int
    AMO_PIPELINE_ID_OPERATOR: int
    AMO_STAGE_ID_OPERATOR_NEW: int

    AMO_TAG_WENT_TO_BOT: str = "Перешел в бота"
    AMO_TAG_SURVEY_DONE: str = "Опрос пройден"

    ROUTING_KEYWORD_MASTER: str = "мастер"
    ROUTING_KEYWORD_OPERATOR: str = "оператор"

    # HH OAuth
    HH_CLIENT_ID: str = ""
    HH_CLIENT_SECRET: str = ""
    HH_REDIRECT_URI: str = ""

    # Avito OAuth
    AVITO_CLIENT_ID: str = ""
    AVITO_CLIENT_SECRET: str = ""
    AVITO_REDIRECT_URI: str = ""
    AVITO_AUTHORIZE_URL: str = "https://avito.ru/oauth"
    AVITO_TOKEN_URL: str = "https://api.avito.ru/token"
    AVITO_SCOPE: str = ""

    # поведение
    HH_SYNC_ENABLED: bool = False
    AVITO_SYNC_ENABLED: bool = False
    AVITO_MARK_READ_ON_STAGE_CHANGE: bool = True

    TELEGRAM_MASTER_BOT_TOKEN: str = ""
    TELEGRAM_MASTER_BOT_USERNAME: str = ""
    TELEGRAM_OPERATOR_BOT_TOKEN: str = ""
    TELEGRAM_OPERATOR_BOT_USERNAME: str = ""

    TELEGRAM_WEBHOOK_MODE: bool = False
    TELEGRAM_WEBHOOK_SECRET: str = ""  # для проверки X-Telegram-Bot-Api-Secret-Token
    TELEGRAM_WEBHOOK_BASE: str = ""  # например, https://hr-bridge.onrender.com

    ADMIN_TOKEN: str = ""

    HH_API_BASE: str = "https://api.hh.ru"
    HH_SET_STATE_PATH: str = "/negotiations/{response_id}/status"
    HH_TOKEN_URL: str = "https://api.hh.ru/token"

    AVITO_API_BASE: str = "https://api.avito.ru"
    AVITO_SEND_MESSAGE_PATH: str = "/messenger/v1/accounts/me/chats/{negotiation_id}/messages"
    AVITO_MARK_READ_PATH: str = "/messenger/v1/accounts/me/chats/{negotiation_id}/read"

    # --- AmoChats (amojo) ---
    AMO_CHATS_BASE: str = "https://amojo.amocrm.ru"
    AMO_CHATS_SCOPE_ID: str  # cf188c..._83c08...
    AMO_CHATS_SECRET: str  # cf2032...
    AMO_CHATS_CHANNEL_ID: str  # cf188c...
    AMO_CHATS_ACCOUNT_ID: str  # 83c0858...
    AMO_CHATS_SENDER_USER_AMOJO_ID: str  # e71231...

    # входящие из AmoChats → наш вебхук. Если Amo даёт подпись — сюда.
    AMOCHATS_INCOMING_SECRET: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    RMQ_DLQ_QUEUE: str = "bridge.tasks.dlq"


settings = Settings()
