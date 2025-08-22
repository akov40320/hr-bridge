class Settings:
    def __getattr__(self, name):
        return ""


settings = Settings()
