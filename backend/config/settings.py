"""
Aegis-1 Configuration Settings

Centralized configuration management using Pydantic Settings.
All environment variables are validated and typed.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===================
    # Application
    # ===================
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secret_key: str = Field(default="change-me-in-production")

    # ===================
    # Database (TimescaleDB)
    # ===================
    database_url: str = Field(
        default="postgresql://aegis:aegis_password@localhost:5432/aegis_db"
    )

    # ===================
    # Redis
    # ===================
    redis_url: str = Field(default="redis://localhost:6379")
    redis_cache_ttl: int = Field(default=60, description="Cache TTL in seconds")

    # ===================
    # RabbitMQ
    # ===================
    rabbitmq_url: str = Field(
        default="amqp://aegis:aegis_password@localhost:5672/"
    )

    # ===================
    # Pinecone (Vector DB)
    # ===================
    pinecone_api_key: str = Field(default="")
    pinecone_environment: str = Field(default="")
    pinecone_index_name: str = Field(default="aegis-vectors")
    pinecone_similarity_threshold: float = Field(
        default=0.6,
        description="Minimum similarity score for vector matches (AC-03)"
    )

    # ===================
    # Google AI (Gemini)
    # ===================
    google_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-1.5-flash")

    # ===================
    # Crypto Exchanges
    # ===================
    binance_api_key: str = Field(default="")
    binance_secret_key: str = Field(default="")
    coinbase_api_key: str = Field(default="")
    coinbase_secret_key: str = Field(default="")

    # ===================
    # Stock Market
    # ===================
    alpaca_api_key: str = Field(default="")
    alpaca_secret_key: str = Field(default="")
    alpaca_base_url: str = Field(default="https://paper-api.alpaca.markets")
    polygon_api_key: str = Field(default="")

    # ===================
    # News & Social
    # ===================
    twitter_bearer_token: str = Field(default="")
    news_api_key: str = Field(default="")

    # ===================
    # Email (SMTP)
    # ===================
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    email_from: str = Field(default="aegis@yourdomain.com")
    email_rate_limit: int = Field(
        default=10,
        description="Max emails per hour per recipient"
    )

    # ===================
    # Webhook Output
    # ===================
    webhook_url: str = Field(default="")
    webhook_auth_token: str = Field(default="")

    # ===================
    # Risk Management
    # ===================
    max_drawdown_percent: float = Field(
        default=5.0,
        description="Maximum drawdown before reducing exposure"
    )
    kill_switch_loss_percent: float = Field(
        default=2.0,
        description="Loss threshold to trigger kill switch (per session)"
    )
    default_position_size_percent: float = Field(
        default=1.0,
        description="Default position size as % of portfolio"
    )

    # ===================
    # Performance Thresholds (from AC)
    # ===================
    max_consensus_latency_ms: int = Field(
        default=100,
        description="Max time to resolve conflicting signals (AC-01)"
    )
    max_e2e_latency_ms: int = Field(
        default=1200,
        description="Max end-to-end latency for AI trades"
    )
    max_emergency_exit_latency_ms: int = Field(
        default=100,
        description="Max latency for math-only emergency exits"
    )
    volatility_threshold_multiplier: float = Field(
        default=2.0,
        description="Volatility multiplier to trigger Quant weight reduction (AC-05)"
    )

    # ===================
    # Validation
    # ===================
    @field_validator("max_drawdown_percent", "kill_switch_loss_percent")
    @classmethod
    def validate_percentages(cls, v: float) -> float:
        if not 0 < v <= 100:
            raise ValueError("Percentage must be between 0 and 100")
        return v

    @field_validator("pinecone_similarity_threshold")
    @classmethod
    def validate_similarity(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError("Similarity threshold must be between 0 and 1")
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
