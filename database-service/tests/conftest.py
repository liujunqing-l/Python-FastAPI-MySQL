import os


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://health_app:change-me@127.0.0.1:5432/b2315p",
)
os.environ.setdefault("INTERNAL_TOKEN", "test-token")
