from datetime import date, datetime, timedelta
import json
import logging
from threading import Lock, Thread

from app.core.config import settings
from app.db.sql_server import execute_query
from app.models.query import QueryDefinition, QueryResult, UnifiedQueryResult
from app.services.query_catalog import DATABASE_DIR, get_query, load_query_sql
from app.services.query_cache import query_cache
from app.services.unified_snapshot import (
    append_snapshot_rows,
    build_snapshot_id,
    finalize_snapshot,
    get_snapshot_metadata,
    read_snapshot_filtered_page,
    read_snapshot_page,
    reset_snapshot,
)

MAX_PAGE_SIZE = 1000
UNIFIED_SNAPSHOT_CHUNK_SIZE = 500
UNIFIED_FIRST_PAGE_CODE_BATCH_SIZE = 100
SNAPSHOT_READ_BATCH_SIZE = 1000
SNAPSHOT_QUERY_IDS = {"consulta_base", "ventas", "kardex"}
ASYNC_SNAPSHOT_QUERY_IDS = {"kardex"}
DAILY_MATERIALIZED_QUERY_IDS = {"ventas"}
UNIFIED_SOURCE_QUERY_IDS = ["consulta_base", "ventas", "kardex", "transferencias_tiendas"]
COMMON_BARCODES_SNAPSHOT_QUERY_ID = "consulta_unificada_common_barcodes_v3"
UNIFIED_FILTERS = {
    "codigoBarra": ["Codigo Barra", "CodigoBarra"],
    "referencia": ["Referencias", "Referencia"],
    "codigoMarca": ["Codigo Marca", "CodigoMarca"],
    "nombreMarca": ["Nombre Marca", "Marca"],
    "categoria": ["Nombre Categoria", "Codigo Categoria"],
}
UNIFIED_COLUMNS = [
    "Codigo Barra",
    "Referencias",
    "Codigo Marca",
    "Marca",
    "Descripcion",
    "Nombre Marca",
    "Codigo Fabricante",
    "Nombre Fabricante",
    "Codigo Categoria",
    "Nombre Categoria",
    "Codigo Linea",
    "Nombre Linea",
    "Usuarios",
    "Numero de compra",
    "Fecha Factura",
    "Descripcion de compra",
    "Correcciones de compra",
    "Cantidad de compra",
    "Suma Unidades Compras",
    "Existencia actual",
    "Suma Existencia",
    "Porcentaje de existencia%",
    "Unidades vendidas",
    "Suma Cantidades ventas",
    "porcentaje de unidades vendidas%",
    "NumeroFactura",
    "FechaVenta",
    "Tienda",
    "Region",
    "PrecioDetal",
    "CostoDolar",
    "PrecioMayor",
    "PrecioPromocion",
    "Utilidad por ventas",
    "% Utilidad por ventas",
    "Costo Inicial",
    "Kardex Nombre Tienda",
    "Kardex hecid",
    "Kardex dimid fecha movimiento",
    "Kardex Nombre Articulo",
    "Kardex Tipo",
    "Kardex Concepto",
    "Kardex Motivo Ajuste",
    "Kardex Fecha Movimiento",
    "Kardex Documento",
    "Kardex Observacion",
    "Kardex Item",
    "Kardex Referencia",
    "Kardex Codigo Marca",
    "Kardex Cantidad",
    "Kardex Existencia",
    "Kardex Cantidad RM",
    "Kardex Existencia RM",
    "Unidades de Ajustes Positivos",
    "% Ajustes Positivos",
    "Unidades de Ajustes Negativos",
    "% Ajustes Negativos",
    "Utilidad perdida por ajustes",
    "% Utilidad perdida por ajustes",
    "Transferencia matriz",
    "Transferencia sucursal",
    "Codigo envia",
    "Codigo recibe",
    "Fecha emision transferencia",
    "Fecha carga transferencia",
    "Numero transferencia",
    "Tienda kardex transferencia",
]
UNIFIED_BASE_COLUMNS = [
    "Codigo Barra",
    "Referencias",
    "Codigo Marca",
    "Marca",
    "Descripcion",
    "Nombre Marca",
    "Codigo Fabricante",
    "Nombre Fabricante",
    "Codigo Categoria",
    "Nombre Categoria",
    "Codigo Linea",
    "Nombre Linea",
    "Usuarios",
    "Numero de compra",
    "Fecha Factura",
    "Descripcion de compra",
    "Correcciones de compra",
    "Cantidad de compra",
    "Suma Unidades Compras",
]
TRANSFER_COLUMNS = [
    "MATRIZ",
    "SUCURSAL",
    "CodigoEnvia",
    "CodigoRecibe",
    "FechaEmision",
    "FECHACARGATRANSFERENCIA",
    "CodigoBarra",
    "Numero",
    "dimid_tienda",
    "Documento",
    "FechaMovimiento",
    "Tipo",
    "Concepto",
    "Cantidad",
]
SALES_DETAIL_COLUMNS = [
    "Codigo Barra",
    "Existencia actual",
    "Suma Existencia",
    "Unidades vendidas",
    "Suma Cantidades ventas",
    "NumeroFactura",
    "FechaVenta",
    "Tienda",
    "Region",
    "PrecioDetal",
    "CostoDolar",
    "PrecioMayor",
    "PrecioPromocion",
    "Utilidad por ventas",
]
KARDEX_DETAIL_COLUMNS = [
    "Codigo Barra",
    "Costo Inicial",
    "Unidades de Ajustes Positivos",
    "% Ajustes Positivos",
    "Unidades de Ajustes Negativos",
    "% Ajustes Negativos",
    "Utilidad perdida por ajustes",
    "% Utilidad perdida por ajustes",
]
TRANSFER_DETAIL_COLUMNS = [
    "Codigo Barra",
    "Transferencia matriz",
    "Transferencia sucursal",
    "Codigo envia",
    "Codigo recibe",
    "Fecha emision transferencia",
    "Fecha carga transferencia",
    "Numero transferencia",
    "Tienda kardex transferencia",
]

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


