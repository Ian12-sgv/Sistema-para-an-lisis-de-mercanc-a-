"""Snapshots Parquet de consultas individuales (exactos y materializados por día)."""

from datetime import timedelta
from threading import Thread

from app.core.config import settings
from app.db.sql_server import execute_query
from app.models.query import QueryDefinition, QueryResult, SnapshotStatus
from app.services.query_catalog import get_query, load_query_sql
from app.services.query_runner.common import (
    ASYNC_SNAPSHOT_QUERY_IDS,
    DAILY_MATERIALIZED_QUERY_IDS,
    MAX_PAGE_SIZE,
    SNAPSHOT_QUERY_IDS,
    SNAPSHOT_READ_BATCH_SIZE,
    _building_snapshots,
    _snapshot_build_lock,
    build_ordered_parameters,
    build_page_sql,
    execute_estimated_page,
    get_cache_parameters,
    get_result_filters,
    logger,
    normalize_pagination,
    parse_date_parameter,
)
from app.services.unified_snapshot import (
    append_snapshot_rows,
    build_snapshot_id,
    finalize_snapshot,
    get_snapshot_metadata,
    read_snapshot_filtered_page,
    read_snapshot_page,
    reset_snapshot,
)


def append_snapshot_from_snapshot(target_snapshot_id: str, source_snapshot_id: str, start_index: int, total_rows: int) -> int:
    next_index = start_index

    for offset in range(0, total_rows, SNAPSHOT_READ_BATCH_SIZE):
        rows = read_snapshot_page(source_snapshot_id, offset, SNAPSHOT_READ_BATCH_SIZE)
        next_index = append_snapshot_rows(target_snapshot_id, next_index, rows)

    return next_index


def build_query_snapshot_exact(
    query_id: str,
    definition: QueryDefinition,
    cache_parameters: dict,
    ordered_parameters: list,
) -> tuple[str, list[str], int]:
    snapshot_id = build_snapshot_id(query_id, cache_parameters)
    metadata = get_snapshot_metadata(snapshot_id)

    if metadata is not None:
        columns, total_rows = metadata
        return snapshot_id, columns, total_rows

    reset_snapshot(snapshot_id)

    sql = load_query_sql(definition)
    page_sql = build_page_sql(sql, definition.order_by)
    offset = 0
    snapshot_columns: list[str] = []
    next_row_index = 0

    while True:
        columns, fetched_rows = execute_query(page_sql, [*ordered_parameters, offset, MAX_PAGE_SIZE + 1])
        rows = fetched_rows[:MAX_PAGE_SIZE]
        has_next_page = len(fetched_rows) > MAX_PAGE_SIZE

        if columns:
            snapshot_columns = columns

        next_row_index = append_snapshot_rows(snapshot_id, next_row_index, rows)

        if not has_next_page or not rows:
            break

        offset += MAX_PAGE_SIZE

    finalize_snapshot(snapshot_id, cache_parameters, snapshot_columns, next_row_index)

    return snapshot_id, snapshot_columns, next_row_index


def can_materialize_query_by_day(query_id: str, cache_parameters: dict) -> bool:
    if query_id not in DAILY_MATERIALIZED_QUERY_IDS:
        return False

    return bool(cache_parameters.get("fechaDesde") and cache_parameters.get("fechaHasta"))


def build_query_snapshot_daily(
    query_id: str,
    definition: QueryDefinition,
    parameters: dict,
) -> tuple[str, list[str], int]:
    cache_parameters = get_cache_parameters(query_id, parameters)

    if not can_materialize_query_by_day(query_id, cache_parameters):
        return build_query_snapshot_exact(
            query_id,
            definition,
            cache_parameters,
            build_ordered_parameters(definition, parameters),
        )

    fecha_desde = parse_date_parameter(cache_parameters.get("fechaDesde"), "fechaDesde")
    fecha_hasta = parse_date_parameter(cache_parameters.get("fechaHasta"), "fechaHasta")

    if fecha_hasta < fecha_desde:
        raise ValueError("fechaHasta must be greater than or equal to fechaDesde.")

    if fecha_desde == fecha_hasta:
        daily_parameters = {
            **parameters,
            "fechaDesde": fecha_desde.isoformat(),
            "fechaHasta": fecha_desde.isoformat(),
        }
        daily_cache_parameters = get_cache_parameters(query_id, daily_parameters)
        daily_ordered_parameters = build_ordered_parameters(definition, daily_parameters)
        return build_query_snapshot_exact(query_id, definition, daily_cache_parameters, daily_ordered_parameters)

    snapshot_id = build_snapshot_id(query_id, cache_parameters)
    metadata = get_snapshot_metadata(snapshot_id)

    if metadata is not None:
        columns, total_rows = metadata
        return snapshot_id, columns, total_rows

    reset_snapshot(snapshot_id)

    snapshot_columns: list[str] = []
    next_row_index = 0
    current_date = fecha_desde

    while current_date <= fecha_hasta:
        daily_parameters = {
            **parameters,
            "fechaDesde": current_date.isoformat(),
            "fechaHasta": current_date.isoformat(),
        }
        daily_cache_parameters = get_cache_parameters(query_id, daily_parameters)
        daily_ordered_parameters = build_ordered_parameters(definition, daily_parameters)
        daily_snapshot_id, columns, total_rows = build_query_snapshot_exact(
            query_id,
            definition,
            daily_cache_parameters,
            daily_ordered_parameters,
        )

        snapshot_columns = columns or snapshot_columns
        next_row_index = append_snapshot_from_snapshot(snapshot_id, daily_snapshot_id, next_row_index, total_rows)
        current_date += timedelta(days=1)

    finalize_snapshot(snapshot_id, cache_parameters, snapshot_columns, next_row_index)

    return snapshot_id, snapshot_columns, next_row_index


