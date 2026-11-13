"""Tiendas y bodegas activas, para filtrar la existencia por ubicación."""

from app.core.config import settings
from app.db.sql_server import execute_query
from app.models.query import Tienda
from app.services.query_cache import query_cache
from app.services.query_runner.sql import build_tiendas_sql

TIENDAS_CACHE_KEY = "tiendas_activas_v1"
TIPO_POR_CODIGO = {0: "Bodega", 1: "Tienda"}


def list_tiendas() -> list[Tienda]:
    if not settings.has_database_credentials:
        return []

    cached = query_cache.get(TIENDAS_CACHE_KEY)

    if cached is not None:
        return cached

    _columns, rows = execute_query(build_tiendas_sql())
    tiendas = [
        Tienda(
            codigo=str(row.get("Codigo") or "").strip(),
            nombre=str(row.get("Nombre") or "").strip(),
            zona=str(row.get("Zona") or "").strip(),
            tipo=TIPO_POR_CODIGO.get(_as_int(row.get("Tipo")), "Otro"),
        )
        for row in rows
        if str(row.get("Codigo") or "").strip()
    ]
    query_cache.set(TIENDAS_CACHE_KEY, tiendas)

    return tiendas


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