def build_transferencias_page_sql() -> str:
    return """
WITH FilteredMTF AS (
    SELECT
          MATRIZ
        , SUCURSAL
        , CodigoEnvia
        , CodigoRecibe
        , FechaEmision
        , FECHACARGATRANSFERENCIA
        , CodigoBarra
        , Numero
    FROM dbo.MOVTRANSFERECIAS_TIENDAS
    WHERE CodigoBarra IS NOT NULL
      AND FechaEmision >= ?
      AND FechaEmision < DATEADD(DAY, 1, ?)
      AND (? IS NULL OR CAST(CodigoBarra AS VARCHAR(50)) = CAST(? AS VARCHAR(50)))
),
NeededPairs AS (
    SELECT DISTINCT
          CodigoBarra
        , CONVERT(VARCHAR(50), Numero) AS DocumentoStr
    FROM FilteredMTF
),
LatestK AS (
    SELECT
          K.dimid_tienda
        , K.Documento
        , K.FechaMovimiento
        , K.Tipo
        , K.Concepto
        , K.Cantidad
        , K.CodigoBarra
        , ROW_NUMBER() OVER (
            PARTITION BY K.CodigoBarra, CONVERT(VARCHAR(50), K.Documento)
            ORDER BY K.FechaMovimiento DESC, K.hecid_kardex DESC
          ) AS rn
    FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
    INNER JOIN NeededPairs AS NP
        ON CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(NP.CodigoBarra AS VARCHAR(50))
       AND CONVERT(VARCHAR(50), K.Documento) = NP.DocumentoStr
),
JoinedTransferencias AS (
    SELECT
          MTF.MATRIZ
        , MTF.SUCURSAL
        , MTF.CodigoEnvia
        , MTF.CodigoRecibe
        , MTF.FechaEmision
        , MTF.FECHACARGATRANSFERENCIA
        , MTF.CodigoBarra
        , MTF.Numero
        , HK.dimid_tienda
        , HK.Documento
        , HK.FechaMovimiento
        , HK.Tipo
        , HK.Concepto
        , HK.Cantidad
        , ROW_NUMBER() OVER (ORDER BY MTF.FechaEmision, MTF.CodigoBarra, MTF.Numero) AS page_row_number
    FROM FilteredMTF AS MTF
    LEFT JOIN LatestK AS HK
        ON CAST(HK.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
       AND CONVERT(VARCHAR(50), HK.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
       AND HK.rn = 1
    WHERE LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'
)
SELECT
      MATRIZ
    , SUCURSAL
    , CodigoEnvia
    , CodigoRecibe
    , FechaEmision
    , FECHACARGATRANSFERENCIA
    , CodigoBarra
    , Numero
    , dimid_tienda
    , Documento
    , FechaMovimiento
    , Tipo
    , Concepto
    , Cantidad
FROM JoinedTransferencias
WHERE page_row_number > ?
  AND page_row_number <= ?
ORDER BY page_row_number
"""


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


def build_distinct_barcode_sql(sql: str) -> str:
    return (
        "SELECT DISTINCT CAST(CodigoBarra AS VARCHAR(50)) AS CodigoBarra "
        f"FROM ({sql}) AS source_query "
        "WHERE CodigoBarra IS NOT NULL"
    )


def load_unified_base_sql() -> str:
    return (DATABASE_DIR / "consulta_base_unificada.sql").read_text(encoding="utf-8")


def get_source_barcode_sql(query_id: str) -> str:
    if query_id == "consulta_base":
        return """
SELECT DISTINCT CAST(M.[CodigoBarra] AS VARCHAR(50)) AS CodigoBarra
FROM [J101010100_999911].[dbo].[COMPRAS] AS C
INNER JOIN [J101010100_999911].[dbo].[MOVCOMPRAS] AS M
    ON C.[Documento] = M.[Documento]
   AND C.[Proveedor] = M.[Proveedor]
WHERE C.IDLote <> 001
  AND C.[Fecha] >= ?
  AND C.[Fecha] < DATEADD(DAY, 1, ?)
  AND M.[CodigoBarra] IS NOT NULL
"""

    if query_id == "ventas":
        return """
SELECT DISTINCT CAST(i.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
FROM dbo.tbHecInventario AS h
INNER JOIN dbo.tbDimInventario AS i
    ON i.dimID_Inventario = h.dimid_inventario
INNER JOIN dbo.tbDimTiendas AS t
    ON t.dimid_tienda = h.dimid_tienda
INNER JOIN dbo.tbHecVentas AS v
    ON v.dimid_inventario = h.dimid_inventario
   AND v.dimid_tienda = h.dimid_tienda
WHERE
    t.dimID_Tienda <> '2010'
    AND v.[FechaVenta] >= ?
    AND v.[FechaVenta] < DATEADD(DAY, 1, ?)
    AND t.Status = 1
    AND t.Tipo = 1
    AND i.CodigoBarra IS NOT NULL
"""

    if query_id == "kardex":
        return """
SELECT DISTINCT CAST(K.[CodigoBarra] AS VARCHAR(50)) AS CodigoBarra
FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
WHERE K.[FechaMovimiento] >= ?
  AND K.[FechaMovimiento] < DATEADD(DAY, 1, ?)
  AND K.[MotivoAjuste] IS NOT NULL
  AND LTRIM(RTRIM(K.[MotivoAjuste])) <> ''
  AND K.[CodigoBarra] IS NOT NULL
"""

    if query_id == "transferencias_tiendas":
        return """
WITH FilteredMTF AS (
    SELECT
          CodigoBarra
        , Numero
        , FechaEmision
    FROM dbo.MOVTRANSFERECIAS_TIENDAS
    WHERE CodigoBarra IS NOT NULL
      AND FechaEmision >= ?
      AND FechaEmision < DATEADD(DAY, 1, ?)
),
NeededPairs AS (
    SELECT DISTINCT
          CodigoBarra
        , CONVERT(VARCHAR(50), Numero) AS DocumentoStr
    FROM FilteredMTF
),
LatestK AS (
    SELECT
          K.CodigoBarra
        , K.Documento
        , K.Concepto
        , ROW_NUMBER() OVER (
            PARTITION BY K.CodigoBarra, CONVERT(VARCHAR(50), K.Documento)
            ORDER BY K.FechaMovimiento DESC, K.hecid_kardex DESC
          ) AS rn
    FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
    INNER JOIN NeededPairs AS NP
        ON CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(NP.CodigoBarra AS VARCHAR(50))
       AND CONVERT(VARCHAR(50), K.Documento) = NP.DocumentoStr
)
SELECT DISTINCT CAST(MTF.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
FROM FilteredMTF AS MTF
INNER JOIN LatestK AS HK
    ON CAST(HK.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
   AND CONVERT(VARCHAR(50), HK.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
   AND HK.rn = 1
WHERE LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'
"""

    raise KeyError(f"Unsupported unified source query: {query_id}")


