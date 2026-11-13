"""Constantes, parámetros, paginación, caché y filtros compartidos."""

from datetime import date, datetime
import json
import logging
from threading import Lock

from app.db.sql_server import execute_query
from app.models.query import QueryDefinition


MAX_PAGE_SIZE = 1000
UNIFIED_FIRST_PAGE_CODE_BATCH_SIZE = 100
SNAPSHOT_READ_BATCH_SIZE = 1000
SNAPSHOT_QUERY_IDS = {"consulta_base", "ventas", "kardex"}
ASYNC_SNAPSHOT_QUERY_IDS = {"kardex"}
DAILY_MATERIALIZED_QUERY_IDS = {"ventas"}
COMMON_BARCODES_SNAPSHOT_QUERY_ID = "consulta_unificada_common_barcodes_v4"
UNIFIED_FILTERS = {
    "codigoBarra": ["Codigo Barra", "CodigoBarra"],
    "referencia": ["Referencias", "Referencia"],
    "codigoMarca": ["Codigo Marca", "CodigoMarca"],
    "nombreMarca": ["Nombre Marca", "Marca"],
    "categoria": ["Nombre Categoria", "Codigo Categoria"],
}


logger = logging.getLogger(__name__)
_snapshot_build_lock = Lock()
_building_snapshots: set[str] = set()


def parse_date_parameter(value, parameter_name: str) -> date:
    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        raise ValueError(f"Invalid date parameter: {parameter_name}")

    normalized_value = value.strip()

    for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(normalized_value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Invalid date format for {parameter_name}. Use YYYY-MM-DD.")


def get_barcode_filter_parameter(parameters: dict) -> str | None:
    codigo_barras = str(parameters.get("codigoBarras") or "").strip()

    if codigo_barras:
        return codigo_barras

    codigo_barra = str(parameters.get("codigoBarra") or "").strip()

    return codigo_barra or None


def parse_base_metrics(parameters: dict) -> dict[str, dict]:
    raw_metrics = parameters.get("baseMetrics")

    if isinstance(raw_metrics, dict):
        return raw_metrics

    if not isinstance(raw_metrics, str) or not raw_metrics.strip():
        return {}

    try:
        parsed = json.loads(raw_metrics)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def row_barcode(row: dict) -> str:
    value = row.get("Codigo Barra", row.get("CodigoBarra"))
    return str(value or "").strip()


def to_float(value) -> float:
    if value in (None, ""):
        return 0

    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0


def round_metric(value) -> float:
    return round(value, 2)


def build_ordered_parameters(definition: QueryDefinition, parameters: dict) -> list:
    if definition.id == "ventas":
        fecha_desde = parameters.get("fechaDesde")
        fecha_hasta = parameters.get("fechaHasta")
        codigo_barra = get_barcode_filter_parameter(parameters)

        if not fecha_desde:
            raise ValueError("Missing required parameter: fechaDesde")
        if not fecha_hasta:
            raise ValueError("Missing required parameter: fechaHasta")

        return [
            parse_date_parameter(fecha_desde, "fechaDesde"),
            parse_date_parameter(fecha_hasta, "fechaHasta"),
            codigo_barra,
            codigo_barra,
        ]

    ordered_parameters = []

    for parameter in definition.parameters:
        value = parameters.get(parameter.name)

        if parameter.required and (value is None or value == ""):
            raise ValueError(f"Missing required parameter: {parameter.name}")

        if value not in (None, "") and parameter.type == "date":
            value = parse_date_parameter(value, parameter.name)

        ordered_parameters.append(value)

    if definition.id in {"kardex", "transferencias_tiendas"}:
        codigo_barra = get_barcode_filter_parameter(parameters)
        ordered_parameters.extend([codigo_barra, codigo_barra])

    return ordered_parameters


def normalize_pagination(page: int, page_size: int) -> tuple[int, int, int]:
    normalized_page = max(1, page)
    normalized_page_size = min(MAX_PAGE_SIZE, max(1, page_size))
    offset = (normalized_page - 1) * normalized_page_size

    return normalized_page, normalized_page_size, offset


def build_count_sql(sql: str) -> str:
    return f"SELECT COUNT(1) AS totalRows FROM ({sql}) AS query_source"


def build_page_sql(sql: str, order_by: str) -> str:
    return f"{sql}\nORDER BY {order_by}\nOFFSET ? ROWS FETCH NEXT ? ROWS ONLY"


def execute_estimated_page(
    sql: str,
    order_by: str,
    ordered_parameters: list,
    normalized_page: int,
    normalized_page_size: int,
    offset: int,
    is_loading: bool = False,
) -> tuple[list[str], list[dict], int, int, bool, bool]:
    page_sql = build_page_sql(sql, order_by)
    columns, fetched_rows = execute_query(page_sql, [*ordered_parameters, offset, normalized_page_size + 1])
    has_next_page = len(fetched_rows) > normalized_page_size
    rows = fetched_rows[:normalized_page_size]
    estimated_total_rows = offset + len(rows) + (1 if has_next_page else 0)
    total_pages = normalized_page + 1 if has_next_page else normalized_page

    return columns, rows, estimated_total_rows, total_pages, has_next_page, is_loading


def build_cache_key(kind: str, query_id: str, parameters: dict, page: int | None = None, page_size: int | None = None) -> str:
    payload = {
        "kind": kind,
        "queryId": query_id,
        "parameters": parameters,
        "page": page,
        "pageSize": page_size,
    }

    return json.dumps(payload, default=str, sort_keys=True)


def get_cache_parameters(query_id: str, parameters: dict) -> dict:
    if query_id == "consulta_unificada":
        return {
            "fechaDesde": parameters.get("fechaDesde"),
            "fechaHasta": parameters.get("fechaHasta"),
        }

    if query_id == "ventas":
        barcode_filter = get_barcode_filter_parameter(parameters)
        return {
            "fechaDesde": parameters.get("fechaDesde"),
            "fechaHasta": parameters.get("fechaHasta"),
            "codigoBarra": barcode_filter or "",
        }

    if query_id == "kardex":
        barcode_filter = get_barcode_filter_parameter(parameters)
        return {
            "fechaDesde": parameters.get("fechaDesde"),
            "codigoBarra": barcode_filter or "",
        }

    if query_id == "consulta_base":
        return {
            "fechaDesde": "2024-01-01",
            "fechaHasta": date.today().isoformat(),
        }

    if query_id == "transferencias_tiendas":
        barcode_filter = get_barcode_filter_parameter(parameters)
        return {
            "fechaDesde": parameters.get("fechaDesde"),
            "fechaHasta": parameters.get("fechaHasta"),
            "codigoBarra": barcode_filter or "",
        }

    return parameters


def get_result_filters(parameters: dict) -> list[tuple[list[str], str]]:
    filters = []

    for parameter_name, columns in UNIFIED_FILTERS.items():
        value = str(parameters.get(parameter_name) or "").strip()

        if value:
            filters.append((columns, value))

    return filters


def get_unified_result_filters(parameters: dict) -> list[tuple[list[str], str]]:
    return get_result_filters(parameters)


def row_matches_result_filters(row: dict, filters: list[tuple[list[str], str]]) -> bool:
    for columns, value in filters:
        normalized_value = value.strip().lower()

        if not normalized_value:
            continue

        if not any(normalized_value in str(row.get(column, "")).lower() for column in columns):
            return False

    return True
