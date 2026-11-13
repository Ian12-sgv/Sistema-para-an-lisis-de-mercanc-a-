"""Consulta unificada: códigos de barras comunes, página base y snapshots completos."""

from datetime import date, timedelta
from threading import Thread

from app.core.config import settings
from app.db.sql_server import execute_query
from app.models.query import QueryResult
from app.services.query_cache import query_cache
from app.services.query_runner.columns import UNIFIED_BASE_COLUMNS, UNIFIED_COLUMNS
from app.services.query_runner.common import (
    COMMON_BARCODES_SNAPSHOT_QUERY_ID,
    SNAPSHOT_READ_BATCH_SIZE,
    _building_snapshots,
    _snapshot_build_lock,
    build_cache_key,
    get_cache_parameters,
    get_unified_result_filters,
    logger,
    normalize_pagination,
    parse_date_parameter,
    row_matches_result_filters,
)
from app.services.query_runner.snapshots import append_snapshot_from_snapshot
from app.services.query_runner.sql import (
    build_unified_base_only_detail_sql,
    build_unified_common_codes_sql,
    build_unified_full_sql,
    load_unified_base_sql,
)

UNIFIED_FULL_SNAPSHOT_QUERY_ID = "consulta_unificada_full_v10"
from app.services.unified_snapshot import (
    append_snapshot_rows,
    build_snapshot_id,
    finalize_snapshot,
    get_snapshot_metadata,
    read_snapshot_page,
    reset_snapshot,
)


def get_common_barcodes(parameters: dict) -> list[str]:
    """Códigos de la unificada para el rango, persistidos en un snapshot para no recalcularlos."""
    cache_parameters = get_cache_parameters("consulta_unificada", parameters)
    cache_key = build_cache_key("common_barcodes_v12", "consulta_unificada", cache_parameters)
    cached_codes = query_cache.get(cache_key)

    if cached_codes is not None:
        return cached_codes

    common_codes_snapshot_id = build_snapshot_id(COMMON_BARCODES_SNAPSHOT_QUERY_ID, cache_parameters)
    metadata = get_snapshot_metadata(common_codes_snapshot_id)

    if metadata is not None:
        _columns, total_rows = metadata
        result = []

        for offset in range(0, total_rows, SNAPSHOT_READ_BATCH_SIZE):
            rows = read_snapshot_page(common_codes_snapshot_id, offset, SNAPSHOT_READ_BATCH_SIZE)
            result.extend(str(row["CodigoBarra"]) for row in rows if row.get("CodigoBarra") is not None)

        query_cache.set(cache_key, result)
        return result

    fecha_desde = parse_date_parameter(cache_parameters.get("fechaDesde"), "fechaDesde")
    fecha_hasta = parse_date_parameter(cache_parameters.get("fechaHasta"), "fechaHasta")
    result = list(get_unified_common_codes(fecha_desde, fecha_hasta))
    reset_snapshot(common_codes_snapshot_id)
    next_row_index = append_snapshot_rows(
        common_codes_snapshot_id,
        0,
        [{"CodigoBarra": code} for code in result],
    )
    finalize_snapshot(
        common_codes_snapshot_id,
        cache_parameters,
        ["CodigoBarra"],
        next_row_index,
    )
    query_cache.set(cache_key, result)

    return result


def build_unified_snapshot_exact(fecha_desde: date, fecha_hasta: date) -> tuple[str, list[str], int]:
    cache_parameters = {
        "fechaDesde": fecha_desde.isoformat(),
        "fechaHasta": fecha_hasta.isoformat(),
    }
    snapshot_id = build_snapshot_id(UNIFIED_FULL_SNAPSHOT_QUERY_ID, cache_parameters)
    metadata = get_snapshot_metadata(snapshot_id)

    if metadata is not None:
        columns, total_rows = metadata
        return snapshot_id, columns, total_rows

    reset_snapshot(snapshot_id)

    # Una sola consulta para todo el rango: los pasos con tablas temporales ya limitan
    # el trabajo a los códigos que cumplen la regla, así que no hace falta trocear por códigos.
    columns, rows = execute_query(
        build_unified_full_sql(load_unified_base_sql()),
        [fecha_desde, fecha_hasta, fecha_desde, fecha_hasta],
    )
    snapshot_columns = columns or UNIFIED_COLUMNS
    next_row_index = append_snapshot_rows(snapshot_id, 0, rows)

    finalize_snapshot(snapshot_id, cache_parameters, snapshot_columns, next_row_index)

    return snapshot_id, snapshot_columns, next_row_index