def get_source_barcode_parameters(query_id: str, fecha_desde: date, fecha_hasta: date) -> list:
    if query_id == "ventas":
        return [fecha_desde, fecha_hasta]
    if query_id in ("consulta_base", "kardex"):
        return [fecha_desde, fecha_hasta]
    if query_id == "transferencias_tiendas":
        return [fecha_desde, fecha_hasta]

    raise KeyError(f"Unsupported unified source query: {query_id}")


def get_common_barcodes(parameters: dict) -> list[str]:
    cache_parameters = get_cache_parameters("consulta_unificada", parameters)
    cache_key = build_cache_key("common_barcodes_v11", "consulta_unificada", cache_parameters)
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

    common_codes: set[str] | None = None
    fecha_desde = parse_date_parameter(cache_parameters.get("fechaDesde"), "fechaDesde")
    fecha_hasta = parse_date_parameter(cache_parameters.get("fechaHasta"), "fechaHasta")

    for source_query_id in UNIFIED_SOURCE_QUERY_IDS:
        ordered_parameters = get_source_barcode_parameters(source_query_id, fecha_desde, fecha_hasta)
        _columns, rows = execute_query(get_source_barcode_sql(source_query_id), ordered_parameters)
        codes = {str(row["CodigoBarra"]) for row in rows if row.get("CodigoBarra") is not None}

        common_codes = codes if common_codes is None else common_codes.intersection(codes)

        if not common_codes:
            break

    result = sorted(common_codes or [])
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


def build_unified_page_codes_sql() -> str:
    return """
WITH CommonCodes AS
(
    SELECT DISTINCT
          CAST(M.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
FROM [J101010100_999911].[dbo].[COMPRAS] AS C
INNER JOIN [J101010100_999911].[dbo].[MOVCOMPRAS] AS M
    ON C.Documento = M.Documento
   AND C.Proveedor = M.Proveedor
WHERE C.IDLote <> 001
  AND C.Fecha >= ?
  AND C.Fecha < DATEADD(DAY, 1, ?)
  AND M.CodigoBarra IS NOT NULL
  AND EXISTS
  (
      SELECT 1
      FROM dbo.tbHecVentas AS V
      INNER JOIN dbo.tbHecInventario AS H
          ON V.dimid_inventario = H.dimid_inventario
         AND V.dimid_tienda = H.dimid_tienda
      INNER JOIN dbo.tbDimInventario AS I
          ON I.dimID_Inventario = H.dimid_inventario
      INNER JOIN dbo.tbDimTiendas AS T
          ON T.dimid_tienda = H.dimid_tienda
      WHERE V.FechaVenta >= ?
        AND V.FechaVenta < DATEADD(DAY, 1, ?)
        AND T.dimID_Tienda <> '2010'
        AND T.Status = 1
        AND T.Tipo = 1
        AND CAST(I.CodigoBarra AS VARCHAR(50)) = CAST(M.CodigoBarra AS VARCHAR(50))
  )
  AND EXISTS
  (
      SELECT 1
      FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
      WHERE K.FechaMovimiento >= ?
        AND K.FechaMovimiento < DATEADD(DAY, 1, ?)
        AND K.MotivoAjuste IS NOT NULL
        AND LTRIM(RTRIM(K.MotivoAjuste)) <> ''
        AND CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(M.CodigoBarra AS VARCHAR(50))
  )
  AND EXISTS
  (
      SELECT 1
      FROM dbo.MOVTRANSFERECIAS_TIENDAS AS MTF
      WHERE MTF.CodigoBarra IS NOT NULL
        AND MTF.FechaEmision >= ?
        AND MTF.FechaEmision < DATEADD(DAY, 1, ?)
        AND CAST(MTF.CodigoBarra AS VARCHAR(50)) = CAST(M.CodigoBarra AS VARCHAR(50))
        AND EXISTS
        (
            SELECT 1
            FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K2
            WHERE CAST(K2.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
              AND CONVERT(VARCHAR(50), K2.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
              AND LOWER(LTRIM(RTRIM(K2.Concepto))) = 'transferencia'
        )
  )
)
SELECT CodigoBarra
FROM CommonCodes
ORDER BY CodigoBarra
OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
"""


