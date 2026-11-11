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

        if "CommonCodes" in sql:
            return ["CodigoBarra"], [{"CodigoBarra": "111"}, {"CodigoBarra": "222"}]

        return ["Codigo Barra"], [{"Codigo Barra": "111"}, {"Codigo Barra": "222"}]

    monkeypatch.setattr(unified, "execute_query", fake_execute_query)
    clear_query_cache()

    params = {"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}
    cols, rows, est_total, total_pages, has_more = query_runner.build_unified_first_page(params, page_size=100)

    assert len(calls) == 2

    code_call = calls[0]
    detail_call = calls[1]

    assert "WITH CommonCodes AS" in code_call["sql"]
    assert "OFFSET" not in code_call["sql"]
    assert "WHERE CAST(CodigoBarra AS VARCHAR(50)) IN (?, ?)" in detail_call["sql"]

    assert len(code_call["params"]) == 8
    parsed_code_dates = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in code_call["params"]]
    assert parsed_code_dates == ["2026-05-14", "2026-05-21"] * 4

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
        if "CommonCodes" in sql:
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
        lambda sql, params: (["CodigoBarra"], [{"CodigoBarra": "111"}]) if "CommonCodes" in sql else (_ for _ in ()).throw(AssertionError("no detail query expected")),
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


def test_build_unified_base_detail_sql_top_and_no_in_clause():
    base_sql = "SELECT CodigoBarra FROM sometable WHERE 1=1"
    sql = query_runner.build_unified_base_detail_sql(base_sql, None)

    assert "TOP (?)" in sql
    assert "IN (" not in sql
    assert "ORDER BY CodigoBarra" in sql
