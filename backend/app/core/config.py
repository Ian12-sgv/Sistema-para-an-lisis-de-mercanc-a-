from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = Field(default="local", alias="APP_ENV")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    db_driver: str = Field(default="ODBC Driver 17 for SQL Server", alias="DB_DRIVER")
    db_server: str = Field(default="SERVERDOS\\SERVERSQL_DOS", alias="DB_SERVER")
    db_name: str = Field(default="master", alias="DB_NAME")
    db_user: str = Field(default="sa", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")
    db_trust_server_certificate: bool = Field(default=True, alias="DB_TRUST_SERVER_CERTIFICATE")
    db_encrypt: str = Field(default="yes", alias="DB_ENCRYPT")
    db_connection_timeout: int = Field(default=5, alias="DB_CONNECTION_TIMEOUT")
    db_query_timeout: int = Field(default=60, alias="DB_QUERY_TIMEOUT")

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "https://rotacionblumer.netlify.app",
        ],
        alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def has_database_credentials(self) -> bool:
        return bool(self.db_server and self.db_name and self.db_user and self.db_password)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]

        return value

    @model_validator(mode="after")
    def validate_production_credentials(self):
        if self.app_env.lower() in {"prod", "production"} and not self.db_password:
            raise ValueError("DB_PASSWORD is required in production.")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
