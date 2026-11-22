"""Safety checks for the optional local BQ8 Streamlit dashboard."""
import runpy
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_streamlit_secrets_are_excluded_from_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/.streamlit/secrets.toml" in ignore
    assert ".env" in ignore


def test_local_credential_toml_roundtrips_without_losing_special_characters():
    helpers = runpy.run_path(str(ROOT / "scripts" / "configure_bq8_dashboard.py"),
                             run_name="test_import_only")
    sample = "postgresql+psycopg://postgres.EXAMPLE:p%40ssw%23ord@pooler.example:5432/postgres"
    data = helpers["secrets_toml"](sample)
    assert tomllib.loads(data)["DATABASE_URL"] == sample
    assert "DATABASE_URL = " in data


def test_streamlit_entrypoint_supports_local_secret_and_existing_env():
    source = (ROOT / "dashboard_app.py").read_text(encoding="utf-8")
    compile(source, "dashboard_app.py", "exec")
    assert 'if not os.getenv("DATABASE_URL"):' in source
    assert 'st.secrets.get("DATABASE_URL")' in source
    assert 'st.stop()' in source


def test_live_bq8_dashboard_does_not_publish_results():
    source = (ROOT / "src" / "sidequests_analytics" / "dashboard.py").read_text(encoding="utf-8")
    compile(source, "dashboard.py", "exec")
    assert "compute_bq8_experienced(engine)" in source
    assert '"Refresh live BQ8"' in source
    assert "store_bq_result(" not in source