def find_cached_unified_range(start_date: date, max_end_date: date) -> tuple[date, str, list[str], int] | None:
    current_end = max_end_date

    while current_end >= start_date:
        cache_parameters = {
            "fechaDesde": start_date.isoformat(),
            "fechaHasta": current_end.isoformat(),
        }
        snapshot_id = build_snapshot_id(UNIFIED_FULL_SNAPSHOT_QUERY_ID, cache_parameters)
        metadata = get_snapshot_metadata(snapshot_id)

        if metadata is not None:
            columns, total_rows = metadata
            return current_end, snapshot_id, columns, total_rows

        current_end -= timedelta(days=1)

    return None


def build_unified_snapshot_incremental(fecha_desde: date, fecha_hasta: date) -> tuple[str, list[str], int]:
    if fecha_desde == fecha_hasta:
        return build_unified_snapshot_exact(fecha_desde, fecha_hasta)

    cache_parameters = {
        "fechaDesde": fecha_desde.isoformat(),
        "fechaHasta": fecha_hasta.isoformat(),
    }
    snapshot_id = build_snapshot_id(UNIFIED_FULL_SNAPSHOT_QUERY_ID, cache_parameters)
    metadata = get_snapshot_metadata(snapshot_id)

    if metadata is not None:
        columns, total_rows = metadata
        return snapshot_id, columns, total_rows

    reset_snapshot(snapshot_id)

    snapshot_columns = UNIFIED_COLUMNS
    next_row_index = 0
    current_date = fecha_desde

    while current_date <= fecha_hasta:
        cached_range = find_cached_unified_range(current_date, fecha_hasta)

        if cached_range is None:
            source_snapshot_id, columns, total_rows = build_unified_snapshot_exact(current_date, current_date)
            range_end = current_date
        else:
            range_end, source_snapshot_id, columns, total_rows = cached_range

        snapshot_columns = columns or snapshot_columns
        next_row_index = append_snapshot_from_snapshot(snapshot_id, source_snapshot_id, next_row_index, total_rows)
        current_date = range_end + timedelta(days=1)

    finalize_snapshot(snapshot_id, cache_parameters, snapshot_columns, next_row_index)

    return snapshot_id, snapshot_columns, next_row_index


def build_unified_snapshot(parameters: dict) -> tuple[str, list[str], int]:
    cache_parameters = get_cache_parameters("consulta_unificada", parameters)
    fecha_desde = parse_date_parameter(cache_parameters.get("fechaDesde"), "fechaDesde")
    fecha_hasta = parse_date_parameter(cache_parameters.get("fechaHasta"), "fechaHasta")

    if fecha_hasta < fecha_desde:
        raise ValueError("fechaHasta must be greater than or equal to fechaDesde.")

    return build_unified_snapshot_exact(fecha_desde, fecha_hasta)


def get_unified_snapshot_id(parameters: dict) -> str:
    cache_parameters = get_cache_parameters("consulta_unificada", parameters)
    fecha_desde = parse_date_parameter(cache_parameters.get("fechaDesde"), "fechaDesde")
    fecha_hasta = parse_date_parameter(cache_parameters.get("fechaHasta"), "fechaHasta")

    if fecha_hasta < fecha_desde:
        raise ValueError("fechaHasta must be greater than or equal to fechaDesde.")

    return build_snapshot_id(
        UNIFIED_FULL_SNAPSHOT_QUERY_ID,
        {
            "fechaDesde": fecha_desde.isoformat(),
            "fechaHasta": fecha_hasta.isoformat(),
        },
    )


def _build_unified_snapshot_background(snapshot_id: str, parameters: dict) -> None:
    try:
        build_unified_snapshot(parameters)
    except Exception:
        logger.exception("Background unified snapshot generation failed")
    finally:
        with _snapshot_build_lock:
            _building_snapshots.discard(snapshot_id)


