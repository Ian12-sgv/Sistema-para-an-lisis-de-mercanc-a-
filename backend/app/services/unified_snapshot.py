from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from threading import Lock
from uuid import uuid4

try:
    import duckdb
except ImportError:  # pragma: no cover - handled at runtime with a clear message.
    duckdb = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DIR = PROJECT_ROOT / ".cache"
SNAPSHOT_DB = SNAPSHOT_DIR / "unified_summaries.sqlite3"
SNAPSHOT_PARQUET_DIR = SNAPSHOT_DIR / "parquet_snapshots"
SNAPSHOT_TMP_DIR = SNAPSHOT_DIR / "tmp"
SNAPSHOT_VERSION = "query_snapshot_duckdb_parquet_v1"

_db_lock = Lock()


def build_snapshot_id(query_id: str, parameters: dict) -> str:
    payload = json.dumps(
        {
            "version": SNAPSHOT_VERSION,
            "queryId": query_id,
            "parameters": parameters,
        },
        default=str,
        sort_keys=True,
    )

    return sha256(payload.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SNAPSHOT_DB)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


def _require_duckdb():
    if duckdb is None:
        raise RuntimeError("DuckDB no esta instalado. Ejecuta: backend\\.venv\\Scripts\\python.exe -m pip install -e backend")

    return duckdb


def _snapshot_path(snapshot_id: str) -> Path:
    return SNAPSHOT_PARQUET_DIR / snapshot_id


def _quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    return str(value)


def ensure_schema() -> None:
    with _db_lock:
        with _connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS unified_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    parameters_json TEXT NOT NULL,
                    columns_json TEXT NOT NULL,
                    total_rows INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    storage_format TEXT NOT NULL DEFAULT 'parquet'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS unified_snapshot_rows (
                    snapshot_id TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    row_json TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, row_index)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_unified_snapshot_rows_page
                ON unified_snapshot_rows (snapshot_id, row_index)
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(unified_snapshots)").fetchall()
            }
            if "storage_format" not in columns:
                connection.execute(
                    """
                    ALTER TABLE unified_snapshots
                    ADD COLUMN storage_format TEXT NOT NULL DEFAULT 'sqlite'
                    """
                )


