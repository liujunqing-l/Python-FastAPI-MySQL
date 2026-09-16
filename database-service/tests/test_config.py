from app.config import Settings
import pytest


def test_settings_reads_postgresql_database_url():
    settings = Settings(
        database_url="postgresql+psycopg://health_app:secret@127.0.0.1:5432/b2315p",
        internal_token="test-token",
    )

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.internal_token == "test-token"


def test_settings_has_local_spool_default(tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://health_app:secret@127.0.0.1:5432/b2315p",
        internal_token="test-token",
        raw_spool_dir=tmp_path,
    )

    assert settings.raw_spool_dir == tmp_path


def test_production_requires_explicit_jwt_secret():
    with pytest.raises(ValueError, match="AUTH_JWT_SECRET"):
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://health_app:secret@127.0.0.1:5432/b2315p",
            internal_token="test-token",
            auth_jwt_secret="",
        )