def start_unified_snapshot_background(snapshot_id: str, parameters: dict) -> None:
    with _snapshot_build_lock:
        if snapshot_id in _building_snapshots:
            return

        _building_snapshots.add(snapshot_id)
        Thread(
            target=_build_unified_snapshot_background,
            args=(snapshot_id, parameters),
            daemon=True,
        ).start()


def get_unified_common_codes(fecha_desde: date, fecha_hasta: date) -> list[str]:
    """Códigos comunes del rango, calculados una vez y reutilizados por todas las páginas.

    Antes cada página volvía a ejecutar la consulta completa con OFFSET; SQL Server
    tenía que calcular todo el conjunto igualmente, así que paginar costaba lo mismo que la página 1.
    """
    cache_key = build_cache_key(
        "unified_common_codes_v2",
        "consulta_unificada",
        {"fechaDesde": fecha_desde.isoformat(), "fechaHasta": fecha_hasta.isoformat()},
    )
    cached_codes = query_cache.get(cache_key)

    if cached_codes is not None:
        return cached_codes

    _columns, code_rows = execute_query(
        build_unified_common_codes_sql(),
        [fecha_desde, fecha_hasta],
    )
    codes = [str(row["CodigoBarra"]) for row in code_rows if row.get("CodigoBarra") is not None]
    query_cache.set(cache_key, codes)

    return codes


def build_unified_base_page(parameters: dict, page: int, page_size: int) -> tuple[list[str], list[dict], int, int, bool]:
    cache_parameters = get_cache_parameters("consulta_unificada", parameters)
    fecha_desde = parse_date_parameter(cache_parameters.get("fechaDesde"), "fechaDesde")
    fecha_hasta = parse_date_parameter(cache_parameters.get("fechaHasta"), "fechaHasta")

    if fecha_hasta < fecha_desde:
        raise ValueError("fechaHasta must be greater than or equal to fechaDesde.")

    normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)
    base_sql = load_unified_base_sql()
    result_filters = get_unified_result_filters(parameters)
    codes = get_unified_common_codes(fecha_desde, fecha_hasta)
    has_more = len(codes) > offset + normalized_page_size
    page_codes = codes[offset : offset + normalized_page_size]

    if not page_codes:
        return UNIFIED_BASE_COLUMNS, [], offset, normalized_page, False

    columns, fetched_rows = execute_query(
        build_unified_base_only_detail_sql(base_sql, len(page_codes)),
        [
            fecha_desde,
            fecha_hasta,
            *page_codes,
        ],
    )
    rows = [
        row
        for row in fetched_rows
        if not result_filters or row_matches_result_filters(row, result_filters)
    ]

    page_rows = rows[:normalized_page_size]
    estimated_total_rows = offset + len(page_rows) + (1 if has_more else 0)
    total_pages = normalized_page + 1 if has_more else normalized_page

    return columns or UNIFIED_BASE_COLUMNS, page_rows, estimated_total_rows, total_pages, has_more


def build_unified_first_page(parameters: dict, page_size: int) -> tuple[list[str], list[dict], int, int, bool]:
    return build_unified_base_page(parameters, 1, page_size)


def run_unified_query(parameters: dict, page: int = 1, page_size: int = 200) -> QueryResult:
    normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)

    if not settings.has_database_credentials:
        return QueryResult(
            queryId="consulta_unificada",
            columns=["estado", "detalle"],
            rows=[
                {
                    "estado": "sin_conexion",
                    "detalle": "Configura .env y conecta la VPN para ejecutar esta consulta.",
                }
            ],
            rowCount=1,
            totalRows=1,
            page=normalized_page,
            pageSize=normalized_page_size,
            totalPages=1,
            isLoading=False,
            isComplete=True,
        )

    columns, rows, estimated_total_rows, total_pages, has_more = build_unified_base_page(
        parameters,
        normalized_page,
        normalized_page_size,
    )

    return QueryResult(
        queryId="consulta_unificada",
        columns=columns or UNIFIED_BASE_COLUMNS,
        rows=rows,
        rowCount=len(rows),
        totalRows=estimated_total_rows,
        page=normalized_page,
        pageSize=normalized_page_size,
        totalPages=total_pages,
        isLoading=False,
        isComplete=not has_more,
    )
