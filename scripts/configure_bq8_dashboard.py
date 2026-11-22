"""One-time local Streamlit credential setup. No secrets are committed or printed.

Run from the Analytics repository with:
  python scripts/configure_bq8_dashboard.py
Then:
  python -m streamlit run dashboard_app.py --server.address 127.0.0.1
"""
import getpass
import json
import os
import socket
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from run_bq3_local import connection_template, connection_url, safe_error_details

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = PROJECT_ROOT / ".streamlit" / "secrets.toml"


def secrets_toml(database_url: str) -> str:
    """TOML basic strings support JSON string escapes; do not print this value."""
    return "DATABASE_URL = " + json.dumps(database_url, ensure_ascii=True) + "\n"


def main() -> int:
    if SECRETS_PATH.exists():
        print("The local Streamlit credentials file already exists. It was not overwritten.")
        print("To rotate credentials, edit or remove it locally, without committing it.")
        return 1

    print("One-time BQ8 dashboard setup (local machine only).")
    print("Copy Supabase > Connect > Session pooler, port 5432,")
    print("leaving the literal [YOUR-PASSWORD] placeholder in the PostgreSQL URI.")
    template = getpass.getpass("URI PostgreSQL (input hidden): ").strip()
    try:
        parsed = connection_template(template)
    except ValueError as error:
        print(f"Connection URI format invalid: {error}")
        return 1

    phase = "resolve_host"
    engine = None
    try:
        socket.getaddrinfo(parsed.host, parsed.port, type=socket.SOCK_STREAM)
        password = getpass.getpass("PostgreSQL database password (input hidden): ")
        try:
            url = connection_url(template, password)
        finally:
            del template, password

        phase = "test_connection"
        engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        engine.dispose()
        engine = None

        # A local plaintext file is a convenience, not encrypted secret storage.
        # .streamlit/secrets.toml is ignored by Git, and this program never logs it.
        SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Avoid overwriting existing files or following symlinks.
        with SECRETS_PATH.open("x", encoding="utf-8") as handle:
            handle.write(secrets_toml(url.render_as_string(hide_password=False)))
        if os.name != "nt":
            SECRETS_PATH.chmod(0o600)

        print("Connection verified. Local Streamlit configuration saved.")
        print("WARNING: credentials are plaintext on this computer, NOT encrypted.")
        print("Keep the file private, do not attach it to issues or screenshots,")
        print("and never commit it to GitHub. Only launch the dashboard locally.")
        return 0
    except Exception as error:
        details = safe_error_details(error, phase)
        print(f"Setup did not complete: {details['diagnostic']}.")
        print(details["explanation"])
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