def get_snapshot_metadata(snapshot_id: str) -> tuple[list[str], int] | None:
    ensure_schema()

    with _db_lock:
        with _connect() as connection:
            row = connection.execute(
                """
                SELECT columns_json, total_rows
                FROM unified_snapshots
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()

    if row is None:
        return None

    return json.loads(row[0]), int(row[1])


def _read_parquet_page(snapshot_id: str, offset: int, page_size: int) -> list[dict]:
    _require_duckdb()
    snapshot_path = _snapshot_path(snapshot_id)
    parquet_glob = snapshot_path / "*.parquet"

    if not snapshot_path.exists() or not any(snapshot_path.glob("*.parquet")):
        return []

    sql = f"""
        SELECT *
        FROM read_parquet('{_quote_path(parquet_glob)}', union_by_name=true)
        ORDER BY __row_index
        LIMIT ? OFFSET ?
    """

    with duckdb.connect(database=":memory:") as connection:
        result = connection.execute(sql, [page_size, offset])
        columns = [column[0] for column in result.description or []]
        rows = result.fetchall()

    return [
        {column: value for column, value in zip(columns, row) if column != "__row_index"}
        for row in rows
    ]


def _read_sqlite_page(snapshot_id: str, offset: int, page_size: int) -> list[dict]:
    with _db_lock:
        with _connect() as connection:
            rows = connection.execute(
                """
                SELECT row_json
                FROM unified_snapshot_rows
                WHERE snapshot_id = ?
                ORDER BY row_index
                LIMIT ? OFFSET ?
                """,
                (snapshot_id, page_size, offset),
            ).fetchall()

    return [json.loads(row[0]) for row in rows]


def read_snapshot_page(snapshot_id: str, offset: int, page_size: int) -> list[dict]:
    ensure_schema()

    if (_snapshot_path(snapshot_id)).exists():
        return _read_parquet_page(snapshot_id, offset, page_size)

    return _read_sqlite_page(snapshot_id, offset, page_size)


def _build_filter_predicates(filters: list[tuple[list[str], str]]) -> tuple[str, list[str]]:
    predicates = []
    values = []

    for columns, value in filters:
        normalized_value = value.strip().lower()

        if not normalized_value:
            continue

        column_predicates = []
        for column in columns:
            escaped_column = column.replace('"', '""')
            column_predicates.append(f"LOWER(CAST(\"{escaped_column}\" AS VARCHAR)) LIKE ?")
            values.append(f"%{normalized_value}%")

        if column_predicates:
            predicates.append(f"({' OR '.join(column_predicates)})")

    if not predicates:
        return "", []

    return f"WHERE {' AND '.join(predicates)}", values


def read_snapshot_filtered_page(
    snapshot_id: str,
    filters: list[tuple[list[str], str]],
    offset: int,
    page_size: int,
) -> tuple[list[dict], int]:
    ensure_schema()
    snapshot_path = _snapshot_path(snapshot_id)

    if not snapshot_path.exists() or not any(snapshot_path.glob("*.parquet")):
        rows = _read_sqlite_page(snapshot_id, 0, 1_000_000)
        filtered_rows = rows

        for columns, value in filters:
            normalized_value = value.strip().lower()
            if not normalized_value:
                continue

            filtered_rows = [
                row
                for row in filtered_rows
                if any(normalized_value in str(row.get(column, "")).lower() for column in columns)
            ]

        return filtered_rows[offset : offset + page_size], len(filtered_rows)

    _require_duckdb()
    parquet_glob = snapshot_path / "*.parquet"

    with duckdb.connect(database=":memory:") as connection:
        result = connection.execute(
            f"SELECT * FROM read_parquet('{_quote_path(parquet_glob)}', union_by_name=true) LIMIT 0"
        )
        existing_columns = [column[0] for column in result.description or []]

        effective_filters: list[tuple[list[str], str]] = []
        for columns, value in filters:
            supported_columns = [column for column in columns if column in existing_columns]
            if supported_columns:
                effective_filters.append((supported_columns, value))

        where_sql, values = _build_filter_predicates(effective_filters)
        rows_sql = f"""
            SELECT *
            FROM read_parquet('{_quote_path(parquet_glob)}', union_by_name=true)
            {where_sql}
            ORDER BY __row_index
            LIMIT ? OFFSET ?
        """
        count_sql = f"""
            SELECT COUNT(*) AS total_rows
            FROM read_parquet('{_quote_path(parquet_glob)}', union_by_name=true)
            {where_sql}
        """

        count_result = connection.execute(count_sql, values).fetchone()
        total_rows = int(count_result[0] if count_result else 0)
        result = connection.execute(rows_sql, [*values, page_size, offset])
        columns = [column[0] for column in result.description or []]
        rows = result.fetchall()

    return (
        [
            {column: value for column, value in zip(columns, row) if column != "__row_index"}
            for row in rows
        ],
        total_rows,
    )


def reset_snapshot(snapshot_id: str) -> None:
    ensure_schema()

    with _db_lock:
        with _connect() as connection:
            connection.execute("DELETE FROM unified_snapshot_rows WHERE snapshot_id = ?", (snapshot_id,))
            connection.execute("DELETE FROM unified_snapshots WHERE snapshot_id = ?", (snapshot_id,))

    snapshot_path = _snapshot_path(snapshot_id)
    if snapshot_path.exists():
        shutil.rmtree(snapshot_path)


def append_snapshot_rows(snapshot_id: str, start_index: int, rows: list[dict]) -> int:
    ensure_schema()

    if not rows:
        return start_index

    _require_duckdb()
    snapshot_path = _snapshot_path(snapshot_id)
    snapshot_path.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_TMP_DIR.mkdir(parents=True, exist_ok=True)

    tmp_json = SNAPSHOT_TMP_DIR / f"{snapshot_id}_{start_index}_{uuid4().hex}.ndjson"
    parquet_path = snapshot_path / f"part_{start_index:012d}.parquet"

    with tmp_json.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(rows):
            normalized_row = {"__row_index": start_index + index, **row}
            handle.write(json.dumps(normalized_row, default=_json_default, ensure_ascii=False))
            handle.write("\n")

    try:
        with duckdb.connect(database=":memory:") as connection:
            connection.execute(
                f"""
                COPY (
                    SELECT *
                    FROM read_json_auto('{_quote_path(tmp_json)}', format='newline_delimited')
                )
                TO '{_quote_path(parquet_path)}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
    finally:
        tmp_json.unlink(missing_ok=True)

    return start_index + len(rows)


def finalize_snapshot(snapshot_id: str, parameters: dict, columns: list[str], total_rows: int) -> None:
    ensure_schema()
    created_at = datetime.now(timezone.utc).isoformat()
    parameters_json = json.dumps(parameters, default=str, sort_keys=True)
    columns_json = json.dumps(columns, ensure_ascii=False)

    with _db_lock:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO unified_snapshots
                    (snapshot_id, parameters_json, columns_json, total_rows, created_at, storage_format)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, parameters_json, columns_json, total_rows, created_at, "parquet"),
            )


def write_snapshot(snapshot_id: str, parameters: dict, columns: list[str], rows: list[dict]) -> None:
    reset_snapshot(snapshot_id)
    next_index = append_snapshot_rows(snapshot_id, 0, rows)
    finalize_snapshot(snapshot_id, parameters, columns, next_index)
