import { describe, expect, it } from "vitest";
import { formatCellValue } from "./App";

describe("formatCellValue", () => {
  it("muestra Vendido como porcentaje con 2 decimales", () => {
    expect(formatCellValue("Vendido", 31.39)).toBe("31.39%");
    expect(formatCellValue("Vendido", 3.846153846)).toBe("3.85%");
    expect(formatCellValue("Vendido", "22.24")).toBe("22.24%");
  });

  it("deja Vendido vacio cuando no hay ventas", () => {
    expect(formatCellValue("Vendido", "")).toBe("");
    expect(formatCellValue("Vendido", null)).toBe("");
  });

  it("no toca las demas columnas", () => {
    expect(formatCellValue("Quedan", 988)).toBe("988");
    expect(formatCellValue("Codigo Barra", "3300000003757")).toBe("3300000003757");
  });
});
