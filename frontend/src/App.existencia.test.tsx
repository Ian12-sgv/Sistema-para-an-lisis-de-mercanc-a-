import React from "react";
import { vi, describe, it, afterEach, expect } from "vitest";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
Object.defineProperty(globalThis, "window", { value: dom.window, configurable: true });
Object.defineProperty(globalThis, "document", { value: dom.window.document, configurable: true });
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });

import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import * as api from "./api";
import { App } from "./App";

const unifiedQuery = {
  id: "consulta_unificada",
  name: "Consulta unificada",
  description: "desc",
  parameters: [
    { name: "fechaDesde", label: "Fecha desde", type: "date", required: true },
    { name: "fechaHasta", label: "Fecha hasta", type: "date", required: true },
  ],
};

const unifiedResult = {
  queryId: "consulta_unificada",
  columns: ["Codigo Barra", "Referencias"],
  rows: [{ "Codigo Barra": "111", Referencias: "REF-1" }],
  rowCount: 1,
  totalRows: 1,
  page: 1,
  pageSize: 100,
  totalPages: 1,
  isLoading: false,
  isComplete: true,
};

function salesDetail(existencia: number, porTienda: string) {
  return {
    ...unifiedResult,
    queryId: "ventas",
    columns: ["Codigo Barra", "Existencia actual", "Suma Existencia", "Existencia por tienda"],
    rows: [
      { "Codigo Barra": "111", "Existencia actual": existencia, "Suma Existencia": 67, "Existencia por tienda": porTienda },
    ],
  };
}

describe("App existencia por tienda", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it(
    "lets the user pick several stores and warehouses and shows their names",
    async () => {
      vi.spyOn(api, "fetchQueries").mockResolvedValue([unifiedQuery] as any);
      vi.spyOn(api, "fetchTiendas").mockResolvedValue([
        { codigo: "1011", nombre: "SUC CALIDOSO LIBERTAD", zona: "ORIENTE", tipo: "Tienda" },
        { codigo: "2010", nombre: "BODEGA CREACION", zona: "ORIENTE", tipo: "Bodega" },
      ]);
      const runQueryMock = vi
        .spyOn(api, "runQuery")
        .mockResolvedValue(salesDetail(7, "SUC CALIDOSO LIBERTAD: 7") as any)
        .mockResolvedValueOnce(unifiedResult as any)
        .mockResolvedValueOnce(salesDetail(67, "BODEGA CREACION: 50 | SUC CALIDOSO LIBERTAD: 7") as any)
        .mockResolvedValueOnce(salesDetail(50, "BODEGA CREACION: 50") as any)
        .mockResolvedValueOnce(salesDetail(57, "BODEGA CREACION: 50 | SUC CALIDOSO LIBERTAD: 7") as any);

      const { findByRole, findByText, findByLabelText, getByText, queryByRole } = render(<App />);
      (await findByRole("button", { name: /ejecutar/i })).click();
      await findByText("REF-1");

      (await findByRole("button", { name: "Ventas" })).click();
      await waitFor(() => expect(runQueryMock).toHaveBeenCalledTimes(2));
      expect(runQueryMock.mock.calls[1][0]).toBe("ventas");
      expect(runQueryMock.mock.calls[1][1]).not.toHaveProperty("tiendaExistencia");
      // La columna con los nombres aparece en la tabla.
      await findByText("Existencia por tienda");
      // La celda muestra un resumen y "Ver" abre el desglose separado en bodegas y tiendas.
      fireEvent.click(await findByRole("button", { name: "Ver 2 lugares" }));
      const dialog = await findByRole("dialog");
      expect(within(dialog).getByText("BODEGA CREACION")).toBeTruthy();
      expect(within(dialog).getByText("SUC CALIDOSO LIBERTAD")).toBeTruthy();
      expect(within(dialog).getByText("50")).toBeTruthy();
      fireEvent.click(within(dialog).getByRole("button", { name: "Cerrar" }));
      await waitFor(() => expect(queryByRole("dialog")).toBeNull());

      // Grupos separados y casillas con el nombre de cada tienda/bodega.
      expect(getByText("Tiendas")).toBeTruthy();
      expect(getByText("Bodegas")).toBeTruthy();

      fireEvent.click(await findByLabelText("BODEGA CREACION"));
      await waitFor(() => expect(runQueryMock).toHaveBeenCalledTimes(3));
      expect(runQueryMock.mock.calls[2][1]).toMatchObject({ tiendaExistencia: "2010", codigoBarras: "111" });

      const tiendaCheckbox = await findByLabelText("SUC CALIDOSO LIBERTAD");
      // Mientras carga, la lista queda deshabilitada.
      await waitFor(() => expect(tiendaCheckbox.matches(":disabled")).toBe(false));
      fireEvent.click(tiendaCheckbox);
      await waitFor(() => expect(runQueryMock).toHaveBeenCalledTimes(4));
      expect(runQueryMock.mock.calls[3][1]).toMatchObject({ tiendaExistencia: "2010,1011" });
      await findByText("BODEGA CREACION + SUC CALIDOSO LIBERTAD");

      // Con todas las bodegas ya marcadas, el botón del grupo las quita de un clic.
      const bodegasButton = await findByRole("button", { name: "Quitar todas las bodegas" });
      await waitFor(() => expect(bodegasButton.matches(":disabled")).toBe(false));
      fireEvent.click(bodegasButton);
      await waitFor(() => expect(runQueryMock).toHaveBeenCalledTimes(5));
      expect(runQueryMock.mock.calls[4][1]).toMatchObject({ tiendaExistencia: "1011" });

      // Y "Todas las bodegas" las vuelve a marcar.
      const marcarBodegas = await findByRole("button", { name: "Todas las bodegas" });
      await waitFor(() => expect(marcarBodegas.matches(":disabled")).toBe(false));
      fireEvent.click(marcarBodegas);
      await waitFor(() => expect(runQueryMock).toHaveBeenCalledTimes(6));
      expect(runQueryMock.mock.calls[5][1]).toMatchObject({ tiendaExistencia: "1011,2010" });
    },
    15000,
  );
});
