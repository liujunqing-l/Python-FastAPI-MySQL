from logging.config import fileConfig
import os

from dotenv import load_dotenv

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Base


config = context.config
load_dotenv()
database_url = os.getenv("DATABASE_URL")
if database_url:
    # Alembic's ConfigParser treats '%' specially, so escape it for URLs.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """Ignore PostgreSQL's auto-created indexes/table for the DEFAULT partition.

    ``health_records_default`` is created explicitly by migration 001 and is
    not represented as a separate ORM table.  Autogenerate should therefore
    compare the partitioned parent only, rather than proposing destructive
    removal of the managed child partition.
    """

    if reflected and type_ == "table" and name == "health_records_default":
        return False
    if reflected and type_ == "index" and name == "health_records_default_imei_collected_at_idx":
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
