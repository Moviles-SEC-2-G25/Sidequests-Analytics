"""Run BQ8 from Windows/terminal using the existing secure BQ3 pooler pattern.

By default only SELECT queries run. Publishing aggregate results requires --publish.
No URL, password, account ID or user-level row is printed or written to disk.
"""
import argparse
import getpass
import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_bq3_local import connection_template, connection_url, safe_error_details


def summarize(legacy, experienced):
    print("\nBQ8 weekly experiment (all instrumented users):")
    print(json.dumps(legacy, indent=2, ensure_ascii=False, default=str))
    print("\nBQ8 Sprint 4 cohort: >=2 quests completed BEFORE exposure:")
    print(json.dumps(experienced, indent=2, ensure_ascii=False, default=str))
    if any(int(row.get("eligible_users") or 0) < 10 for row in experienced):
        print(
            "\nLIMITACION: menos de diez usuarios elegibles en alguna variante. "
            "No concluyas que la diversidad causa un cambio de aceptacion o regreso."
        )


def main(argv=None):
    from sqlalchemy import create_engine, text
    from sidequests_analytics.pipeline import (
        compute_bq8, compute_bq8_experienced, store_bq_result,
    )

    parser = argparse.ArgumentParser(description="BQ8: real Supabase results, read-only by default.")
    parser.add_argument("--publish", action="store_true",
                        help="Explicitly store new aggregate BQ8 and BQ8_EXPERIENCED results.")
    parser.add_argument("--dashboard", action="store_true",
                        help="Open Streamlit using the same private local DB connection.")
    args = parser.parse_args(argv)

    print("BQ8 — Supabase > Connect > Session pooler (port 5432).")
    print("Pega la URI PostgreSQL con [YOUR-PASSWORD] y escribe la clave por separado.")
    template = getpass.getpass("URI de conexion: ").strip()
    try:
        target = connection_template(template)
    except ValueError as error:
        print(f"URI invalida: {error}")
        return 1

    engine = None
    phase = "resolve_host"
    try:
        socket.getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM)
        password = getpass.getpass("Password PostgreSQL (no la clave publica de Supabase): ")
        try:
            url = connection_url(template, password)
        finally:
            del template, password
        phase = "connect"
        engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        with engine.connect() as conn:
            conn.execute(text("select 1"))

        phase = "compute"
        # Both compute_* functions perform SELECT queries only.
        legacy = compute_bq8(engine)
        experienced = compute_bq8_experienced(engine)
        summarize(legacy, experienced)
        if args.publish:
            phase = "publish"
            print("\nPublicando SOLO resultados agregados en analytics.bq_results...")
            store_bq_result(engine, "BQ8", legacy)
            store_bq_result(engine, "BQ8_EXPERIENCED", experienced)
            print("Publicacion completada.")
        else:
            print("\nSOLO LECTURA: no se escribio ningun resultado en Supabase.")

        if args.dashboard:
            if not args.publish:
                print("Aviso: el dashboard muestra resultados previamente guardados; "
                      "para ver resultados nuevos debes publicarlos con permiso.")
            phase = "dashboard"
            from streamlit.web import bootstrap
            os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
            print("Dashboard local: http://127.0.0.1:8501 (Ctrl+C para cerrar).")
            bootstrap.run(
                str(Path(__file__).resolve().parents[1] / "dashboard_app.py"),
                False, [], {
                    "server.address": "127.0.0.1",
                    "server.port": 8501,
                    "server.headless": True,
                    "browser.gatherUsageStats": False,
                },
            )
    except Exception as error:
        details = safe_error_details(error, phase, result_stored=False)
        print(f"Error BQ8 en etapa {phase}. Diagnostico: {details['diagnostic']}.")
        print(details["explanation"])
        if details["sqlstate"]:
            print(f"SQLSTATE: {details['sqlstate']}")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        os.environ.pop("DATABASE_URL", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
