"""Punto de entrada: decide cómo ejecutar cada consulta y unifica resultados."""

from threading import Thread

from app.core.config import settings
from app.models.query import QueryResult, UnifiedQueryResult
from app.services.query_cache import query_cache
from app.services.query_catalog import get_query, load_query_sql
from app.services.query_runner.common import (
    SNAPSHOT_QUERY_IDS,
    build_cache_key,
    build_ordered_parameters,
    execute_estimated_page,
    logger,
    normalize_pagination,
)
from app.services.query_runner.details import run_unified_detail_query
from app.services.query_runner.snapshots import run_query_from_snapshot
from app.services.query_runner.transferencias import run_transferencias_query
from app.services.query_runner.unified import run_unified_query


def run_query(query_id: str, parameters: dict, page: int = 1, page_size: int = 200, background_tasks: object | None = None) -> QueryResult:
    if parameters.get("detalleUnificada") and query_id in {"ventas", "kardex", "transferencias_tiendas"}:
        return run_unified_detail_query(query_id, parameters, page, page_size)

    if query_id == "consulta_unificada":
        return run_unified_query(parameters, page, page_size)

    if query_id == "transferencias_tiendas":
        return run_transferencias_query(parameters, page, page_size)

    if query_id in SNAPSHOT_QUERY_IDS:
        return run_query_from_snapshot(query_id, parameters, page, page_size, background_tasks)

    definition = get_query(query_id)
    sql = load_query_sql(definition)
    ordered_parameters = build_ordered_parameters(definition, parameters)
    normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)

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

    page_cache_key = build_cache_key("page", query_id, parameters, normalized_page, normalized_page_size)
    cached_page = query_cache.get(page_cache_key)

    if cached_page is None:
        columns, rows, _estimated_total_rows, _total_pages, has_next_page, _is_loading = execute_estimated_page(
            sql,
            definition.order_by,
            ordered_parameters,
            normalized_page,
            normalized_page_size,
            offset,
        )
        query_cache.set(page_cache_key, (columns, rows, has_next_page))

        if query_id == "transferencias_tiendas" and has_next_page:
            Thread(
                target=prefetch_page_cache,
                args=(query_id, parameters, normalized_page + 1, normalized_page_size),
                daemon=True,
            ).start()
    else:
        columns, rows, has_next_page = cached_page

    estimated_total_rows = offset + len(rows) + (1 if has_next_page else 0)
    total_pages = normalized_page + 1 if has_next_page else normalized_page

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


def prefetch_page_cache(query_id: str, parameters: dict, page: int, page_size: int) -> None:
    try:
        definition = get_query(query_id)
        ordered_parameters = build_ordered_parameters(definition, parameters)
        normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)
        cache_key = build_cache_key("page", query_id, parameters, normalized_page, normalized_page_size)

        if query_cache.get(cache_key) is not None:
            return

        sql = load_query_sql(definition)
        columns, rows, _estimated_total_rows, _total_pages, has_next_page, _is_loading = execute_estimated_page(
            sql,
            definition.order_by,
            ordered_parameters,
            normalized_page,
            normalized_page_size,
            offset,
        )
        query_cache.set(cache_key, (columns, rows, has_next_page))
    except Exception:
        logger.exception("Page prefetch failed for query_id=%s page=%s", query_id, page)


def prefetch_next_page(query_id: str, parameters: dict, page: int, page_size: int) -> None:
    try:
        run_query(query_id, parameters, page + 1, page_size)
    except Exception:
        return


def unify_queries(query_ids: list[str], parameters: dict) -> UnifiedQueryResult:
    results = [run_query(query_id, parameters) for query_id in query_ids]
    all_columns = sorted({column for result in results for column in result.columns})

    unified_rows = []
    for result in results:
        for row in result.rows:
            unified_row = {column: row.get(column) for column in all_columns}
            unified_row["_queryId"] = result.query_id
            unified_rows.append(unified_row)

    columns = ["_queryId", *all_columns]

    return UnifiedQueryResult(
        results=results,
        columns=columns,
        rows=unified_rows,
        rowCount=len(unified_rows),
    )
