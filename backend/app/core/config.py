from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/db.sqlite3"
    app_name: str = "Habla con tu dinero"

    # Modelo en formato litellm: "anthropic/claude-haiku-4-5", "ollama/llama3.2", etc.
    litellm_model: str = "anthropic/claude-haiku-4-5"

    # API keys — litellm las lee nativas de estas variables de entorno
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    gemini_api_key: str = ""
    mistral_api_key: str = ""

    # Para Ollama o endpoints custom (ej: http://ollama:11434)
    litellm_api_base: str = ""

    # JWT
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # Voz
    model_cache_dir: str = "/tmp/models"

    class Config:
        env_file = ".env"
        extra = "ignore"  # ignora variables desconocidas en .env


settings = Settings()