def build_unified_base_only_detail_sql(base_sql: str, code_count: int) -> str:
    placeholders = ", ".join(["?"] * code_count)

    return f"""
SELECT
      CAST(CodigoBarra AS VARCHAR(50)) AS [Codigo Barra]
    , Referencia AS [Referencias]
    , CodigoMarca AS [Codigo Marca]
    , marca_detail.NombreMarca AS [Marca]
    , Nombre AS [Descripcion]
    , marca_detail.NombreMarca AS [Nombre Marca]
    , Fabricante AS [Codigo Fabricante]
    , NombreFabricante AS [Nombre Fabricante]
    , CodigoCategoria AS [Codigo Categoria]
    , NombreCategoria AS [Nombre Categoria]
    , CodigoLinea AS [Codigo Linea]
    , NombreLinea AS [Nombre Linea]
    , Usuario AS [Usuarios]
    , Documento AS [Numero de compra]
    , FechaFactura AS [Fecha Factura]
    , Observacion AS [Descripcion de compra]
    , CantidadDevuelta AS [Correcciones de compra]
    , Cantidad AS [Cantidad de compra]
    , [Suma Unidades Compra] AS [Suma Unidades Compras]
FROM ({base_sql}) AS base_query
OUTER APPLY
(
    SELECT TOP 1
          MC.[Nombre] AS NombreMarca
    FROM [J101010100_999911].[dbo].[MARCAS] AS MC
    WHERE CAST(MC.[Codigo] AS VARCHAR(50)) = CAST(base_query.CodigoMarca AS VARCHAR(50))
) AS marca_detail
WHERE CAST(CodigoBarra AS VARCHAR(50)) IN ({placeholders})
ORDER BY CodigoBarra
"""


