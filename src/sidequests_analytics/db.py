import os
import tomllib
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        # Reuse the git-ignored local Streamlit credentials file, without printing it.
        secret = Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"
        if secret.is_file():
            try:
                with secret.open("rb") as handle:
                    database_url = tomllib.load(handle).get("DATABASE_URL")
            except (OSError, ValueError):
                raise RuntimeError("Invalid local database configuration.") from None
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required. Use the Supabase pooler/direct PostgreSQL "
            "connection from a server-side environment; never expose it to mobile clients."
        )

    return create_engine(database_url, pool_pre_ping=True, hide_parameters=True)
