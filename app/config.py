"""
Configuration settings loaded from environment variables.
Uses Pydantic for validation and type safety.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application configuration from .env"""

    # Anthropic
    anthropic_api_key: str

    # Meta Cloud API (WhatsApp)
    meta_verify_token: str
    meta_access_token: str
    meta_phone_number_id: str

    # Raunk's phones (primary + optional secondary, comma-separated)
    raunak_phone: str
    raunak_phone2: Optional[str] = None

    # Google APIs
    google_credentials_file: str = "data/google_credentials.json"
    google_token_file: str = "data/google_token.json"

    # External APIs
    openweather_api_key: Optional[str] = None
    news_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None  # For Whisper voice transcription

    # Database (PostgreSQL with asyncpg)
    database_url: str

    # Application settings
    max_conversation_history: int = 50
    log_level: str = "INFO"
    transcription_backend: str = "whisper"  # or "sarvam" for regional languages
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"  # Allow extra env vars


# Global settings instance
settings = Settings()