def build_unified_base_detail_sql(base_sql: str, code_count: int | None) -> str:
    top_clause = "TOP (?) " if code_count is None else ""
    code_filter = ""

    if code_count is not None:
        placeholders = ", ".join(["?"] * code_count)
        code_filter = f"WHERE CAST(CodigoBarra AS VARCHAR(50)) IN ({placeholders})"

    unified_base_sql = base_sql

    return f"""
SELECT {top_clause}
      CAST(CodigoBarra AS VARCHAR(50)) AS [Codigo Barra]
    , Referencia AS [Referencias]
    , CodigoMarca AS [Codigo Marca]
    , marca_detail.NombreMarca AS [Marca]
    , Nombre AS [Descripcion]
    , marca_detail.NombreMarca AS [Nombre Marca]
    , Fabricante AS [Codigo Fabricante]
    , NombreFabricante AS [Nombre Fabricante]
    , CodigoCategoria AS [Codigo Categoria]
    , NombreCategoria AS [Nombre Categoria]
    , CodigoLinea AS [Codigo Linea]
    , NombreLinea AS [Nombre Linea]
    , Usuario AS [Usuarios]
    , Documento AS [Numero de compra]
    , FechaFactura AS [Fecha Factura]
    , Observacion AS [Descripcion de compra]
    , CantidadDevuelta AS [Correcciones de compra]
    , Cantidad AS [Cantidad de compra]
    , [Suma Unidades Compra] AS [Suma Unidades Compras]
    , sales_detail.ExistenciaActual AS [Existencia actual]
    , sales_detail.SumaExistencia AS [Suma Existencia]
    , CASE
        WHEN sales_detail.ExistenciaActual IS NULL OR sales_detail.ExistenciaActual = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(sales_detail.ExistenciaActual AS FLOAT), 0)) * 100
      END AS [Porcentaje de existencia%]
    , sales_detail.UnidadesVendidas AS [Unidades vendidas]
    , sales_detail.UnidadesVendidas AS [Suma Cantidades ventas]
    , CASE
        WHEN sales_detail.UnidadesVendidas IS NULL OR sales_detail.UnidadesVendidas = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(sales_detail.UnidadesVendidas AS FLOAT), 0)) * 100
      END AS [porcentaje de unidades vendidas%]
    , sales_detail.NumeroFactura
    , sales_detail.FechaVenta
    , sales_detail.Tienda
    , sales_detail.Region
    , sales_detail.PrecioDetal
    , sales_detail.CostoDolar
    , sales_detail.PrecioMayor
    , sales_detail.PrecioPromocion
    , kardex_detail.CostoInicial * ISNULL(sales_detail.UnidadesVendidas, 0) AS [Utilidad por ventas]
    , CASE
        WHEN (kardex_detail.CostoInicial * ISNULL(sales_detail.UnidadesVendidas, 0)) = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.CostoInicial * ISNULL(sales_detail.UnidadesVendidas, 0) AS FLOAT), 0)) * 100
      END AS [% Utilidad por ventas]
    , kardex_detail.CostoInicial AS [Costo Inicial]
    , kardex_detail.NombreTienda AS [Kardex Nombre Tienda]
    , kardex_detail.hecid_kardex AS [Kardex hecid]
    , kardex_detail.dimid_fechamovimiento AS [Kardex dimid fecha movimiento]
    , kardex_detail.NombreArticulo AS [Kardex Nombre Articulo]
    , kardex_detail.Tipo AS [Kardex Tipo]
    , kardex_detail.Concepto AS [Kardex Concepto]
    , kardex_detail.MotivoAjuste AS [Kardex Motivo Ajuste]
    , kardex_detail.FechaMovimiento AS [Kardex Fecha Movimiento]
    , kardex_detail.Documento AS [Kardex Documento]
    , kardex_detail.Observacion AS [Kardex Observacion]
    , kardex_detail.Item AS [Kardex Item]
    , kardex_detail.Referencia AS [Kardex Referencia]
    , kardex_detail.CodigoMarca AS [Kardex Codigo Marca]
    , kardex_detail.Cantidad AS [Kardex Cantidad]
    , kardex_detail.Existencia AS [Kardex Existencia]
    , kardex_detail.CantidadRM AS [Kardex Cantidad RM]
    , kardex_detail.ExistenciaRM AS [Kardex Existencia RM]
    , kardex_detail.AjustesPositivos AS [Unidades de Ajustes Positivos]
    , CASE
        WHEN kardex_detail.AjustesPositivos IS NULL OR kardex_detail.AjustesPositivos = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.AjustesPositivos AS FLOAT), 0)) * 100
      END AS [% Ajustes Positivos]
    , kardex_detail.AjustesNegativos AS [Unidades de Ajustes Negativos]
    , CASE
        WHEN kardex_detail.AjustesNegativos IS NULL OR kardex_detail.AjustesNegativos = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.AjustesNegativos AS FLOAT), 0)) * 100
      END AS [% Ajustes Negativos]
    , kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0) AS [Utilidad perdida por ajustes]
    , CASE
        WHEN (kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0)) = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0) AS FLOAT), 0)) * 100
      END AS [% Utilidad perdida por ajustes]
    , transfer_detail.MATRIZ AS [Transferencia matriz]
    , transfer_detail.SUCURSAL AS [Transferencia sucursal]
    , transfer_detail.CodigoEnvia AS [Codigo envia]
    , transfer_detail.CodigoRecibe AS [Codigo recibe]
    , transfer_detail.FechaEmision AS [Fecha emision transferencia]
    , transfer_detail.FECHACARGATRANSFERENCIA AS [Fecha carga transferencia]
    , transfer_detail.Numero AS [Numero transferencia]
    , transfer_detail.dimid_tienda AS [Tienda kardex transferencia]
FROM ({unified_base_sql}) AS base_query
OUTER APPLY
(
    SELECT TOP 1
          MC.[Nombre] AS NombreMarca
    FROM [J101010100_999911].[dbo].[MARCAS] AS MC
    WHERE CAST(MC.[Codigo] AS VARCHAR(50)) = CAST(base_query.CodigoMarca AS VARCHAR(50))
) AS marca_detail
CROSS APPLY
(
    SELECT
          MAX(T.Nombre) AS NombreTienda
        , MAX(K.[hecid_kardex]) AS hecid_kardex
        , MAX(K.[dimid_fechamovimiento]) AS dimid_fechamovimiento
        , MAX(H.[Nombre]) AS NombreArticulo
        , MAX(K.[Tipo]) AS Tipo
        , MAX(K.[Concepto]) AS Concepto
        , MAX(K.[MotivoAjuste]) AS MotivoAjuste
        , MAX(K.[FechaMovimiento]) AS FechaMovimiento
        , MAX(K.[Documento]) AS Documento
        , MAX(K.[Observacion]) AS Observacion
        , MAX(K.[Item]) AS Item
        , MAX(K.[Referencia]) AS Referencia
        , MAX(K.[CodigoMarca]) AS CodigoMarca
        , SUM(ISNULL(K.[Cantidad], 0)) AS Cantidad
        , MAX(I.[CostoInicial]) AS CostoInicial
        , MAX(K.[Existencia]) AS Existencia
        , SUM(ISNULL(K.[CantidadRM], 0)) AS CantidadRM
        , MAX(K.[ExistenciaRM]) AS ExistenciaRM
        , SUM(CASE WHEN LOWER(LTRIM(RTRIM(K.[Tipo]))) = 'entrada' THEN ISNULL(K.[Cantidad], 0) ELSE 0 END) AS AjustesPositivos
        , SUM(CASE WHEN LOWER(LTRIM(RTRIM(K.[Tipo]))) = 'salida' THEN ABS(ISNULL(K.[Cantidad], 0)) ELSE 0 END) AS AjustesNegativos
    FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
    INNER JOIN [BODEGA_DATOS].[dbo].[tbDimTiendas] T
        ON K.[dimid_tienda] = T.[dimid_tienda]
    INNER JOIN [BODEGA_DATOS].[dbo].[tbHecInventario] I
        ON K.[dimid_inventario] = I.[dimid_inventario]
    INNER JOIN [BODEGA_DATOS].[dbo].[tbDimInventario] H
        ON H.[dimid_inventario] = I.[dimid_inventario]
    WHERE K.[FechaMovimiento] >= ?
      AND K.[FechaMovimiento] < DATEADD(DAY, 1, ?)
      AND K.[MotivoAjuste] IS NOT NULL
      AND LTRIM(RTRIM(K.[MotivoAjuste])) <> ''
      AND CAST(K.[CodigoBarra] AS VARCHAR(50)) = CAST(base_query.CodigoBarra AS VARCHAR(50))
    HAVING COUNT_BIG(*) > 0
) AS kardex_detail
CROSS APPLY
(
    SELECT
          MAX(CASE WHEN h.[Existencia] < 0 THEN 0 ELSE h.[Existencia] END) AS ExistenciaActual
        , SUM(CASE WHEN h.[Existencia] < 0 THEN 0 ELSE h.[Existencia] END) AS SumaExistencia
        , SUM(ISNULL(v.[Cantidad], 0)) AS UnidadesVendidas
        , MAX(v.[NumeroFactura]) AS NumeroFactura
        , MAX(v.[FechaVenta]) AS FechaVenta
        , MAX(t.[Nombre]) AS Tienda
        , MAX(t.[Zona]) AS Region
        , MAX(CAST(ROUND(c.[PrecioDetal], 2) AS DECIMAL(18,2))) AS PrecioDetal
        , MAX(CAST(ROUND(c.[CostoInicial], 2) AS DECIMAL(18,2))) AS CostoDolar
        , MAX(CAST(ROUND(c.[PrecioMayor], 2) AS DECIMAL(18,2))) AS PrecioMayor
        , MAX(CAST(ROUND(c.[PrecioPromocion], 2) AS DECIMAL(18,2))) AS PrecioPromocion
    FROM dbo.tbHecInventario AS h
    INNER JOIN dbo.tbDimInventario AS i
        ON i.dimID_Inventario = h.dimid_inventario
    INNER JOIN dbo.tbDimTiendas AS t
        ON t.dimid_tienda = h.dimid_tienda
    INNER JOIN [J101010100_999911].[dbo].[Inventario] AS c
        ON c.CodigoBarra = i.CodigoBarra
    INNER JOIN dbo.tbHecVentas AS v
        ON v.dimid_inventario = h.dimid_inventario
       AND v.dimid_tienda = h.dimid_tienda
    WHERE v.[FechaVenta] >= ?
      AND v.[FechaVenta] < DATEADD(DAY, 1, ?)
      AND t.dimID_Tienda <> '2010'
      AND t.Status = 1
      AND t.Tipo = 1
      AND CAST(i.CodigoBarra AS VARCHAR(50)) = CAST(base_query.CodigoBarra AS VARCHAR(50))
    HAVING COUNT_BIG(*) > 0
) AS sales_detail
CROSS APPLY
(
    SELECT TOP 1
          MTF.MATRIZ
        , MTF.SUCURSAL
        , MTF.CodigoEnvia
        , MTF.CodigoRecibe
        , MTF.FechaEmision
        , MTF.FECHACARGATRANSFERENCIA
        , MTF.Numero
        , HK.dimid_tienda
    FROM dbo.MOVTRANSFERECIAS_TIENDAS AS MTF
    CROSS APPLY
    (
        SELECT TOP 1
              K.dimid_tienda
            , K.Concepto
        FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
        WHERE CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
          AND CONVERT(VARCHAR(50), K.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
        ORDER BY K.FechaMovimiento DESC, K.hecid_kardex DESC
    ) AS HK
    WHERE MTF.CodigoBarra IS NOT NULL
      AND MTF.FechaEmision >= ?
      AND MTF.FechaEmision < DATEADD(DAY, 1, ?)
      AND CAST(MTF.CodigoBarra AS VARCHAR(50)) = CAST(base_query.CodigoBarra AS VARCHAR(50))
      AND LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'
    ORDER BY MTF.FechaEmision DESC, MTF.Numero DESC
) AS transfer_detail
{code_filter}
ORDER BY CodigoBarra
"""


