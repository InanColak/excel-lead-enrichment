from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://leadenrich:changeme@db:5432/leadenrich"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "changeme"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme"
    upload_dir: str = "/data/uploads"
    max_upload_size_mb: int = 10
    max_rows_per_file: int = 10000
    debug: bool = False
    apollo_api_url: str = "https://api.apollo.io/api/v1/people/match"
    apollo_bulk_api_url: str = "https://api.apollo.io/api/v1/people/bulk_match"
    apollo_webhook_secret: str = "changeme-webhook-secret"
    webhook_base_url: str = ""
    webhook_timeout_seconds: int = 300
    bulk_batch_size: int = 10
    bulk_batch_delay_seconds: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
