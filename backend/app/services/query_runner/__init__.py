"""Ejecución, caché y unificación de consultas SQL Server.

Módulos:
- dispatcher: punto de entrada (run_query, unify_queries).
- unified: consulta unificada por código de barras.
- snapshots: snapshots Parquet de consultas individuales.
- transferencias: consulta paginada de transferencias entre tiendas.
- details: detalle por fuente para la unificada.
- dashboard: resumen y gráficas.
- sql: SQL generado en Python.
- common / columns: utilidades y constantes compartidas.

Para sustituir dependencias en pruebas (monkeypatch), parchear el submódulo
donde se usan, por ejemplo `unified.execute_query`, no este paquete.
"""

from app.services.query_cache import query_cache
from app.services.query_runner.common import (
    COMMON_BARCODES_SNAPSHOT_QUERY_ID,
    build_ordered_parameters,
    get_cache_parameters,
)
from app.services.query_runner.dashboard import build_dashboard_summary
from app.services.query_runner.dispatcher import run_query, unify_queries
from app.services.query_runner.snapshots import get_query_snapshot_status
from app.services.query_runner.sql import (
    build_transferencias_page_sql,
    build_unified_full_sql,
)
from app.services.query_runner.unified import (
    build_unified_first_page,
    build_unified_snapshot,
    get_common_barcodes,
    run_unified_query,
)

__all__ = [
    "COMMON_BARCODES_SNAPSHOT_QUERY_ID",
    "build_dashboard_summary",
    "build_ordered_parameters",
    "build_transferencias_page_sql",
    "build_unified_full_sql",
    "build_unified_first_page",
    "build_unified_snapshot",
    "get_cache_parameters",
    "get_common_barcodes",
    "get_query_snapshot_status",
    "query_cache",
    "run_query",
    "run_unified_query",
    "unify_queries",
]
