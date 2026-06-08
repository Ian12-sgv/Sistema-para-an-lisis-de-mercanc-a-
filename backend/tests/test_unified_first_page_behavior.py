from app.services import query_runner


def test_run_unified_query_page1_returns_base_rows_without_loading(monkeypatch):
    sample_rows = [{"Codigo Barra": str(i)} for i in range(100)]
    sample_columns = ["Codigo Barra", "Referencias"]

    def fake_build_base_page(params, page, page_size):
        assert page == 1
        assert page_size == 100
        return sample_columns, sample_rows, len(sample_rows), 2, True

    monkeypatch.setattr(query_runner, "settings", type("SettingsStub", (), {"has_database_credentials": True})())
    monkeypatch.setattr(query_runner, "build_unified_base_page", fake_build_base_page)

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

        if "CommonCodes" in sql:
            return ["CodigoBarra"], [{"CodigoBarra": "111"}, {"CodigoBarra": "222"}]

        return ["Codigo Barra"], [{"Codigo Barra": "111"}, {"Codigo Barra": "222"}]

    monkeypatch.setattr(query_runner, "execute_query", fake_execute_query)

    params = {"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}
    cols, rows, est_total, total_pages, has_more = query_runner.build_unified_first_page(params, page_size=100)

    assert len(calls) == 2

    code_call = calls[0]
    detail_call = calls[1]

    assert "WITH CommonCodes AS" in code_call["sql"]
    assert "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in code_call["sql"]
    assert "WHERE CAST(CodigoBarra AS VARCHAR(50)) IN (?, ?)" in detail_call["sql"]

    assert len(code_call["params"]) == 10
    parsed_code_dates = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in code_call["params"][:8]]
    assert parsed_code_dates == ["2026-05-14", "2026-05-21"] * 4
    assert code_call["params"][8:] == [0, 101]

    detail_params = detail_call["params"]
    parsed_detail_dates = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in detail_params[:2]]
    assert parsed_detail_dates == ["2026-05-14", "2026-05-21"]
    assert detail_params[2:] == ["111", "222"]

    assert cols == ["Codigo Barra"]
    assert rows == [{"Codigo Barra": "111"}, {"Codigo Barra": "222"}]
    assert est_total == 2
    assert total_pages == 1
    assert has_more is False


def test_run_unified_query_base_page_failure_is_not_hidden(monkeypatch):
    def fake_build_base_page(params, page, page_size):
        raise RuntimeError("DB preview failed")

    monkeypatch.setattr(query_runner, "settings", type("SettingsStub", (), {"has_database_credentials": True})())
    monkeypatch.setattr(query_runner, "build_unified_base_page", fake_build_base_page)

    try:
        query_runner.run_unified_query({"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}, page=1, page_size=100)
    except RuntimeError as exc:
        assert str(exc) == "DB preview failed"
    else:
        raise AssertionError("run_unified_query should not hide base page failures")


def test_build_unified_base_detail_sql_top_and_no_in_clause():
    base_sql = "SELECT CodigoBarra FROM sometable WHERE 1=1"
    sql = query_runner.build_unified_base_detail_sql(base_sql, None)

    assert "TOP (?)" in sql
    assert "IN (" not in sql
    assert "ORDER BY CodigoBarra" in sql
