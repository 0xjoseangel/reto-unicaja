from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/db.sqlite3"
    app_name: str = "Habla con tu dinero"

    class Config:
        env_file = ".env"


settings = Settings()
