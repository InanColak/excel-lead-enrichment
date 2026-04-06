from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://leadenrich:changeme@db:5432/leadenrich"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "changeme"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme"
    debug: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
