from datetime import date, datetime

from app.models.query import QueryResult


def test_query_result_formats_date_values_as_year_month_day():
    result = QueryResult(
        queryId="ventas",
        columns=["FechaVenta", "FechaFactura", "Nombre"],
        rows=[
            {
                "FechaVenta": datetime(2026, 5, 15, 15, 20, 0),
                "FechaFactura": date(2026, 5, 14),
                "Nombre": "Articulo",
            },
            {
                "FechaVenta": "2026-05-16T00:00:00",
                "FechaFactura": "2026-05-17",
                "Nombre": "Articulo 2",
            },
        ],
        rowCount=2,
        totalRows=2,
    )

    assert result.rows == [
        {
            "FechaVenta": "2026-05-15",
            "FechaFactura": "2026-05-14",
            "Nombre": "Articulo",
        },
        {
            "FechaVenta": "2026-05-16",
            "FechaFactura": "2026-05-17",
            "Nombre": "Articulo 2",
        },
    ]
