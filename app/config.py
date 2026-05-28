from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+asyncpg://procbay:password@localhost:5432/procbay"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "change-me"
    AUCTION_DEFAULT_DURATION_SECONDS: int = 300
    CLAUDE_API_KEY: str | None = None
    MANAGER_THRESHOLD_INR: int = 50_000
    CFO_THRESHOLD_INR: int = 500_000


settings = Settings()

