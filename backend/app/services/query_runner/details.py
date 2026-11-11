"""Detalle por fuente (ventas, kardex, transferencias) para los códigos de la unificada."""

from app.db.sql_server import execute_query
from app.models.query import QueryResult
from app.services.query_catalog import get_query, load_query_sql
from app.services.query_runner.columns import (
    KARDEX_DETAIL_COLUMNS,
    SALES_DETAIL_COLUMNS,
    TRANSFER_DETAIL_COLUMNS,
)
from app.services.query_runner.common import (
    build_ordered_parameters,
    get_barcode_filter_parameter,
    normalize_pagination,
    parse_base_metrics,
    parse_date_parameter,
    round_metric,
    row_barcode,
    to_float,
)
from app.services.query_runner.sql import build_kardex_detail_raw_sql


def group_rows_by_barcode(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}

    for row in rows:
        barcode = row_barcode(row)

        if not barcode:
            continue

        grouped.setdefault(barcode, []).append(row)

    return grouped


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