def build_unified_snapshot_exact(fecha_desde: date, fecha_hasta: date) -> tuple[str, list[str], int]:
    cache_parameters = {
        "fechaDesde": fecha_desde.isoformat(),
        "fechaHasta": fecha_hasta.isoformat(),
    }
    snapshot_id = build_snapshot_id("consulta_unificada_full_v7", cache_parameters)
    metadata = get_snapshot_metadata(snapshot_id)

    if metadata is not None:
        columns, total_rows = metadata
        return snapshot_id, columns, total_rows

    reset_snapshot(snapshot_id)

    common_barcodes = get_common_barcodes(cache_parameters)
    base_sql = load_unified_base_sql()
    snapshot_columns = UNIFIED_COLUMNS
    next_row_index = 0

    for index in range(0, len(common_barcodes), UNIFIED_SNAPSHOT_CHUNK_SIZE):
        chunk_codes = common_barcodes[index : index + UNIFIED_SNAPSHOT_CHUNK_SIZE]

        if not chunk_codes:
            continue

        columns, rows = execute_query(
            build_unified_base_detail_sql(base_sql, len(chunk_codes)),
            [
                fecha_desde,
                fecha_hasta,
                fecha_desde,
                fecha_hasta,
                fecha_desde,
                fecha_hasta,
                fecha_desde,
                fecha_hasta,
                *chunk_codes,
            ],
        )
        snapshot_columns = columns or snapshot_columns
        next_row_index = append_snapshot_rows(snapshot_id, next_row_index, rows)

    finalize_snapshot(snapshot_id, cache_parameters, snapshot_columns, next_row_index)

    return snapshot_id, snapshot_columns, next_row_index


def find_cached_unified_range(start_date: date, max_end_date: date) -> tuple[date, str, list[str], int] | None:
    current_end = max_end_date

    while current_end >= start_date:
        cache_parameters = {
            "fechaDesde": start_date.isoformat(),
            "fechaHasta": current_end.isoformat(),
        }
        snapshot_id = build_snapshot_id("consulta_unificada_full_v7", cache_parameters)
        metadata = get_snapshot_metadata(snapshot_id)

        if metadata is not None:
            columns, total_rows = metadata
            return current_end, snapshot_id, columns, total_rows

        current_end -= timedelta(days=1)

    return None


def append_snapshot_from_snapshot(target_snapshot_id: str, source_snapshot_id: str, start_index: int, total_rows: int) -> int:
    next_index = start_index

    for offset in range(0, total_rows, SNAPSHOT_READ_BATCH_SIZE):
        rows = read_snapshot_page(source_snapshot_id, offset, SNAPSHOT_READ_BATCH_SIZE)
        next_index = append_snapshot_rows(target_snapshot_id, next_index, rows)

    return next_index


def build_unified_snapshot_incremental(fecha_desde: date, fecha_hasta: date) -> tuple[str, list[str], int]:
    if fecha_desde == fecha_hasta:
        return build_unified_snapshot_exact(fecha_desde, fecha_hasta)

    cache_parameters = {
        "fechaDesde": fecha_desde.isoformat(),
        "fechaHasta": fecha_hasta.isoformat(),
    }
    snapshot_id = build_snapshot_id("consulta_unificada_full_v7", cache_parameters)
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
        "consulta_unificada_full_v7",
        {
            "fechaDesde": fecha_desde.isoformat(),
            "fechaHasta": fecha_hasta.isoformat(),
        },
    )


def get_result_filters(parameters: dict) -> list[tuple[list[str], str]]:
    filters = []

    for parameter_name, columns in UNIFIED_FILTERS.items():
        value = str(parameters.get(parameter_name) or "").strip()

        if value:
            filters.append((columns, value))

    return filters


def get_unified_result_filters(parameters: dict) -> list[tuple[list[str], str]]:
    return get_result_filters(parameters)


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


def row_matches_result_filters(row: dict, filters: list[tuple[list[str], str]]) -> bool:
    for columns, value in filters:
        normalized_value = value.strip().lower()

        if not normalized_value:
            continue

        if not any(normalized_value in str(row.get(column, "")).lower() for column in columns):
            return False

    return True


