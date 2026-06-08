from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

import pyodbc

from app.core.config import settings


def build_connection_string() -> str:
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={settings.db_server};"
        f"DATABASE={settings.db_name};"
        f"UID={settings.db_user};"
        f"PWD={settings.db_password};"
        f"Encrypt={settings.db_encrypt};"
        f"TrustServerCertificate={'yes' if settings.db_trust_server_certificate else 'no'};"
        f"Connection Timeout={settings.db_connection_timeout};"
    )


@contextmanager
def sql_server_connection():
    if not settings.has_database_credentials:
        raise RuntimeError("Database credentials are not configured.")

    connection = pyodbc.connect(build_connection_string(), timeout=settings.db_query_timeout)
    try:
        yield connection
    finally:
        connection.close()


def execute_query(sql: str, parameters: Iterable[Any] | None = None, batch_size: int = 1000) -> tuple[list[str], list[dict[str, Any]]]:
    with sql_server_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(sql, list(parameters or []))

        columns = [column[0] for column in cursor.description or []]
        rows: list[dict[str, Any]] = []

        if columns:
            while True:
                batch = cursor.fetchmany(batch_size)

                if not batch:
                    break

                rows.extend(dict(zip(columns, row)) for row in batch)

        return columns, rows


def execute_scalar(sql: str, parameters: Iterable[Any] | None = None) -> Any:
    with sql_server_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(sql, list(parameters or []))
        row = cursor.fetchone()

        return row[0] if row else None

