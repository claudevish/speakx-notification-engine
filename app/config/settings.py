from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    anthropic_api_key: str
    clevertap_account_id: str
    clevertap_passcode: str
    clevertap_region: str = "in1"
    base_url: str = ""
    secret_key: str
    environment: str = "development"
    log_level: str = "INFO"
    portal_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
