from app.services import query_runner
from app.services.query_runner import unified


def test_run_unified_query_page1_returns_base_rows_without_loading(monkeypatch):
    sample_rows = [{"Codigo Barra": str(i)} for i in range(100)]
    sample_columns = ["Codigo Barra", "Referencias"]

    def fake_build_base_page(params, page, page_size):
        assert page == 1
        assert page_size == 100
        return sample_columns, sample_rows, len(sample_rows), 2, True

    monkeypatch.setattr(unified, "settings", type("SettingsStub", (), {"has_database_credentials": True})())
    monkeypatch.setattr(unified, "build_unified_base_page", fake_build_base_page)

    result = query_runner.run_unified_query({"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}, page=1, page_size=100)

    assert result.query_id == "consulta_unificada"
    assert result.rows == sample_rows
    assert result.row_count == len(sample_rows)
    assert result.is_loading is False
    assert result.is_complete is False


def test_build_unified_first_page_calls_execute_query_with_expected_parameter_count_and_order(monkeypatch):
    calls = []

    def fake_execute_query(sql, params):
        calls.append({"sql": sql, "params": params})

        if is_codes_sql(sql):
            return ["CodigoBarra"], [{"CodigoBarra": "111"}, {"CodigoBarra": "222"}]

        return ["Codigo Barra"], [{"Codigo Barra": "111"}, {"Codigo Barra": "222"}]

    monkeypatch.setattr(unified, "execute_query", fake_execute_query)
    clear_query_cache()

    params = {"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}
    cols, rows, est_total, total_pages, has_more = query_runner.build_unified_first_page(params, page_size=100)

    assert len(calls) == 2

    code_call = calls[0]
    detail_call = calls[1]

    assert "#u_transfer" in code_call["sql"]
    assert "OFFSET" not in code_call["sql"]
    assert "WHERE CAST(CodigoBarra AS VARCHAR(50)) IN (?, ?)" in detail_call["sql"]

    assert len(code_call["params"]) == 2
    parsed_code_dates = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in code_call["params"]]
    assert parsed_code_dates == ["2026-05-14", "2026-05-21"]

    detail_params = detail_call["params"]
    parsed_detail_dates = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in detail_params[:2]]
    assert parsed_detail_dates == ["2026-05-14", "2026-05-21"]
    assert detail_params[2:] == ["111", "222"]

    assert cols == ["Codigo Barra"]
    assert rows == [{"Codigo Barra": "111"}, {"Codigo Barra": "222"}]
    assert est_total == 2
    assert total_pages == 1
    assert has_more is False


def test_unified_pages_reuse_common_codes_instead_of_requerying(monkeypatch):
    calls = {"codes": 0, "detail": []}
    all_codes = [f"{i:03d}" for i in range(5)]

    def fake_execute_query(sql, params):
        if is_codes_sql(sql):
            calls["codes"] += 1
            return ["CodigoBarra"], [{"CodigoBarra": code} for code in all_codes]

        page_codes = params[2:]
        calls["detail"].append(page_codes)
        return ["Codigo Barra"], [{"Codigo Barra": code} for code in page_codes]

    monkeypatch.setattr(unified, "execute_query", fake_execute_query)
    clear_query_cache()

    params = {"fechaDesde": "2026-04-01", "fechaHasta": "2026-04-07"}
    _cols, first_rows, _total, _pages, first_has_more = unified.build_unified_base_page(params, 1, 2)
    _cols, second_rows, _total, _pages, second_has_more = unified.build_unified_base_page(params, 2, 2)
    _cols, last_rows, _total, _pages, last_has_more = unified.build_unified_base_page(params, 3, 2)

    assert calls["codes"] == 1
    assert calls["detail"] == [["000", "001"], ["002", "003"], ["004"]]
    assert [row["Codigo Barra"] for row in first_rows + second_rows + last_rows] == all_codes
    assert (first_has_more, second_has_more, last_has_more) == (True, True, False)


def test_unified_page_past_the_end_returns_empty(monkeypatch):
    monkeypatch.setattr(
        unified,
        "execute_query",
        lambda sql, params: (["CodigoBarra"], [{"CodigoBarra": "111"}]) if is_codes_sql(sql) else (_ for _ in ()).throw(AssertionError("no detail query expected")),
    )
    clear_query_cache()

    _cols, rows, _total, _pages, has_more = unified.build_unified_base_page(
        {"fechaDesde": "2026-03-01", "fechaHasta": "2026-03-02"}, 5, 10
    )

    assert rows == []
    assert has_more is False


def clear_query_cache():
    with query_runner.query_cache._lock:
        query_runner.query_cache._items.clear()


def is_codes_sql(sql: str) -> bool:
    """La consulta de codigos termina leyendo #u_transfer y no trae la consulta base de compras."""
    return "FROM #u_transfer" in sql and "AS base_query" not in sql


def test_run_unified_query_base_page_failure_is_not_hidden(monkeypatch):
    def fake_build_base_page(params, page, page_size):
        raise RuntimeError("DB preview failed")

    monkeypatch.setattr(unified, "settings", type("SettingsStub", (), {"has_database_credentials": True})())
    monkeypatch.setattr(unified, "build_unified_base_page", fake_build_base_page)

    try:
        query_runner.run_unified_query({"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}, page=1, page_size=100)
    except RuntimeError as exc:
        assert str(exc) == "DB preview failed"
    else:
        raise AssertionError("run_unified_query should not hide base page failures")


def test_unified_full_sql_requires_kardex_sales_and_transfers():
    base_sql = "SELECT CodigoBarra FROM sometable WHERE Fecha >= ? AND Fecha < DATEADD(DAY, 1, ?)"
    sql = query_runner.build_unified_full_sql(base_sql)

    # 2 fechas para los pasos con tablas temporales + 2 de la consulta base.
    assert sql.count("?") == 4
    # Ajustes de kardex, ventas y transferencias son obligatorios.
    assert "INNER JOIN #u_kardex AS kardex_detail" in sql
    assert "INNER JOIN #u_sales AS sales_detail" in sql
    assert "INNER JOIN #u_transfer AS transfer_detail" in sql
    assert "LEFT JOIN #u_kardex" not in sql
    # Ya no hay subconsultas por fila (eran las que hacian lenta la consulta).
    assert "CROSS APPLY" not in sql
    assert "ORDER BY base_query.CodigoBarra" in sql


def test_unified_codes_sql_filters_in_order_compras_kardex_ventas_transferencias():
    from app.services.query_runner import sql as unified_sql

    codes_sql = unified_sql.build_unified_common_codes_sql()

    assert codes_sql.count("?") == 2
    # Cada paso solo trabaja con los codigos que pasaron el anterior.
    assert "INTO #u_kardex" in codes_sql
    assert "FROM #u_compras uc" in codes_sql.split("INTO #u_kardex", 1)[1].split("INTO #u_sales", 1)[0]
    assert "FROM #u_kardex uk" in codes_sql.split("INTO #u_sales", 1)[1].split("INTO #u_mtf", 1)[0]
    assert "FROM #u_sales us" in codes_sql.split("INTO #u_mtf", 1)[1].split("INTO #u_kdoc", 1)[0]
    assert codes_sql.rstrip().endswith("FROM #u_transfer\nORDER BY CodigoBarra")


def test_unified_includes_despacho_columns_after_suma_compras():
    from app.services.query_runner import sql as unified_sql
    from app.services.query_runner.columns import UNIFIED_BASE_COLUMNS, UNIFIED_COLUMNS

    expected = ["Suma Unidades Compras", "Despachar A", "Numero Contenedor"]
    for columns in (UNIFIED_COLUMNS, UNIFIED_BASE_COLUMNS):
        start = columns.index("Suma Unidades Compras")
        assert columns[start : start + 3] == expected

    base_sql = unified_sql.load_unified_base_sql()
    assert "C.[DespacharA]" in base_sql
    assert "C.[NumeroContenedor]" in base_sql

    for detail_sql in (
        unified_sql.build_unified_full_sql(base_sql),
        unified_sql.build_unified_base_only_detail_sql(base_sql, 2),
    ):
        assert "DespacharA AS [Despachar A]" in detail_sql
        assert "NumeroContenedor AS [Numero Contenedor]" in detail_sql


def test_unified_full_detail_sql_qualifies_base_columns_shared_with_kardex():
    import re

    from app.services.query_runner import sql as unified_sql

    detail_sql = unified_sql.build_unified_full_sql(unified_sql.load_unified_base_sql())
    final_select = detail_sql[detail_sql.rindex("\nSELECT") :]
    select_list = re.sub(r"\[[^\]]*\]", "[]", final_select.split("FROM (", 1)[0])

    # kardex_detail tambien expone Referencia, CodigoMarca, Documento, Observacion y Cantidad:
    # sin el prefijo base_query SQL Server falla con "nombre de columna ambiguo" (Msg 209).
    for column in ("Referencia", "CodigoMarca", "Documento", "Observacion", "Cantidad"):
        assert not re.search(rf"(?<![.\w\[]){column}\b(?!\])", select_list), column
