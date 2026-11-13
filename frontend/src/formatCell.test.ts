import { describe, expect, it } from "vitest";
import { formatCellValue } from "./App";

describe("formatCellValue", () => {
  it("muestra Vendido como porcentaje con 2 decimales", () => {
    expect(formatCellValue("Vendido", 31.39)).toBe("31.39%");
    expect(formatCellValue("Vendido", 3.846153846)).toBe("3.85%");
    expect(formatCellValue("Vendido", "22.24")).toBe("22.24%");
  });

  it("muestra Quedan como el porcentaje que falta por vender", () => {
    expect(formatCellValue("Quedan", 988, { Vendido: 31.39, Quedan: 988 })).toBe("68.61%");
    expect(formatCellValue("Quedan", 923, { Vendido: 3.846153846, Quedan: 923 })).toBe("96.15%");
  });

  it("deja Vendido y Quedan vacios cuando no hay ventas", () => {
    expect(formatCellValue("Vendido", "")).toBe("");
    expect(formatCellValue("Vendido", null)).toBe("");
    expect(formatCellValue("Quedan", "", { Vendido: "", Quedan: "" })).toBe("");
  });

  it("no toca las demas columnas", () => {
    expect(formatCellValue("Unidades vendidas", 450)).toBe("450");
    expect(formatCellValue("Codigo Barra", "3300000003757")).toBe("3300000003757");
  });
});
