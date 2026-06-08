import { describe, expect, it } from "vitest";

import {
  buildQueryRunParameters,
  filterRowsByAdjustment,
  filterRowsForCurrentPage,
  type TableFilters,
} from "./queryFilters";

const emptyFilters: TableFilters = {
  codigoBarra: "",
  referencia: "",
  codigoMarca: "",
  nombreMarca: "",
  categoria: "",
};

describe("query filters", () => {
  it("sends unified table filters as backend parameters", () => {
    const parameters = buildQueryRunParameters(
      "consulta_unificada",
      { fechaDesde: "2026-05-14", fechaHasta: "2026-05-21" },
      {
        ...emptyFilters,
        codigoBarra: " 5029900011300 ",
        referencia: "NV59034",
      },
    );

    expect(parameters).toMatchObject({
      fechaDesde: "2026-05-14",
      fechaHasta: "2026-05-21",
      codigoBarra: "5029900011300",
      referencia: "NV59034",
    });
  });

  it("adds non-empty table filters to normal query parameters so the backend can filter globally", () => {
    const parameters = buildQueryRunParameters(
      "ventas",
      { fechaDesde: "2026-05-14", fechaHasta: "2026-05-21" },
      { ...emptyFilters, codigoBarra: "5029900011300" },
    );

    expect(parameters).toEqual({
      fechaDesde: "2026-05-14",
      fechaHasta: "2026-05-21",
      codigoBarra: "5029900011300",
    });
  });

  it("locally filters unified rows by barcode before loading detail", () => {
    const rows = [
      { "Codigo Barra": "111", "Unidades de Ajustes Positivos": 1, "Unidades de Ajustes Negativos": 0 },
      { "Codigo Barra": "222", "Unidades de Ajustes Positivos": 0, "Unidades de Ajustes Negativos": 1 },
    ];

    const filteredRows = filterRowsForCurrentPage(
      "consulta_unificada",
      rows,
      { ...emptyFilters, codigoBarra: "222" },
    );

    expect(filteredRows).toEqual([rows[1]]);
  });

  it("filters positive and negative adjustment values after details are merged", () => {
    const rows = [
      { "Codigo Barra": "111", "Unidades de Ajustes Positivos": 1, "Unidades de Ajustes Negativos": 0 },
      { "Codigo Barra": "222", "Unidades de Ajustes Positivos": 0, "Unidades de Ajustes Negativos": 1 },
      { "Codigo Barra": "333" },
    ];

    const positiveRows = filterRowsByAdjustment(
      "consulta_unificada",
      rows,
      { positive: true, negative: false, both: false },
    );
    const negativeRows = filterRowsByAdjustment("consulta_unificada", rows, {
      positive: false,
      negative: true,
      both: false,
    });

    expect(positiveRows).toEqual([rows[0]]);
    expect(negativeRows).toEqual([rows[1]]);
  });

  it("filters unified rows with both positive and negative adjustments", () => {
    const rows = [
      { "Codigo Barra": "111", "Unidades de Ajustes Positivos": 4, "Unidades de Ajustes Negativos": 0 },
      { "Codigo Barra": "222", "Unidades de Ajustes Positivos": 0, "Unidades de Ajustes Negativos": 6 },
      { "Codigo Barra": "333", "Unidades de Ajustes Positivos": 2, "Unidades de Ajustes Negativos": 8 },
    ];

    const bothRows = filterRowsByAdjustment("consulta_unificada", rows, {
      positive: false,
      negative: false,
      both: true,
    });

    expect(bothRows).toEqual([rows[2]]);
  });

  it("buildQueryRunParameters trims filters and unified rows also filter locally by text filters", () => {
    const parameterValues = { fechaDesde: "2026-05-14", fechaHasta: "2026-05-21" };
    const tableFilters: TableFilters = {
      codigoBarra: " 5029900011300 ",
      referencia: " NV59034 ",
      codigoMarca: " NVN ",
      nombreMarca: " NIRVANA ",
      categoria: " MEDIAS ",
    };

    const params = buildQueryRunParameters("consulta_unificada", parameterValues, tableFilters);

    expect(params).toMatchObject({
      fechaDesde: "2026-05-14",
      fechaHasta: "2026-05-21",
      codigoBarra: "5029900011300",
      referencia: "NV59034",
      codigoMarca: "NVN",
      nombreMarca: "NIRVANA",
      categoria: "MEDIAS",
    });

    const rows = [
      { "Codigo Barra": "111", "Unidades de Ajustes Positivos": 1, "Unidades de Ajustes Negativos": 0 },
      { "Codigo Barra": "222", "Unidades de Ajustes Positivos": 0, "Unidades de Ajustes Negativos": 1 },
    ];

    const filtered = filterRowsForCurrentPage(
      "consulta_unificada",
      rows,
      { ...emptyFilters, codigoBarra: "222" },
    );

    expect(filtered).toEqual([rows[1]]);

    // positive/negative adjustments still apply locally
    expect(filterRowsByAdjustment("consulta_unificada", rows, { positive: true, negative: false, both: false })).toEqual([
      rows[0],
    ]);

    expect(filterRowsByAdjustment("consulta_unificada", rows, { positive: false, negative: true, both: false })).toEqual([
      rows[1],
    ]);
  });

  it("non-unified queries also filter the current page locally by text filters", () => {
    const rows = [
      { "Codigo Barra": "111", "Referencias": "REF-A" },
      { "Codigo Barra": "222", "Referencias": "REF-B" },
    ];

    const tableFilters: TableFilters = {
      codigoBarra: "222",
      referencia: "",
      codigoMarca: "",
      nombreMarca: "",
      categoria: "",
    };

    const filtered = filterRowsForCurrentPage("ventas", rows, tableFilters);
    expect(filtered).toEqual([rows[1]]);
  });
});
