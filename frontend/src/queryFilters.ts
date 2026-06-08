export const TABLE_FILTERS = [
  { key: "codigoBarra", label: "Codigo de barra", columns: ["Codigo Barra", "CodigoBarra"] },
  { key: "referencia", label: "Referencia", columns: ["Referencias", "Referencia"] },
  { key: "codigoMarca", label: "Codigo de marca", columns: ["Codigo Marca", "CodigoMarca"] },
  { key: "nombreMarca", label: "Nombre de marca", columns: ["Nombre Marca", "Marca"] },
  { key: "categoria", label: "Categoria", columns: ["Nombre Categoria", "Codigo Categoria"] },
] as const;

export type TableFilterKey = (typeof TABLE_FILTERS)[number]["key"];
export type UnifiedAdjustmentFilter = "positive" | "negative" | "both";

export type TableFilters = Record<TableFilterKey, string>;
export type UnifiedAdjustmentFilters = Record<UnifiedAdjustmentFilter, boolean>;

function toNumber(value: unknown) {
  if (typeof value === "number") return value;
  const parsedValue = Number(String(value ?? "").replace(",", "."));

  return Number.isFinite(parsedValue) ? parsedValue : 0;
}

export function buildQueryRunParameters(
  queryId: string,
  parameterValues: Record<string, string>,
  tableFilters: TableFilters,
) {
  const trimmedFilters = Object.fromEntries(
    Object.entries(tableFilters)
      .map(([key, value]) => [key, value.trim()])
      .filter(([_key, value]) => value),
  );

  return {
    ...parameterValues,
    ...trimmedFilters,
  };
}

export function filterRowsForCurrentPage(
  queryId: string | null,
  rows: Record<string, unknown>[],
  tableFilters: TableFilters,
) {
  return rows.filter((row) => {
    const matchesTextFilters = TABLE_FILTERS.every((filter) => {
      const filterValue = tableFilters[filter.key].trim().toLowerCase();

      if (!filterValue) return true;

      return filter.columns.some((column) =>
        String(row[column] ?? "")
          .toLowerCase()
          .includes(filterValue),
      );
    });

    if (!matchesTextFilters) return false;

    return true;
  });
}

export function filterRowsByAdjustment(
  queryId: string | null,
  rows: Record<string, unknown>[],
  unifiedAdjustmentFilters: UnifiedAdjustmentFilters,
) {
  if (queryId !== "consulta_unificada") return rows;

  return rows.filter((row) => {
    const hasPositiveAdjustment = toNumber(row["Unidades de Ajustes Positivos"]) > 0;
    const hasNegativeAdjustment = toNumber(row["Unidades de Ajustes Negativos"]) > 0;

    if (unifiedAdjustmentFilters.both) return hasPositiveAdjustment && hasNegativeAdjustment;

    if (!unifiedAdjustmentFilters.positive && !unifiedAdjustmentFilters.negative) return true;

    return (
      (unifiedAdjustmentFilters.positive && hasPositiveAdjustment) ||
      (unifiedAdjustmentFilters.negative && hasNegativeAdjustment)
    );
  });
}
