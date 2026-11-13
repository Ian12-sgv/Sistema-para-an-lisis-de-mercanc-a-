from app.api.routes.tiendas import get_tiendas
from app.services import query_runner, tiendas
from app.services.query_runner import details
from app.services.query_runner import sql as unified_sql

# Ventas de un codigo en dos tiendas: la tienda 1036 aparece en 3 ventas.
# Antes la existencia de esa tienda se sumaba 3 veces.
VENTAS_ROWS = [
    {"CodigoBarra": "111", "Existencia": 10, "Suma Existencia": 37, "Cantidad": 1, "Suma Cantidades ventas": 4, "Tienda": "SUC A"},
    {"CodigoBarra": "111", "Existencia": 10, "Suma Existencia": 37, "Cantidad": 1, "Suma Cantidades ventas": 4, "Tienda": "SUC A"},
    {"CodigoBarra": "111", "Existencia": 10, "Suma Existencia": 37, "Cantidad": 1, "Suma Cantidades ventas": 4, "Tienda": "SUC A"},
    {"CodigoBarra": "111", "Existencia": 7, "Suma Existencia": 37, "Cantidad": 1, "Suma Cantidades ventas": 4, "Tienda": "SUC B"},
]
# Existencia real por tienda/bodega (una fila por tienda, sin repetir).
EXISTENCIA_ROWS = [
    {"CodigoBarra": "111", "CodigoTienda": "1036", "NombreTienda": "SUC LA CHICA", "TipoTienda": 1, "Existencia": 10},
    {"CodigoBarra": "111", "CodigoTienda": "1011", "NombreTienda": "SUC CALIDOSO LIBERTAD", "TipoTienda": 1, "Existencia": 7},
    {"CodigoBarra": "111", "CodigoTienda": "2010", "NombreTienda": "BODEGA CREACION", "TipoTienda": 0, "Existencia": 50},
    {"CodigoBarra": "111", "CodigoTienda": "2008", "NombreTienda": "BODEGA PANTY", "TipoTienda": 0, "Existencia": 0},
]


def run_sales_detail(monkeypatch, extra_parameters: dict) -> tuple[dict, list]:
    calls = []

    def fake_execute_query(sql, params):
        calls.append({"sql": sql, "params": params})
        if "CodigoTienda" in sql:
            return list(EXISTENCIA_ROWS[0].keys()), EXISTENCIA_ROWS
        return list(VENTAS_ROWS[0].keys()), VENTAS_ROWS

    monkeypatch.setattr(details, "execute_query", fake_execute_query)

    result = query_runner.run_query(
        "ventas",
        {
            "fechaDesde": "2026-05-01",
            "fechaHasta": "2026-05-31",
            "detalleUnificada": "1",
            "codigoBarras": "111",
            **extra_parameters,
        },
        page=1,
        page_size=100,
    )
    return result.rows[0], calls


def test_without_store_filter_existence_is_total_of_stores_and_warehouses(monkeypatch):
    row, calls = run_sales_detail(monkeypatch, {})

    # 10 + 7 + 50 (bodega incluida), cada tienda una sola vez.
    assert row["Suma Existencia"] == 67.0
    assert row["Existencia actual"] == 67.0
    # Nombres de mayor a menor; las que tienen 0 no aparecen.
    assert row["Existencia por tienda"] == "BODEGA CREACION: 50 | SUC LA CHICA: 10 | SUC CALIDOSO LIBERTAD: 7"
    assert calls[-1]["params"] == ["111"]


def test_one_store_filter_shows_existence_in_that_store(monkeypatch):
    row, _calls = run_sales_detail(monkeypatch, {"tiendaExistencia": "2010"})

    assert row["Existencia actual"] == 50.0
    assert row["Suma Existencia"] == 67.0
    assert row["Existencia por tienda"] == "BODEGA CREACION: 50"


def test_several_stores_and_warehouses_are_added_and_named(monkeypatch):
    row, _calls = run_sales_detail(monkeypatch, {"tiendaExistencia": "2010,1011"})

    assert row["Existencia actual"] == 57.0
    assert row["Suma Existencia"] == 67.0
    assert row["Existencia por tienda"] == "BODEGA CREACION: 50 | SUC CALIDOSO LIBERTAD: 7"


def test_store_without_stock_shows_zero(monkeypatch):
    row, _calls = run_sales_detail(monkeypatch, {"tiendaExistencia": "2008"})

    assert row["Existencia actual"] == 0.0
    assert row["Suma Existencia"] == 67.0
    assert row["Existencia por tienda"] == ""


