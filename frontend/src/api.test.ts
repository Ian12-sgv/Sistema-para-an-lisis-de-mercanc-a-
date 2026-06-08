import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runQuery } from "./api";

describe("api runQuery", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      } as Response),
    ) as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    vi.resetAllMocks();
    globalThis.fetch = originalFetch;
  });

  it("sends queryId, parameters, page and pageSize", async () => {
    await runQuery("ventas", { fechaDesde: "2026-05-14" }, 2, 50);

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = (globalThis.fetch as any).mock.calls[0];

    expect(url).toContain("/api/queries/run");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      queryId: "ventas",
      parameters: { fechaDesde: "2026-05-14" },
      page: 2,
      pageSize: 50,
    });
  });

  it("includes provided unified filters in the request body for consulta_unificada", async () => {
    await runQuery(
      "consulta_unificada",
      {
        fechaDesde: "2026-05-14",
        fechaHasta: "2026-05-21",
        codigoBarra: "5029900018767",
      },
      1,
      200,
    );

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const [_, options] = (globalThis.fetch as any).mock.calls[0];

    expect(JSON.parse(options.body)).toEqual({
      queryId: "consulta_unificada",
      parameters: {
        fechaDesde: "2026-05-14",
        fechaHasta: "2026-05-21",
        codigoBarra: "5029900018767",
      },
      page: 1,
      pageSize: 200,
    });
  });
});
