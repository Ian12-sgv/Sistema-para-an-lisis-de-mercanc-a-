from app.services.unified_snapshot import (
    append_snapshot_rows,
    build_snapshot_id,
    finalize_snapshot,
    read_snapshot_filtered_page,
    reset_snapshot,
)


def test_snapshot_filtered_page_filters_by_reference_and_category_with_pagination():
    parameters = {"fechaDesde": "2026-05-14", "fechaHasta": "2026-05-21"}
    snapshot_id = build_snapshot_id("test_filtered_unified_snapshot_pagination", parameters)
    reset_snapshot(snapshot_id)

    try:
        rows = [
            {"Codigo Barra": "111", "Referencias": "REF-A", "Nombre Categoria": "DAMA"},
            {"Codigo Barra": "222", "Referencias": "REF-B", "Nombre Categoria": "PANTY"},
            {"Codigo Barra": "333", "Referencias": "REF-A", "Nombre Categoria": "DAMAS"},
        ]

        next_index = append_snapshot_rows(snapshot_id, 0, rows)
        finalize_snapshot(snapshot_id, parameters, ["Codigo Barra", "Referencias", "Nombre Categoria"], next_index)

        filtered_rows, total_rows = read_snapshot_filtered_page(
            snapshot_id,
            [(["Referencias", "Referencia"], "REF-A")],
            0,
            100,
        )

        assert total_rows == 2
        assert {row["Codigo Barra"] for row in filtered_rows} == {"111", "333"}

        category_rows, category_total = read_snapshot_filtered_page(
            snapshot_id,
            [(["Nombre Categoria", "Codigo Categoria"], "PANTY")],
            0,
            100,
        )

        assert category_total == 1
        assert category_rows[0]["Codigo Barra"] == "222"

        page_one, page_total = read_snapshot_filtered_page(
            snapshot_id,
            [(["Referencias", "Referencia"], "REF-A")],
            0,
            1,
        )
        page_two, _ = read_snapshot_filtered_page(
            snapshot_id,
            [(["Referencias", "Referencia"], "REF-A")],
            1,
            1,
        )

        assert page_total == 2
        assert len(page_one) == 1
        assert len(page_two) == 1
        assert {page_one[0]["Codigo Barra"], page_two[0]["Codigo Barra"]} == {"111", "333"}
    finally:
        reset_snapshot(snapshot_id)
