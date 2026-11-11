"""Consulta paginada de transferencias entre tiendas, con prefetch de la página siguiente."""

from threading import Thread

from app.core.config import settings
from app.db.sql_server import execute_query
from app.models.query import QueryResult
from app.services.query_cache import query_cache
from app.services.query_catalog import get_query
from app.services.query_runner.common import (
    build_cache_key,
    build_ordered_parameters,
    logger,
    normalize_pagination,
)
from app.services.query_runner.sql import build_transferencias_page_sql


def run_transferencias_query(parameters: dict, page: int = 1, page_size: int = 200) -> QueryResult:
    normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)
    ordered_parameters = build_ordered_parameters(get_query("transferencias_tiendas"), parameters)

    if not settings.has_database_credentials:
        return QueryResult(
            queryId="transferencias_tiendas",
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

    page_cache_key = build_cache_key(
        "transfer_page",
        "transferencias_tiendas",
        parameters,
        normalized_page,
        normalized_page_size,
    )
    cached_page = query_cache.get(page_cache_key)

    if cached_page is None:
        columns, fetched_rows = execute_query(
            build_transferencias_page_sql(),
            [*ordered_parameters, offset, offset + normalized_page_size + 1],
        )
        has_next_page = len(fetched_rows) > normalized_page_size
        rows = fetched_rows[:normalized_page_size]
        query_cache.set(page_cache_key, (columns, rows, has_next_page))

        if has_next_page:
            Thread(
                target=prefetch_transferencias_page,
                args=(parameters, normalized_page + 1, normalized_page_size),
                daemon=True,
            ).start()
    else:
        columns, rows, has_next_page = cached_page

    estimated_total_rows = offset + len(rows) + (1 if has_next_page else 0)
    total_pages = normalized_page + 1 if has_next_page else normalized_page

    return QueryResult(
        queryId="transferencias_tiendas",
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


def prefetch_transferencias_page(parameters: dict, page: int, page_size: int) -> None:
    try:
        ordered_parameters = build_ordered_parameters(get_query("transferencias_tiendas"), parameters)
        normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)
        cache_key = build_cache_key(
            "transfer_page",
            "transferencias_tiendas",
            parameters,
            normalized_page,
            normalized_page_size,
        )

        if query_cache.get(cache_key) is not None:
            return

        columns, fetched_rows = execute_query(
            build_transferencias_page_sql(),
            [*ordered_parameters, offset, offset + normalized_page_size + 1],
        )
        has_next_page = len(fetched_rows) > normalized_page_size
        rows = fetched_rows[:normalized_page_size]
        query_cache.set(cache_key, (columns, rows, has_next_page))
    except Exception:
        logger.exception("Transferencias prefetch failed for page=%s", page)