def build_unified_base_page(parameters: dict, page: int, page_size: int) -> tuple[list[str], list[dict], int, int, bool]:
    cache_parameters = get_cache_parameters("consulta_unificada", parameters)
    fecha_desde = parse_date_parameter(cache_parameters.get("fechaDesde"), "fechaDesde")
    fecha_hasta = parse_date_parameter(cache_parameters.get("fechaHasta"), "fechaHasta")

    if fecha_hasta < fecha_desde:
        raise ValueError("fechaHasta must be greater than or equal to fechaDesde.")

    normalized_page, normalized_page_size, offset = normalize_pagination(page, page_size)
    base_sql = load_unified_base_sql()
    result_filters = get_unified_result_filters(parameters)
    _code_columns, code_rows = execute_query(
        build_unified_page_codes_sql(),
        [
            fecha_desde,
            fecha_hasta,
            fecha_desde,
            fecha_hasta,
            fecha_desde,
            fecha_hasta,
            fecha_desde,
            fecha_hasta,
            offset,
            normalized_page_size + 1,
        ],
    )
    codes = [str(row["CodigoBarra"]) for row in code_rows if row.get("CodigoBarra") is not None]
    has_more = len(codes) > normalized_page_size
    page_codes = codes[:normalized_page_size]

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


def build_query_snapshot_exact(
    query_id: str,
    definition: QueryDefinition,
    cache_parameters: dict,
    ordered_parameters: list,
) -> tuple[str, list[str], int]:
    snapshot_id = build_snapshot_id(query_id, cache_parameters)

    if query_id == "transferencias_tiendas" and snapshot_id in _building_snapshots:
        return QueryResult(
            queryId=query_id,
            columns=TRANSFER_COLUMNS,
            rows=[],
            rowCount=0,
            totalRows=0,
            page=normalized_page,
            pageSize=normalized_page_size,
            totalPages=1,
            isLoading=True,
            isComplete=False,
        )

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

        if query_id == "transferencias_tiendas":
            return QueryResult(
                queryId=query_id,
                columns=TRANSFER_COLUMNS,
                rows=[],
                rowCount=0,
                totalRows=0,
                page=normalized_page,
                pageSize=normalized_page_size,
                totalPages=1,
                isLoading=True,
                isComplete=False,
            )

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


def group_rows_by_barcode(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}

    for row in rows:
        barcode = row_barcode(row)

        if not barcode:
            continue

        grouped.setdefault(barcode, []).append(row)

    return grouped


def build_kardex_detail_raw_sql() -> str:
    return """
SELECT
      K.[CodigoBarra] AS CodigoBarra
    , K.[Tipo]
    , K.[Cantidad]
    , I.[CostoInicial]
FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
INNER JOIN [BODEGA_DATOS].[dbo].[tbHecInventario] I
    ON K.[dimid_inventario] = I.[dimid_inventario]
WHERE K.[FechaMovimiento] >= ?
  AND K.[MotivoAjuste] IS NOT NULL
  AND LTRIM(RTRIM(K.[MotivoAjuste])) <> ''
  AND (
        ? IS NULL
        OR CAST(K.[CodigoBarra] AS VARCHAR(50)) IN (
            SELECT LTRIM(RTRIM([value]))
            FROM STRING_SPLIT(CAST(? AS VARCHAR(MAX)), ',')
        )
      )
"""


def summarize_sales_detail(rows: list[dict], base_metrics: dict[str, dict]) -> list[dict]:
    grouped = group_rows_by_barcode(rows)
    summaries: list[dict] = []

    for barcode, barcode_rows in grouped.items():
        first_row = barcode_rows[0]
        units_sold = to_float(first_row.get("Suma Cantidades ventas"))

        if units_sold == 0:
            units_sold = sum(to_float(row.get("Cantidad")) for row in barcode_rows)

        sum_existence = to_float(first_row.get("Suma Existencia"))

        if sum_existence == 0:
            sum_existence = sum(to_float(row.get("Existencia")) for row in barcode_rows)

        metric = base_metrics.get(barcode, {})
        initial_cost = to_float(metric.get("costoInicial")) or to_float(first_row.get("CostoDolar"))

        summaries.append(
            {
                "Codigo Barra": barcode,
                "Existencia actual": round_metric(to_float(first_row.get("Existencia"))),
                "Suma Existencia": round_metric(sum_existence),
                "Unidades vendidas": round_metric(units_sold),
                "Suma Cantidades ventas": first_row.get("Suma Cantidades ventas") or units_sold,
                "NumeroFactura": first_row.get("NumeroFactura"),
                "FechaVenta": first_row.get("FechaVenta"),
                "Tienda": first_row.get("Tienda"),
                "Region": first_row.get("Region"),
                "PrecioDetal": first_row.get("PrecioDetal"),
                "CostoDolar": first_row.get("CostoDolar"),
                "PrecioMayor": first_row.get("PrecioMayor"),
                "PrecioPromocion": first_row.get("PrecioPromocion"),
                "Utilidad por ventas": round_metric(initial_cost * units_sold),
            }
        )

    return summaries


def summarize_kardex_detail(rows: list[dict], base_metrics: dict[str, dict]) -> list[dict]:
    grouped = group_rows_by_barcode(rows)
    summaries: list[dict] = []

    for barcode, barcode_rows in grouped.items():
        costo_inicial = to_float(barcode_rows[0].get("CostoInicial"))
        metric = base_metrics.get(barcode, {})
        cantidad_compra = to_float(metric.get("cantidadCompra"))
        ajustes_positivos = sum(
            to_float(row.get("Cantidad"))
            for row in barcode_rows
            if str(row.get("Tipo") or "").strip().lower() == "entrada"
        )
        ajustes_negativos = sum(
            abs(to_float(row.get("Cantidad")))
            for row in barcode_rows
            if str(row.get("Tipo") or "").strip().lower() == "salida"
        )
        utilidad_perdida = costo_inicial * ajustes_negativos

        summaries.append(
            {
                "Codigo Barra": barcode,
                "Costo Inicial": round_metric(costo_inicial),
                "Unidades de Ajustes Positivos": round_metric(ajustes_positivos),
                "% Ajustes Positivos": round_metric(cantidad_compra / ajustes_positivos) if ajustes_positivos else "",
                "Unidades de Ajustes Negativos": round_metric(ajustes_negativos),
                "% Ajustes Negativos": round_metric(cantidad_compra / ajustes_negativos) if ajustes_negativos else "",
                "Utilidad perdida por ajustes": round_metric(utilidad_perdida),
                "% Utilidad perdida por ajustes": round_metric(cantidad_compra / utilidad_perdida) if utilidad_perdida else "",
            }
        )

    return summaries


