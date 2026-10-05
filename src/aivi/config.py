from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/aivi.db"
    api_token: str = ""
    admin_username: str = "admin"
    admin_password: str = "1234"
    session_secret: str = "change-this-local-session-secret"
    session_hours: int = 12
    data_dir: Path = Path("./data")
    export_dir: Path = Path("./exports")
    set_api_key: str = ""
    set_api_base_url: str = "https://marketplace.set.or.th/api/public"
    gemini_api_key: str = ""
    llm_cheap_provider: str = "gemini"
    llm_strong_provider: str = "gemini"
    llm_cheap_model: str = "gemini-2.5-flash"
    llm_strong_model: str = "gemini-2.5-pro"
    aivi_env: str = "dev"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()
