from app.services import query_runner
from app.services.query_catalog import get_query
from app.services.query_runner import details, unified
from app.services.unified_snapshot import (
    append_snapshot_rows,
    build_snapshot_id,
    finalize_snapshot,
    read_snapshot_filtered_page,
    reset_snapshot,
)


def test_common_barcodes_use_unified_rule_query_and_are_persisted(monkeypatch):
    parameters = {"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}
    cache_parameters = query_runner.get_cache_parameters("consulta_unificada", parameters)
    snapshot_id = build_snapshot_id(query_runner.COMMON_BARCODES_SNAPSHOT_QUERY_ID, cache_parameters)
    reset_snapshot(snapshot_id)
    with query_runner.query_cache._lock:
        query_runner.query_cache._items.clear()

    calls = []

    def fake_execute_query(sql, params):
        calls.append({"sql": sql, "params": params})
        return ["CodigoBarra"], [{"CodigoBarra": "B"}, {"CodigoBarra": "D"}]

    monkeypatch.setattr(unified, "execute_query", fake_execute_query)

    try:
        first = query_runner.get_common_barcodes(parameters)
        with query_runner.query_cache._lock:
            query_runner.query_cache._items.clear()
        second = query_runner.get_common_barcodes(parameters)

        assert first == ["B", "D"]
        assert second == ["B", "D"]
        # Una sola consulta (la misma regla que usan las paginas); la segunda vez sale del snapshot.
        assert len(calls) == 1
        assert "#u_transfer" in calls[0]["sql"]
        assert [p.isoformat() for p in calls[0]["params"]] == ["2026-05-14", "2026-05-21"]
    finally:
        reset_snapshot(snapshot_id)


def test_snapshot_filtered_page_filters_against_full_parquet_snapshot():
    parameters = {"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}
    snapshot_id = build_snapshot_id("test_filtered_unified_snapshot", parameters)
    reset_snapshot(snapshot_id)
    # Clear any cached results from other tests that could affect this one
    with query_runner.query_cache._lock:
        query_runner.query_cache._items.clear()
    try:
        next_index = append_snapshot_rows(
            snapshot_id,
            0,
            [
                {"Codigo Barra": "111", "Referencias": "REF-A", "Nombre Categoria": "DAMA"},
                {"Codigo Barra": "222", "Referencias": "REF-B", "Nombre Categoria": "PANTY"},
            ],
        )
        finalize_snapshot(snapshot_id, parameters, ["Codigo Barra", "Referencias", "Nombre Categoria"], next_index)

        rows, total_rows = read_snapshot_filtered_page(
            snapshot_id,
            [(["Codigo Barra", "CodigoBarra"], "222")],
            0,
            100,
        )

        assert total_rows == 1
        assert rows[0]["Codigo Barra"] == "222"
    finally:
        reset_snapshot(snapshot_id)


def test_ventas_parameters_include_dates_and_optional_barcode():
    definition = get_query("ventas")

    parameters = query_runner.build_ordered_parameters(
        definition,
        {
            "fechaDesde": "2026-05-14",
            "fechaHasta": "2026-05-21",
            "codigoBarra": "5029900011300",
        },
    )

    assert [value.isoformat() if hasattr(value, "isoformat") else value for value in parameters] == [
        "2026-05-14",
        "2026-05-21",
        "5029900011300",
        "5029900011300",
    ]


def test_ventas_parameters_prefer_batch_barcodes_over_single_barcode():
    definition = get_query("ventas")

    parameters = query_runner.build_ordered_parameters(
        definition,
        {
            "fechaDesde": "2026-05-14",
            "fechaHasta": "2026-05-21",
            "codigoBarra": "111",
            "codigoBarras": "111,222",
        },
    )

    assert [value.isoformat() if hasattr(value, "isoformat") else value for value in parameters] == [
        "2026-05-14",
        "2026-05-21",
        "111,222",
        "111,222",
    ]


def test_kardex_parameters_include_optional_barcode_twice():
    definition = get_query("kardex")

    parameters = query_runner.build_ordered_parameters(
        definition,
        {
            "fechaDesde": "2026-05-14",
            "codigoBarra": "5029900011300",
        },
    )

    assert [value.isoformat() if hasattr(value, "isoformat") else value for value in parameters] == [
        "2026-05-14",
        "5029900011300",
        "5029900011300",
    ]


def test_transferencias_parameters_include_dates_and_optional_barcode_twice():
    definition = get_query("transferencias_tiendas")

    parameters = query_runner.build_ordered_parameters(
        definition,
        {
            "fechaDesde": "2026-05-14",
            "fechaHasta": "2026-05-21",
            "codigoBarra": "5029900018767",
        },
    )

    assert [value.isoformat() if hasattr(value, "isoformat") else value for value in parameters] == [
        "2026-05-14",
        "2026-05-21",
        "5029900018767",
        "5029900018767",
    ]


def test_run_unified_detail_kardex_calculates_summary_in_python(monkeypatch):
    captured = {}

    def fake_execute_query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return (
            ["CodigoBarra", "Tipo", "Cantidad", "CostoInicial"],
            [
                {"CodigoBarra": "111", "Tipo": "Entrada", "Cantidad": 2, "CostoInicial": 5},
                {"CodigoBarra": "111", "Tipo": "Salida", "Cantidad": -3, "CostoInicial": 5},
            ],
        )

    monkeypatch.setattr(details, "execute_query", fake_execute_query)

    result = query_runner.run_query(
        "kardex",
        {
            "fechaDesde": "2026-05-14",
            "detalleUnificada": "1",
            "codigoBarras": "111",
            "baseMetrics": '{"111":{"cantidadCompra":10}}',
        },
        page=1,
        page_size=100,
    )

    assert "GROUP BY" not in captured["sql"]
    assert [value.isoformat() if hasattr(value, "isoformat") else value for value in captured["params"]] == [
        "2026-05-14",
        "111",
        "111",
    ]
    assert result.rows == [
        {
            "Codigo Barra": "111",
            "Costo Inicial": 5.0,
            "Unidades de Ajustes Positivos": 2.0,
            "% Ajustes Positivos": 5.0,
            "Unidades de Ajustes Negativos": 3.0,
            "% Ajustes Negativos": 3.33,
            "Utilidad perdida por ajustes": 15.0,
            "% Utilidad perdida por ajustes": 0.67,
        }
    ]


def test_run_unified_query_uses_base_page_when_unified_filters_are_present(monkeypatch):
    parameters = {
        "fechaDesde": "2026-05-14",
        "fechaHasta": "2026-05-21",
        "codigoBarra": "5029900018767",
    }

    monkeypatch.setattr(unified, "settings", type("SettingsStub", (), {"has_database_credentials": True})())

    called = {"base_page": False}

    def fake_build_unified_base_page(params, page, page_size):
        called["base_page"] = True
        assert params == parameters
        assert page == 2
        assert page_size == 10
        return ["Codigo Barra"], [{"Codigo Barra": "5029900018767"}], 11, 3, True

    monkeypatch.setattr(unified, "build_unified_base_page", fake_build_unified_base_page)

    result = query_runner.run_unified_query(parameters, page=2, page_size=10)

    assert called["base_page"] is True
    assert result.query_id == "consulta_unificada"
    assert result.rows == [{"Codigo Barra": "5029900018767"}]
    assert result.total_rows == 11
    assert result.total_pages == 3
    assert result.page == 2
    assert result.is_loading is False
    assert result.is_complete is False


def test_run_unified_query_uses_base_page_when_no_filters(monkeypatch):
    parameters = {
        "fechaDesde": "2026-05-14",
        "fechaHasta": "2026-05-21",
    }

    monkeypatch.setattr(unified, "settings", type("SettingsStub", (), {"has_database_credentials": True})())

    called = {"base_page": False}

    def fake_build_unified_base_page(params, page, page_size):
        called["base_page"] = True
        assert params == parameters
        assert page == 1
        assert page_size == 4
        return (
            ["Codigo Barra"],
            [{"Codigo Barra": "111"}, {"Codigo Barra": "222"}, {"Codigo Barra": "333"}, {"Codigo Barra": "444"}],
            5,
            2,
            True,
        )

    monkeypatch.setattr(unified, "build_unified_base_page", fake_build_unified_base_page)

    result = query_runner.run_unified_query(parameters, page=1, page_size=4)

    assert called["base_page"] is True
    assert result.query_id == "consulta_unificada"
    assert result.rows == [{"Codigo Barra": "111"}, {"Codigo Barra": "222"}, {"Codigo Barra": "333"}, {"Codigo Barra": "444"}]
    assert result.total_rows == 5
    assert result.total_pages == 2
    assert result.page == 1


def test_run_unified_query_returns_base_page_without_background_snapshot(monkeypatch):
    parameters = {
        "fechaDesde": "2026-05-20",
        "fechaHasta": "2026-05-27",
    }

    monkeypatch.setattr(unified, "settings", type("SettingsStub", (), {"has_database_credentials": True})())

    called = {"base_page": False}

    def fake_build_unified_base_page(params, page, page_size):
        called["base_page"] = True
        assert params == parameters
        assert page == 1
        assert page_size == 100
        return ["Codigo Barra"], [{"Codigo Barra": "111"}], 2, 2, True

    monkeypatch.setattr(unified, "build_unified_base_page", fake_build_unified_base_page)

    result = query_runner.run_unified_query(parameters, page=1, page_size=100)

    assert called == {"base_page": True}
    assert result.rows == [{"Codigo Barra": "111"}]
    assert result.row_count == 1
    assert result.total_rows == 2
    assert result.total_pages == 2
    assert result.is_loading is False
    assert result.is_complete is False


def test_run_unified_query_propagates_base_page_errors(monkeypatch):
    parameters = {
        "fechaDesde": "2026-05-20",
        "fechaHasta": "2026-05-27",
    }

    monkeypatch.setattr(unified, "settings", type("SettingsStub", (), {"has_database_credentials": True})())
    monkeypatch.setattr(
        unified,
        "build_unified_base_page",
        lambda params, page, page_size: (_ for _ in ()).throw(RuntimeError("timeout")),
    )

    try:
        query_runner.run_unified_query(parameters, page=1, page_size=100)
    except RuntimeError as exc:
        assert str(exc) == "timeout"
    else:
        raise AssertionError("run_unified_query should propagate base page errors")


def test_transferencias_sql_uses_varchar_document_and_strict_concept_filter():
    sql = query_runner.build_transferencias_page_sql()

    assert "CONVERT(VARCHAR(50), K.Documento) = NP.DocumentoStr" in sql
    assert "CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(NP.CodigoBarra AS VARCHAR(50))" in sql
    assert "LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'" in sql


def test_build_unified_snapshot_uses_full_range_intersection(monkeypatch):
    calls = {"exact": 0, "incremental": 0}

    def fake_exact(fecha_desde, fecha_hasta):
        calls["exact"] += 1
        assert fecha_desde.isoformat() == "2026-05-14"
        assert fecha_hasta.isoformat() == "2026-06-03"
        return "snapshot-id", ["Codigo Barra"], 1

    def fake_incremental(_fecha_desde, _fecha_hasta):
        calls["incremental"] += 1
        return "wrong-snapshot-id", [], 0

    monkeypatch.setattr(unified, "build_unified_snapshot_exact", fake_exact)
    monkeypatch.setattr(unified, "build_unified_snapshot_incremental", fake_incremental)

    result = query_runner.build_unified_snapshot(
        {"fechaDesde": "2026-05-14", "fechaHasta": "2026-06-03"}
    )

    assert result == ("snapshot-id", ["Codigo Barra"], 1)
    assert calls == {"exact": 1, "incremental": 0}