def summarize_transfer_detail(rows: list[dict]) -> list[dict]:
    grouped = group_rows_by_barcode(rows)
    summaries: list[dict] = []

    for barcode, barcode_rows in grouped.items():
        first_row = barcode_rows[0]
        summaries.append(
            {
                "Codigo Barra": barcode,
                "Transferencia matriz": first_row.get("MATRIZ"),
                "Transferencia sucursal": first_row.get("SUCURSAL"),
                "Codigo envia": first_row.get("CodigoEnvia"),
                "Codigo recibe": first_row.get("CodigoRecibe"),
                "Fecha emision transferencia": first_row.get("FechaEmision"),
                "Fecha carga transferencia": first_row.get("FECHACARGATRANSFERENCIA"),
                "Numero transferencia": first_row.get("Numero"),
                "Tienda kardex transferencia": first_row.get("dimid_tienda"),
            }
        )

    return summaries


def run_unified_detail_query(query_id: str, parameters: dict, page: int = 1, page_size: int = 200) -> QueryResult:
    normalized_page, normalized_page_size, _offset = normalize_pagination(page, page_size)
    base_metrics = parse_base_metrics(parameters)

    if query_id == "kardex":
        fecha_desde = parse_date_parameter(parameters.get("fechaDesde"), "fechaDesde")
        barcode_filter = get_barcode_filter_parameter(parameters)
        _columns, raw_rows = execute_query(build_kardex_detail_raw_sql(), [fecha_desde, barcode_filter, barcode_filter])
        columns = KARDEX_DETAIL_COLUMNS
        rows = summarize_kardex_detail(raw_rows, base_metrics)
    elif query_id == "ventas":
        definition = get_query("ventas")
        raw_columns, raw_rows = execute_query(load_query_sql(definition), build_ordered_parameters(definition, parameters))
        columns = SALES_DETAIL_COLUMNS
        rows = summarize_sales_detail(raw_rows, base_metrics)
    elif query_id == "transferencias_tiendas":
        definition = get_query("transferencias_tiendas")
        raw_columns, raw_rows = execute_query(load_query_sql(definition), build_ordered_parameters(definition, parameters))
        columns = TRANSFER_DETAIL_COLUMNS
        rows = summarize_transfer_detail(raw_rows)
    else:
        raise KeyError(f"Query not supported for unified detail: {query_id}")

    total_rows = len(rows)
    total_pages = max(1, (total_rows + normalized_page_size - 1) // normalized_page_size)
    offset = (normalized_page - 1) * normalized_page_size
    page_rows = rows[offset : offset + normalized_page_size]

    return QueryResult(
        queryId=query_id,
        columns=columns,
        rows=page_rows,
        rowCount=len(page_rows),
        totalRows=total_rows,
        page=normalized_page,
        pageSize=normalized_page_size,
        totalPages=total_pages,
        isLoading=False,
        isComplete=normalized_page >= total_pages,
    )


def get_first_value(row: dict, columns: list[str]) -> str:
    for column in columns:
        value = row.get(column)

        if value not in (None, ""):
            return str(value)

    return "Sin dato"


def numeric_value(value) -> float:
    if value in (None, ""):
        return 0

    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0


def build_chart_items(counts: dict[str, float], limit: int = 8) -> list[dict]:
    sorted_items = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    max_value = max((value for _label, value in sorted_items), default=1)

    return [
        {
            "label": label,
            "value": value,
            "percent": max(4, (value / max_value) * 100) if max_value else 0,
        }
        for label, value in sorted_items
    ]


def add_count(counts: dict[str, float], label: str, value: float = 1) -> None:
    counts[label] = counts.get(label, 0) + value


def iter_snapshot_rows(snapshot_id: str, total_rows: int, batch_size: int = 1000):
    for offset in range(0, total_rows, batch_size):
        for row in read_snapshot_page(snapshot_id, offset, batch_size):
            yield row


def build_dashboard_summary(parameters: dict) -> dict:
    query_ids = ["consulta_base", "ventas", "kardex", "consulta_unificada"]
    rows_by_endpoint: dict[str, float] = {}
    category_counts: dict[str, float] = {}
    brand_counts: dict[str, float] = {}
    metrics = {
        "totalRows": 0,
        "endpoints": 0,
        "soldUnits": 0,
        "positiveAdjustments": 0,
        "negativeAdjustments": 0,
    }

    for query_id in query_ids:
        if query_id == "consulta_unificada":
            snapshot_id, _columns, total_rows = build_unified_snapshot(parameters)
            query_name = "Consulta unificada"
        else:
            definition = get_query(query_id)
            ordered_parameters = build_ordered_parameters(definition, parameters)
            snapshot_id, _columns, total_rows = build_query_snapshot(query_id, definition, parameters, ordered_parameters)
            query_name = definition.name

        metrics["totalRows"] += total_rows
        metrics["endpoints"] += 1
        add_count(rows_by_endpoint, query_name, total_rows)

        for row in iter_snapshot_rows(snapshot_id, total_rows):
            add_count(category_counts, get_first_value(row, ["Nombre Categoria", "NombreCategoria", "Codigo Categoria", "CodigoCategoria"]))
            add_count(brand_counts, get_first_value(row, ["Nombre Marca", "NombreMarca", "Marca", "Codigo Marca", "CodigoMarca"]))
            metrics["soldUnits"] += numeric_value(row.get("Unidades vendidas") or row.get("Cantidad"))
            metrics["positiveAdjustments"] += numeric_value(row.get("Unidades de Ajustes Positivos"))
            metrics["negativeAdjustments"] += numeric_value(row.get("Unidades de Ajustes Negativos"))

    return {
        "metrics": metrics,
        "charts": {
            "rowsByEndpoint": build_chart_items(rows_by_endpoint),
            "categories": build_chart_items(category_counts),
            "brands": build_chart_items(brand_counts),
        },
    }


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
