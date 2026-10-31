"""Interactive BQ3 validation. Credentials remain in memory and are never logged."""
import argparse
import getpass
import json
import os
import re
import socket
import traceback
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DIAGNOSTIC_PATH = Path(__file__).resolve().parents[1] / "bq3_last_run.json"


def safe_error_details(error, phase, *, result_stored=False):
    """Inspect driver errors without returning their text, URLs or SQL parameters."""
    original = getattr(error, "orig", error)
    sqlstate = getattr(original, "sqlstate", None)
    if not isinstance(sqlstate, str) or not re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
        sqlstate = None
    message = str(original).lower()
    diagnostic, explanation = "UNKNOWN", "El tipo y la etapa del error requieren revisión."
    if sqlstate == "28P01" or any(x in message for x in ("password authentication failed", "authentication failed", "wrong password")):
        diagnostic, explanation = "DB_PASSWORD_REJECTED", "El servidor rechazó la autenticación. Usa la contraseña de la base de datos, escrita sin codificar."
    elif any(x in message for x in ("tenant or user not found", "invalid tenant")):
        diagnostic, explanation = "DB_POOLER_USER_OR_PROJECT", "El pooler no reconoce el usuario o proyecto. Revisa la URI de Session pooler en Connect."
    elif sqlstate in {"42501", "28000"}:
        diagnostic, explanation = "DB_PERMISSIONS", "La conexión no tiene los permisos necesarios para esta etapa."
    elif sqlstate in {"42P01", "42703", "3F000"}:
        diagnostic, explanation = "DB_SCHEMA", "Falta una tabla, columna o esquema requerido en el proyecto conectado."
    elif isinstance(original, socket.gaierror) or any(x in message for x in ("getaddrinfo failed", "could not translate host", "name or service not known", "nodename nor servname")):
        diagnostic, explanation = "DB_DNS", "No se pudo resolver el servidor de la URI."
    elif any(x in message for x in ("timeout", "timed out", "connection time-out")):
        diagnostic, explanation = "DB_TIMEOUT", "La conexión al servidor agotó el tiempo de espera."
    elif any(x in message for x in ("network is unreachable", "no route to host", "10051", "10065")):
        diagnostic, explanation = "DB_NETWORK_ROUTE", "No hay ruta al servidor. Una conexión directa puede requerir IPv6; usa Session pooler."
    elif any(x in message for x in ("connection refused", "actively refused", "10061")):
        diagnostic, explanation = "DB_CONNECTION_REFUSED", "El servidor o la red rechazó la conexión al puerto indicado."
    elif any(x in message for x in ("certificate verify failed", "ssl error", "tls error")):
        diagnostic, explanation = "DB_TLS", "Falló la negociación de la conexión cifrada."
    elif "not json serializable" in message:
        diagnostic, explanation = "RESULT_SERIALIZATION", "El resultado contiene un tipo que el lanzador no pudo serializar."
    elif isinstance(original, UnicodeError):
        diagnostic, explanation = "RESPONSE_ENCODING", "El controlador no pudo interpretar la respuesta del servidor."
    frames = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
    return {
        "status": "failed", "phase": phase, "diagnostic": diagnostic,
        "explanation": explanation, "error_type": type(error).__name__,
        "driver_error_type": type(original).__name__, "sqlstate": sqlstate,
        "result_stored": result_stored,
        "locations": [{"file": Path(f.filename).name, "function": f.name, "line": f.lineno} for f in frames[-4:]],
    }


def write_diagnostic(report):
    # Only allowlisted fields enter this file. Never serialize exceptions or engines.
    try:
        DIAGNOSTIC_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        print("No se pudo guardar el diagnóstico local; conserva el resumen mostrado.")


