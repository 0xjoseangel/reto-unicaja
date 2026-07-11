from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/db.sqlite3"
    app_name: str = "Habla con tu dinero"

    # Proveedor: "claude" | "ollama" | "groq"
    ai_provider: str = "claude"

    # Claude (Anthropic)
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # Ollama (local)
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:7b"

    # Groq (legado)
    groq_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
