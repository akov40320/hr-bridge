from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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

    # прод-поведение с «заглушками»
    HH_SYNC_ENABLED: bool = False
    AVITO_SYNC_ENABLED: bool = False
    AVITO_MARK_READ_ON_STAGE_CHANGE: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
