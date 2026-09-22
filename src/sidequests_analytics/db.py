import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required. Use the Supabase pooler/direct PostgreSQL "
            "connection from a server-side environment; never expose it to mobile clients."
        )

    return create_engine(database_url, pool_pre_ping=True)
