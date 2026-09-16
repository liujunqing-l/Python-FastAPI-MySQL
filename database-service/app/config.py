from pathlib import Path
import secrets

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str
    internal_token: str
    raw_spool_dir: Path = Path("./spool")
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_prefix: str = "raw"
    auth_jwt_secret: str = ""
    auth_jwt_expire_seconds: int = 3600

    @model_validator(mode="after")
    def configure_auth_secret(self) -> "Settings":
        if not self.auth_jwt_secret:
            if self.app_env.lower() == "production":
                raise ValueError("AUTH_JWT_SECRET is required when APP_ENV=production")
            # A development fallback keeps local tests convenient while making
            # it impossible to mistake a generated key for a production secret.
            self.auth_jwt_secret = secrets.token_urlsafe(32)
        if self.auth_jwt_expire_seconds <= 0:
            raise ValueError("AUTH_JWT_EXPIRE_SECONDS must be positive")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
