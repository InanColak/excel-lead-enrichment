"""Application configuration loaded from environment variables and .env file."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration for the lead enrichment service.

    Values are loaded from environment variables prefixed with ENRICHMENT_
    or from a .env file in the project root.
    """

    # API Keys
    apollo_api_key: str = Field(description="Apollo.io API key")
    lusha_api_key: str = Field(description="Lusha API key")
    openai_api_key: str = Field(description="OpenAI API key for column detection")

    # Webhook
    webhook_url: str = Field(description="Public HTTPS URL for Apollo webhook callbacks")
    webhook_port: int = Field(default=8443, description="Local port for the webhook server")
    webhook_timeout_seconds: int = Field(
        default=600, description="Max seconds to wait for all Apollo webhooks"
    )

    # Rate Limits
    apollo_rate_per_minute: int = Field(default=50, description="Apollo API requests per minute")
    apollo_daily_limit: int = Field(default=600, description="Apollo API requests per day")
    lusha_rate_per_second: int = Field(default=25, description="Lusha API requests per second")

    # Batch Sizes
    apollo_batch_size: int = Field(default=10, description="Max records per Apollo bulk_match call")
    lusha_batch_size: int = Field(
        default=100, description="Max records per Lusha bulk person call"
    )

    # HTTP Client
    http_timeout_seconds: int = Field(default=30, description="HTTP request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts for failed API requests")

    # Paths
    db_path: Path = Field(default=Path("data/enrichment.db"), description="SQLite database path")

    model_config = {
        "env_file": ".env",
        "env_prefix": "ENRICHMENT_",
        "extra": "ignore",
    }
