"""Application configuration settings."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration loaded from environment / .env file."""

    APP_NAME: str = "Tri9T Document Intelligence API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # SQLite
    DATABASE_URL: str = "sqlite:///./tri9t.db"

    # MongoDB (placeholder for future stages)
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "tri9t"

    # Groq
    GROQ_API_KEY: str = ""
    MODEL_NAME: str = "llama-3.3-70b-versatile"
    TEMPERATURE: float = 0.7

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


settings = Settings()