def connection_template(template):
    """Reject malformed hosts and embedded credentials before DNS or password input."""
    from sqlalchemy.engine import make_url
    try:
        url = make_url(template)
        port = url.port
    except Exception:
        raise ValueError("Copia solo la URI PostgreSQL, sin comillas ni el comando psql.") from None
    if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise ValueError("Copia la URI PostgreSQL de Connect > Session pooler.")
    if url.password != "[YOUR-PASSWORD]":
        raise ValueError("Deja [YOUR-PASSWORD] en la URI; la contraseña se pide aparte, sin codificar.")
    host = url.host or ""
    dns_name = r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}"
    if (not re.fullmatch(dns_name, host, re.IGNORECASE)
            or not host.lower().endswith((".supabase.com", ".supabase.co"))
            or url.database != "postgres"):
        raise ValueError("La dirección del servidor no tiene el formato esperado. Copia de nuevo la URI de Connect.")
    if port != 5432 or not host.lower().endswith(".pooler.supabase.com"):
        raise ValueError("Selecciona Session pooler en Connect y copia su URI con puerto 5432.")
    if {key.lower() for key in url.query} & {"host", "hostaddr", "port", "service", "servicefile"}:
        raise ValueError("La URI contiene otra configuración de servidor. Copia la URI original de Connect.")
    return url


def connection_url(template, password):
    url = connection_template(template)
    return url.set(drivername="postgresql+psycopg", password=password).update_query_dict(
        {"sslmode": "require", "connect_timeout": "15"})


def main():
    from sqlalchemy import create_engine, text
    from sidequests_analytics.pipeline import compute_bq3, store_bq_result

    parser = argparse.ArgumentParser()
    parser.add_argument("--observation-hours", type=float, default=24.0)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--dashboard", action="store_true")
    args = parser.parse_args()
    print("BQ3: Supabase > Connect > Session pooler, puerto 5432.")
    print("Pega la URI con [YOUR-PASSWORD]; escribe la contraseña aparte. Ambos campos se ocultan.")
    template = getpass.getpass("URI de conexión: ").strip()
    try:
        target = connection_template(template)
    except ValueError as error:
        # The validation messages are fixed strings and never include user input.
        print(f"URI inválida. {error}")
        return 1
    engine = None
    phase = "resolve_host"
    stored = False
    try:
        print(f"Servidor comprobado: {target.host}:{target.port}")
        print("Comprobando DNS antes de pedir la contraseña...")
        socket.getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM)
        print("DNS correcto.")
        password = getpass.getpass("Contraseña de la base de datos (sin codificar): ")
        try:
            url = connection_url(template, password)
        finally:
            del template, password
        phase = "create_engine"
        engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        phase = "connect"
        print("[1/4] Comprobando conexión PostgreSQL...")
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        print("Conexión correcta.")
        phase = "read_and_compute_bq3"
        print("[2/4] Leyendo eventos y calculando BQ3...")
        rows = compute_bq3(engine, observation_hours=args.observation_hours)
        if not rows[0]["journeys_started"]:
            print("No hay recorridos BQ3 v2 en la cohorte. Primero prueba el onboarding de esta rama.")
            return 1
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        if not args.read_only:
            phase = "store_result"
            print("[3/4] Guardando el resultado...")
            store_bq_result(engine, "BQ3", rows)
            stored = True
            print("Resultado guardado en analytics.bq_results. Abre el dashboard de esta rama.")
        else:
            print("Lectura terminada; no se guardaron resultados.")
        if args.dashboard:
            phase = "dashboard_start"
            print("[4/4] Iniciando dashboard...")
            from streamlit.web import bootstrap
            os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
            write_diagnostic({"status": "dashboard_starting", "phase": phase, "result_stored": stored,
                              "journeys_started": rows[0]["journeys_started"], "observation_hours": args.observation_hours})
            print("Abre http://127.0.0.1:8501. La consola debe permanecer abierta; Ctrl+C termina el dashboard.")
            bootstrap.run(str(Path(__file__).resolve().parents[1] / "dashboard_app.py"), False, [],
                          {"server.address": "127.0.0.1", "server.port": 8501,
                           "server.headless": True, "browser.gatherUsageStats": False})
        else:
            write_diagnostic({"status": "passed", "phase": "complete", "result_stored": stored,
                              "journeys_started": rows[0]["journeys_started"], "observation_hours": args.observation_hours})
    except Exception as error:
        details = safe_error_details(error, phase, result_stored=stored)
        write_diagnostic(details)
        print(f"BQ3 no pudo terminar. Etapa: {phase}. Diagnóstico: {details['diagnostic']}.")
        print(details["explanation"])
        print(f"Tipo: {details['error_type']}. Controlador: {details['driver_error_type']}.")
        if details["sqlstate"]:
            print(f"Código SQL: {details['sqlstate']}")
        print("Se guardó un diagnóstico local sin credenciales en bq3_last_run.json.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        if args.dashboard:
            os.environ.pop("DATABASE_URL", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
