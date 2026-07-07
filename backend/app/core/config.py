from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/db.sqlite3"
    app_name: str = "Habla con tu dinero"
    google_api_key: str = ""
    groq_api_key: str = ""

    # Proveedor de IA: "groq" | "ollama"
    ai_provider: str = "groq"
    ollama_base_url: str = "http://ollama:11434/v1"
    ollama_model: str = "qwen2.5:7b"

    class Config:
        env_file = ".env"


settings = Settings()
