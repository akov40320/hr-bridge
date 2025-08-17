from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
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

    # Роутинг по тексту вакансии
    ROUTING_KEYWORD_MASTER: str = "мастер"
    ROUTING_KEYWORD_OPERATOR: str = "оператор"

    # HeadHunter OAuth
    HH_CLIENT_ID: str = ""
    HH_CLIENT_SECRET: str = ""
    HH_REDIRECT_URI: str = ""  # из env, без жёсткого дефолта

    # Avito OAuth
    AVITO_CLIENT_ID: str = ""
    AVITO_CLIENT_SECRET: str = ""
    AVITO_REDIRECT_URI: str = ""  # из env
    AVITO_AUTHORIZE_URL: str = "https://avito.ru/oauth"
    AVITO_TOKEN_URL: str = "https://api.avito.ru/token"  # <— этого поля не хватало

    # Флаги синхры/поведения
    HH_SYNC_ENABLED: bool = False
    AVITO_SYNC_ENABLED: bool = False
    AVITO_MARK_READ_ON_STAGE_CHANGE: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
