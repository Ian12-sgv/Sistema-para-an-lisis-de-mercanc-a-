from pathlib import Path

from app.models.query import QueryDefinition, QueryParameter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATABASE_DIR = PROJECT_ROOT / "database"

QUERY_CATALOG: dict[str, QueryDefinition] = {
    "consulta_base": QueryDefinition(
        id="consulta_base",
        name="Consulta base",
        description="Compras desde el 01/01/2024 hasta la actualidad con datos de inventario, color, fabricante y categorias.",
        sql_file="consulta_base.sql",
        orderBy="C.[Fecha], C.[Documento], C.[Proveedor], M.[CodigoBarra]",
        requires_connection=True,
        parameters=[],
    ),
    "ventas": QueryDefinition(
        id="ventas",
        name="Ventas",
        description="Ventas por rango de fechas con existencia, tienda, region y precios.",
        sql_file="ventas.sql",
        orderBy="v.[FechaVenta], v.[NumeroFactura], i.[CodigoBarra]",
        requires_connection=True,
        parameters=[
            QueryParameter(name="fechaDesde", label="Fecha desde", type="date", required=True),
            QueryParameter(name="fechaHasta", label="Fecha hasta", type="date", required=True),
        ],
    ),
    "kardex": QueryDefinition(
        id="kardex",
        name="Kardex",
        description="Movimientos de kardex con motivo de ajuste desde una fecha inicial.",
        sql_file="kardex.sql",
        orderBy="K.[CodigoBarra]",
        requires_connection=True,
        parameters=[
            QueryParameter(name="fechaDesde", label="Fecha desde", type="date", required=True),
        ],
    ),
    "transferencias_tiendas": QueryDefinition(
        id="transferencias_tiendas",
        name="Transferencias tiendas",
        description="Transferencias entre tiendas cruzadas con kardex por codigo de barra y documento.",
        sql_file="transferencias_tiendas.sql",
        orderBy="MTF.FechaEmision, MTF.CodigoBarra, MTF.Numero",
        requires_connection=True,
        parameters=[
            QueryParameter(name="fechaDesde", label="Fecha desde", type="date", required=True),
            QueryParameter(name="fechaHasta", label="Fecha hasta", type="date", required=True),
        ],
    ),
    "consulta_unificada": QueryDefinition(
        id="consulta_unificada",
        name="Consulta unificada",
        description="Codigos de barra presentes en consulta base, kardex y transferencias. Ventas se consulta por articulo.",
        sql_file="",
        orderBy="CodigoBarra",
        requires_connection=True,
        parameters=[
            QueryParameter(name="fechaDesde", label="Fecha desde", type="date", required=True),
            QueryParameter(name="fechaHasta", label="Fecha hasta", type="date", required=True),
        ],
    ),
}


def list_queries() -> list[QueryDefinition]:
    return list(QUERY_CATALOG.values())


def get_query(query_id: str) -> QueryDefinition:
    if query_id not in QUERY_CATALOG:
        raise KeyError(f"Query not found: {query_id}")

    return QUERY_CATALOG[query_id]


def load_query_sql(definition: QueryDefinition) -> str:
    sql_path = DATABASE_DIR / definition.sql_file

    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    return sql_path.read_text(encoding="utf-8")
