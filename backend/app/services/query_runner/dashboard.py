"""Resumen y gráficas del dashboard a partir de los snapshots."""

from app.services.query_catalog import get_query
from app.services.query_runner.common import build_ordered_parameters
from app.services.query_runner.snapshots import build_query_snapshot
from app.services.query_runner.unified import build_unified_snapshot
from app.services.unified_snapshot import read_snapshot_page


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
