import React from "react";
import { vi, describe, it, beforeEach, afterEach, expect } from "vitest";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
Object.defineProperty(globalThis, "window", { value: dom.window, configurable: true });
Object.defineProperty(globalThis, "document", { value: dom.window.document, configurable: true });
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });

import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import * as api from "./api";
import { App } from "./App";

const fakeQueries = [
  {
    id: "consulta_unificada",
    name: "Unificada",
    description: "desc",
    parameters: [
      { name: "fechaDesde", label: "Fecha desde", type: "date", required: true },
      { name: "fechaHasta", label: "Fecha hasta", type: "date", required: true },
    ],
  },
];

describe("App unified step-by-step behavior", () => {
  beforeEach(() => {
    vi.spyOn(api, "fetchQueries").mockResolvedValue(fakeQueries as any);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders base rows without loading state and exposes detail buttons", async () => {
    const firstResult = {
      queryId: "consulta_unificada",
      columns: ["Codigo Barra", "Referencias"],
      rows: [{ "Codigo Barra": "111", Referencias: "REF-111" }],
      rowCount: 1,
      totalRows: 101,
      page: 1,
      pageSize: 100,
      totalPages: 2,
      isLoading: false,
      isComplete: false,
    };

    vi.spyOn(api, "runQuery").mockResolvedValue(firstResult as any);

    const { findByRole, findByText, getByRole, queryByText } = render(<App />);

    const ejecutarButton = await findByRole("button", { name: /ejecutar/i });
    ejecutarButton.click();

    await findByText("111");
    await findByText("REF-111");

    expect(queryByText(/cargando esta pagina/i)).toBeNull();
    expect(getByRole("button", { name: /^ventas$/i })).toBeTruthy();
    expect(getByRole("button", { name: /^kardex$/i })).toBeTruthy();
    expect(getByRole("button", { name: /^transferencias$/i })).toBeTruthy();
  });

  it("merges unified details from multiple buttons without replacing previous data", async () => {
    const unifiedResult = {
      queryId: "consulta_unificada",
      columns: ["Codigo Barra", "Referencias", "Cantidad de compra"],
      rows: [{ "Codigo Barra": "111", Referencias: "REF-111", "Cantidad de compra": 10 }],
      rowCount: 1,
      totalRows: 1,
      page: 1,
      pageSize: 100,
      totalPages: 1,
      isLoading: false,
      isComplete: true,
    };
    const salesResult = {
      queryId: "ventas",
      columns: ["Codigo Barra", "Existencia actual", "Unidades vendidas"],
      rows: [{ "Codigo Barra": "111", "Existencia actual": 4, "Unidades vendidas": 3 }],
      rowCount: 1,
      totalRows: 1,
      page: 1,
      pageSize: 1000,
      totalPages: 1,
      isLoading: false,
      isComplete: true,
    };
    const kardexResult = {
      queryId: "kardex",
      columns: ["Codigo Barra", "Costo Inicial", "Unidades de Ajustes Positivos"],
      rows: [{ "Codigo Barra": "111", "Costo Inicial": 5, "Unidades de Ajustes Positivos": 2 }],
      rowCount: 1,
      totalRows: 1,
      page: 1,
      pageSize: 1000,
      totalPages: 1,
      isLoading: false,
      isComplete: true,
    };

    const runQueryMock = vi
      .spyOn(api, "runQuery")
      .mockResolvedValueOnce(unifiedResult as any)
      .mockResolvedValueOnce(salesResult as any)
      .mockResolvedValueOnce(kardexResult as any);

    const { findByRole, findByText, getByRole } = render(<App />);

    fireEvent.click(await findByRole("button", { name: /ejecutar/i }));
    await findByText("111");

    fireEvent.click(getByRole("button", { name: /^ventas$/i }));
    await findByText("Unidades vendidas");

    fireEvent.click(getByRole("button", { name: /^kardex$/i }));
    await findByText("Unidades de Ajustes Positivos");

    await waitFor(() => {
      expect(runQueryMock).toHaveBeenCalledTimes(3);
      expect(getByRole("columnheader", { name: "Unidades vendidas" })).toBeTruthy();
      expect(getByRole("columnheader", { name: "Unidades de Ajustes Positivos" })).toBeTruthy();
    });
  });

  it("loads unified detail for visible barcodes in one batch request", async () => {
    const unifiedResult = {
      queryId: "consulta_unificada",
      columns: ["Codigo Barra", "Referencias"],
      rows: [
        { "Codigo Barra": "111", Referencias: "REF-111" },
        { "Codigo Barra": "222", Referencias: "REF-222" },
      ],
      rowCount: 2,
      totalRows: 2,
      page: 1,
      pageSize: 100,
      totalPages: 1,
      isLoading: false,
      isComplete: true,
    };
    const salesResult = {
      queryId: "ventas",
      columns: ["Codigo Barra", "Existencia actual", "Unidades vendidas"],
      rows: [
        { "Codigo Barra": "111", "Existencia actual": 4, "Unidades vendidas": 3 },
        { "Codigo Barra": "222", "Existencia actual": 6, "Unidades vendidas": 5 },
      ],
      rowCount: 2,
      totalRows: 2,
      page: 1,
      pageSize: 1000,
      totalPages: 1,
      isLoading: false,
      isComplete: true,
    };

    const runQueryMock = vi.spyOn(api, "runQuery").mockResolvedValueOnce(unifiedResult as any).mockResolvedValueOnce(salesResult as any);
    const { findByRole, findByText, getByRole } = render(<App />);

    fireEvent.click(await findByRole("button", { name: /ejecutar/i }));
    await findByText("REF-222");

    fireEvent.click(getByRole("button", { name: /^ventas$/i }));
    await findByText("Detalle cargado para 2 de 2 articulos visibles.");

    expect(runQueryMock).toHaveBeenCalledTimes(2);
    expect(runQueryMock).toHaveBeenLastCalledWith(
      "ventas",
      expect.objectContaining({ detalleUnificada: "1", codigoBarras: "111,222" }),
      1,
      1000,
    );
  });

});
