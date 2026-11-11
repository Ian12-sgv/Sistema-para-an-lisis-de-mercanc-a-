import React from "react";
import { vi, describe, it, afterEach, expect } from "vitest";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
Object.defineProperty(globalThis, "window", { value: dom.window, configurable: true });
Object.defineProperty(globalThis, "document", { value: dom.window.document, configurable: true });
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });

import { cleanup, render, waitFor } from "@testing-library/react";
import * as api from "./api";
import { App } from "./App";

const kardexQuery = {
  id: "kardex",
  name: "Kardex",
  description: "desc",
  parameters: [{ name: "fechaDesde", label: "Fecha desde", type: "date", required: true }],
};

function kardexResult(barcodes: string[], isLoading: boolean) {
  return {
    queryId: "kardex",
    columns: ["CodigoBarra"],
    rows: barcodes.map((code) => ({ CodigoBarra: code })),
    rowCount: barcodes.length,
    totalRows: barcodes.length,
    page: 1,
    pageSize: 100,
    totalPages: 1,
    isLoading,
    isComplete: !isLoading,
  };
}

describe("App snapshot polling", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it(
    "polls only the lightweight status and re-runs the query once when the snapshot is ready",
    async () => {
      vi.spyOn(api, "fetchQueries").mockResolvedValue([kardexQuery] as any);
      const runQueryMock = vi
        .spyOn(api, "runQuery")
        .mockResolvedValueOnce(kardexResult(["PARCIAL-1"], true) as any)
        .mockResolvedValueOnce(kardexResult(["COMPLETO-1", "COMPLETO-2"], false) as any);
      const statusMock = vi
        .spyOn(api, "fetchSnapshotStatus")
        .mockResolvedValueOnce({ queryId: "kardex", ready: false, building: true })
        .mockResolvedValueOnce({ queryId: "kardex", ready: true, building: false });

      const { findByRole, findByText } = render(<App />);
      (await findByRole("button", { name: /ejecutar/i })).click();

      await findByText("PARCIAL-1");
      await findByText("COMPLETO-2", undefined, { timeout: 10000 });

      expect(statusMock).toHaveBeenCalledTimes(2);
      expect(runQueryMock).toHaveBeenCalledTimes(2);

      const firstRunParameters = runQueryMock.mock.calls[0][1];
      expect(statusMock.mock.calls[0]).toEqual(["kardex", firstRunParameters]);
      expect(runQueryMock.mock.calls[1]).toEqual(runQueryMock.mock.calls[0]);
    },
    15000,
  );

  it(
    "stops polling and shows an error when the snapshot build failed",
    async () => {
      vi.spyOn(api, "fetchQueries").mockResolvedValue([kardexQuery] as any);
      const runQueryMock = vi.spyOn(api, "runQuery").mockResolvedValue(kardexResult(["PARCIAL-1"], true) as any);
      const statusMock = vi
        .spyOn(api, "fetchSnapshotStatus")
        .mockResolvedValue({ queryId: "kardex", ready: false, building: false });

      const { findByRole, findByText } = render(<App />);
      (await findByRole("button", { name: /ejecutar/i })).click();

      await findByText(/no se pudo preparar la consulta completa/i, undefined, { timeout: 10000 });
      await new Promise((resolve) => setTimeout(resolve, 2500));

      expect(statusMock).toHaveBeenCalledTimes(1);
      expect(runQueryMock).toHaveBeenCalledTimes(1);
    },
    15000,
  );
});
