import logging
from logging.config import fileConfig

from sqlalchemy import create_engine, engine_from_config, text
from sqlalchemy import pool

from alembic import context

logger = logging.getLogger("alembic.env")

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

from database.postgres_connection import Base, ALCHEMY_CONNECTION_STRING, BASEURL
from database.models import *  # ensure all models are loaded

config.set_main_option("sqlalchemy.url", ALCHEMY_CONNECTION_STRING)
target_metadata = Base.metadata


def create_database_if_not_exists() -> None:
    """Auto-create the target database if it doesn't exist yet. 🗄️"""
    db_name = ALCHEMY_CONNECTION_STRING.rsplit("/", 1)[-1]
    maintenance_url = BASEURL + "postgres"

    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": db_name},
            )
            if not result.scalar():
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                logger.info("✅ Created database '%s'", db_name)
            else:
                logger.info("📦 Database '%s' already exists", db_name)
    except Exception as e:
        logger.error("❌ Failed to auto-create database '%s': %s", db_name, e)
        raise
    finally:
        engine.dispose()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    create_database_if_not_exists()

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
