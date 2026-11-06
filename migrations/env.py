
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base, engine

# ==========================================
# IMPORT ALL SQLALCHEMY MODELS
# ==========================================

from app import models

# Phase 7:
# Candidate profiles, resumes, job requirements
import app.phase7_models

# Phase 10B:
# Application details and document metadata
import app.phase10_models


# ==========================================
# ALEMBIC CONFIGURATION
# ==========================================

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ==========================================
# OFFLINE MIGRATIONS
# ==========================================

def run_migrations_offline():
    context.configure(
        url=engine.url.render_as_string(
            hide_password=False
        ),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ==========================================
# ONLINE MIGRATIONS
# ==========================================

def run_migrations_online():
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ==========================================
# RUN MIGRATIONS
# ==========================================

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
