import json
from pathlib import Path
import sys
import socket

import pytest

from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_bq3_local as runner
from run_bq3_local import connection_template, safe_error_details


TEMPLATE = "postgresql://postgres.project:[YOUR-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"


def test_connection_password_error_is_classified_without_sqlstate_or_credentials():
    original = RuntimeError("connection failed: password authentication failed; test-secret/xyz postgres://private-host")
    error = OperationalError("private statement", {"password": "test-secret/xyz"}, original)
    details = safe_error_details(error, "connect")
    assert details["diagnostic"] == "DB_PASSWORD_REJECTED"
    assert details["sqlstate"] is None
    text = json.dumps(details)
    assert "test-secret" not in text
    assert "private-host" not in text
    assert "private statement" not in text


def test_pooler_tenant_error_is_distinguished_from_bad_password():
    details = safe_error_details(RuntimeError("FATAL: Tenant or user not found (private-user)"), "connect")
    assert details["diagnostic"] == "DB_POOLER_USER_OR_PROJECT"
    assert "private-user" not in json.dumps(details)


def test_unknown_error_does_not_print_its_message_or_embedded_secret():
    details = safe_error_details(TypeError("unexpected test-secret/xyz"), "read_and_compute_bq3")
    assert details["diagnostic"] == "UNKNOWN"
    assert details["error_type"] == "TypeError"
    assert "test-secret" not in json.dumps(details)


def test_error_after_result_storage_retains_that_fact():
    details = safe_error_details(RuntimeError("dashboard private data"), "dashboard_start", result_stored=True)
    assert details["result_stored"] is True
    assert details["phase"] == "dashboard_start"
    assert "private data" not in json.dumps(details)


def test_sqlstate_missing_table_is_reported_without_raw_database_error():
    class MissingTableError(Exception):
        sqlstate = "42P01"
    details = safe_error_details(MissingTableError("private.schema table details"), "read_and_compute_bq3")
    assert details["diagnostic"] == "DB_SCHEMA"
    assert details["sqlstate"] == "42P01"
    assert "private.schema" not in json.dumps(details)


@pytest.mark.parametrize("template", [
    TEMPLATE.replace("[YOUR-PASSWORD]", "private-secret"),
    TEMPLATE.replace("@aws-0", "@private-secret@aws-0"),
    TEMPLATE.replace("aws-0", "aws-0\u200b"),
    TEMPLATE.replace(":5432", ":6543"),
    TEMPLATE + "?host=private-secret.example",
    "psql '" + TEMPLATE + "'",
])
def test_invalid_templates_are_rejected_without_echoing_input(template):
    with pytest.raises(ValueError) as error:
        connection_template(template)
    assert "private-secret" not in str(error.value)
    assert "postgresql://" not in str(error.value)


def test_valid_pooler_template_exposes_only_expected_host():
    url = connection_template(TEMPLATE)
    assert url.host == "aws-0-sa-east-1.pooler.supabase.com"
    assert url.port == 5432


def test_failed_dns_stops_before_password_prompt_or_database_connection(monkeypatch, tmp_path, capsys):
    prompts = []
    def get_input(prompt):
        prompts.append(prompt)
        assert len(prompts) == 1, "A DNS failure must not ask for the password"
        return TEMPLATE

    def fail_dns(host, port, **kwargs):
        assert host == "aws-0-sa-east-1.pooler.supabase.com"
        assert port == 5432
        raise socket.gaierror(11001, "un mensaje localizado que no se registra")

    monkeypatch.setattr(sys, "argv", ["run_bq3_local.py"])
    monkeypatch.setattr(runner.getpass, "getpass", get_input)
    monkeypatch.setattr(runner.socket, "getaddrinfo", fail_dns)
    monkeypatch.setattr(runner, "DIAGNOSTIC_PATH", tmp_path / "diagnostic.json")
    assert runner.main() == 1
    details = json.loads(runner.DIAGNOSTIC_PATH.read_text(encoding="utf-8"))
    assert details["diagnostic"] == "DB_DNS"
    assert details["phase"] == "resolve_host"
    assert details["result_stored"] is False
    assert len(prompts) == 1
    assert "un mensaje localizado" not in capsys.readouterr().out