def test_vendido_and_quedan_use_total_purchased_units(monkeypatch):
    # Compró 20 en total (Suma Unidades Compras) y vendió 4.
    row, _calls = run_sales_detail(monkeypatch, {"baseMetrics": '{"111": {"sumaUnidadesCompras": 20}}'})

    assert row["Unidades vendidas"] == 4.0
    assert row["Vendido"] == 20.0
    assert row["Quedan"] == 16.0


def test_vendido_and_quedan_are_empty_without_sales(monkeypatch):
    sin_ventas = [{**row, "Cantidad": 0, "Suma Cantidades ventas": 0} for row in VENTAS_ROWS]
    calls = []

    def fake_execute_query(sql, params):
        calls.append(sql)
        if "CodigoTienda" in sql:
            return list(EXISTENCIA_ROWS[0].keys()), EXISTENCIA_ROWS
        return list(sin_ventas[0].keys()), sin_ventas

    monkeypatch.setattr(details, "execute_query", fake_execute_query)
    result = query_runner.run_query(
        "ventas",
        {
            "fechaDesde": "2026-05-01",
            "fechaHasta": "2026-05-31",
            "detalleUnificada": "1",
            "codigoBarras": "111",
            "baseMetrics": '{"111": {"sumaUnidadesCompras": 20}}',
        },
        page=1,
        page_size=100,
    )
    row = result.rows[0]

    assert row["Unidades vendidas"] == 0.0
    assert row["Vendido"] == ""
    assert row["Quedan"] == ""


def test_vendido_and_quedan_are_empty_without_purchases(monkeypatch):
    row, _calls = run_sales_detail(monkeypatch, {})

    assert row["Vendido"] == ""
    assert row["Quedan"] == ""


def test_vendido_and_quedan_are_the_last_columns_of_the_unified_query():
    from app.services.query_runner.columns import SALES_DETAIL_COLUMNS, UNIFIED_COLUMNS

    sql = unified_sql.build_unified_full_sql(unified_sql.load_unified_base_sql())
    final_select = sql[sql.rindex("\nSELECT") : sql.index("FROM (SELECT")]

    assert UNIFIED_COLUMNS[-2:] == ["Vendido", "Quedan"]
    assert SALES_DETAIL_COLUMNS[-2:] == ["Vendido", "Quedan"]
    # En el SQL, despues de la ultima columna de transferencias y al final del SELECT.
    assert final_select.index("AS [Tienda kardex transferencia]") < final_select.index("AS [Vendido]")
    assert final_select.rstrip().endswith("END AS [Quedan]")


def test_existence_sql_returns_store_name_and_type():
    sql = unified_sql.build_existencia_por_tienda_sql()

    assert "AS NombreTienda" in sql
    assert "AS TipoTienda" in sql
    assert sql.count("?") == 1


def test_full_unified_sql_takes_existence_from_store_table_not_from_sales():
    sql = unified_sql.build_unified_full_sql(unified_sql.load_unified_base_sql())

    assert "INTO #u_existencia" in sql
    assert "existencia_detail.ExistenciaTotal AS [Existencia actual]" in sql
    assert "sales_detail.ExistenciaActual" not in sql
    assert "LEFT JOIN #u_existencia AS existencia_detail" in sql


def test_tiendas_endpoint_labels_stores_and_warehouses(monkeypatch):
    monkeypatch.setattr(tiendas, "settings", type("SettingsStub", (), {"has_database_credentials": True})())
    monkeypatch.setattr(
        tiendas,
        "execute_query",
        lambda sql: (
            ["Codigo", "Nombre", "Zona", "Tipo"],
            [
                {"Codigo": "2010", "Nombre": "BODEGA CREACION", "Zona": "ORIENTE", "Tipo": 0},
                {"Codigo": "1011", "Nombre": "SUC CALIDOSO LIBERTAD", "Zona": "ORIENTE", "Tipo": 1},
            ],
        ),
    )
    with query_runner.query_cache._lock:
        query_runner.query_cache._items.clear()

    result = get_tiendas()

    assert [(t.codigo, t.nombre, t.tipo) for t in result] == [
        ("2010", "BODEGA CREACION", "Bodega"),
        ("1011", "SUC CALIDOSO LIBERTAD", "Tienda"),
    ]