def build_query_snapshot(
    query_id: str,
    definition: QueryDefinition,
    parameters: dict,
    ordered_parameters: list,
) -> tuple[str, list[str], int]:
    cache_parameters = get_cache_parameters(query_id, parameters)

    if can_materialize_query_by_day(query_id, cache_parameters):
        return build_query_snapshot_daily(query_id, definition, parameters)

    return build_query_snapshot_exact(query_id, definition, cache_parameters, ordered_parameters)


def run_query_from_snapshot(query_id: str, parameters: dict, page: int, page_size: int, background_tasks: object | None = None) -> QueryResult:
    definition = get_query(query_id)
    normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)

    ordered_parameters = build_ordered_parameters(definition, parameters)

    if not settings.has_database_credentials:
        return QueryResult(
            queryId=query_id,
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

    cache_parameters = get_cache_parameters(query_id, parameters)
    snapshot_id = build_snapshot_id(query_id, cache_parameters)
    metadata = get_snapshot_metadata(snapshot_id)

    if metadata is not None:
        columns, total_rows = metadata
        result_filters = get_result_filters(parameters)

        if result_filters:
            rows, total_rows = read_snapshot_filtered_page(snapshot_id, result_filters, offset, normalized_page_size)
        else:
            rows = read_snapshot_page(snapshot_id, offset, normalized_page_size)

        total_pages = max(1, (total_rows + normalized_page_size - 1) // normalized_page_size)

        return QueryResult(
            queryId=query_id,
            columns=columns,
            rows=rows,
            rowCount=len(rows),
            totalRows=total_rows,
            page=normalized_page,
            pageSize=normalized_page_size,
            totalPages=total_pages,
            isLoading=False,
            isComplete=normalized_page >= total_pages,
        )

    if can_materialize_query_by_day(query_id, cache_parameters):
        with _snapshot_build_lock:
            if snapshot_id not in _building_snapshots:
                _building_snapshots.add(snapshot_id)
                Thread(
                    target=_build_query_snapshot_background,
                    args=(snapshot_id, query_id, definition, parameters, ordered_parameters),
                    daemon=True,
                ).start()

        sql = load_query_sql(definition)
        columns, rows, estimated_total_rows, total_pages, has_next_page, _is_loading = execute_estimated_page(
            sql,
            definition.order_by,
            ordered_parameters,
            normalized_page,
            normalized_page_size,
            offset,
            is_loading=True,
        )

        return QueryResult(
            queryId=query_id,
            columns=columns,
            rows=rows,
            rowCount=len(rows),
            totalRows=estimated_total_rows,
            page=normalized_page,
            pageSize=normalized_page_size,
            totalPages=total_pages,
            isLoading=True,
            isComplete=not has_next_page,
        )

    if query_id in ASYNC_SNAPSHOT_QUERY_IDS:
        with _snapshot_build_lock:
            if snapshot_id not in _building_snapshots:
                _building_snapshots.add(snapshot_id)
                Thread(
                    target=_build_query_snapshot_background,
                    args=(snapshot_id, query_id, definition, parameters, ordered_parameters),
                    daemon=True,
                ).start()

        sql = load_query_sql(definition)
        columns, rows, estimated_total_rows, total_pages, has_next_page, _is_loading = execute_estimated_page(
            sql,
            definition.order_by,
            ordered_parameters,
            normalized_page,
            normalized_page_size,
            offset,
            is_loading=True,
        )

        return QueryResult(
            queryId=query_id,
            columns=columns,
            rows=rows,
            rowCount=len(rows),
            totalRows=estimated_total_rows,
            page=normalized_page,
            pageSize=normalized_page_size,
            totalPages=total_pages,
            isLoading=True,
            isComplete=not has_next_page,
        )

    sql = load_query_sql(definition)
    columns, rows, estimated_total_rows, total_pages, has_next_page, _is_loading = execute_estimated_page(
        sql,
        definition.order_by,
        ordered_parameters,
        normalized_page,
        normalized_page_size,
        offset,
    )

    return QueryResult(
        queryId=query_id,
        columns=columns,
        rows=rows,
        rowCount=len(rows),
        totalRows=estimated_total_rows,
        page=normalized_page,
        pageSize=normalized_page_size,
        totalPages=total_pages,
        isLoading=False,
        isComplete=not has_next_page,
    )


def _build_query_snapshot_background(snapshot_id: str, query_id: str, definition: QueryDefinition, parameters: dict, ordered_parameters: list) -> None:
    try:
        build_query_snapshot(query_id, definition, parameters, ordered_parameters)
    except Exception:
        logger.exception("Background snapshot generation failed for query_id=%s", query_id)
    finally:
        with _snapshot_build_lock:
            _building_snapshots.discard(snapshot_id)


def get_query_snapshot_status(query_id: str, parameters: dict) -> SnapshotStatus:
    """Estado del snapshot sin consultar SQL Server: solo lee el estado en memoria y los metadatos locales.

    ready=False y building=False significa que la construcción falló o nunca empezó.
    """
    get_query(query_id)

    if query_id not in SNAPSHOT_QUERY_IDS:
        return SnapshotStatus(queryId=query_id, ready=True, building=False)

    snapshot_id = build_snapshot_id(query_id, get_cache_parameters(query_id, parameters))

    # Leer "building" antes que "ready": si la construcción termina entre ambas lecturas,
    # el resultado es ready=True y no un falso fallo.
    with _snapshot_build_lock:
        building = snapshot_id in _building_snapshots

    ready = get_snapshot_metadata(snapshot_id) is not None

    return SnapshotStatus(queryId=query_id, ready=ready, building=building and not ready)
