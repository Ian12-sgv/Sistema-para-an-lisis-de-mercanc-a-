import { BarChart3, ChevronLeft, ChevronRight, Database, Download, FileSpreadsheet, Menu, Moon, Play, RefreshCw, Sun } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { fetchDashboardSummary, fetchQueries, runQuery } from "./api";
import {
  buildQueryRunParameters,
  filterRowsByAdjustment,
  filterRowsForCurrentPage,
  TABLE_FILTERS,
  type TableFilterKey,
  type UnifiedAdjustmentFilter,
} from "./queryFilters";
import type { DashboardSummary, QueryDefinition, QueryResult, UnifiedQueryResult } from "./types";

type ResultState = QueryResult | UnifiedQueryResult | null;
const PAGE_SIZE = 100;
const EXPORT_PAGE_SIZE = 1000;
const MAX_EXPORT_PAGES = 10000;
const DASHBOARD_ID = "__dashboard";
const SALES_COLUMNS = [
  "Existencia actual",
  "Suma Existencia",
  "Unidades vendidas",
  "Suma Cantidades ventas",
  "NumeroFactura",
  "FechaVenta",
  "Tienda",
  "Region",
  "PrecioDetal",
  "CostoDolar",
  "PrecioMayor",
  "PrecioPromocion",
  "Utilidad por ventas",
] as const;
const KARDEX_COLUMNS = [
  "Costo Inicial",
  "Unidades de Ajustes Positivos",
  "% Ajustes Positivos",
  "Unidades de Ajustes Negativos",
  "% Ajustes Negativos",
  "Utilidad perdida por ajustes",
  "% Utilidad perdida por ajustes",
] as const;
const TRANSFER_COLUMNS = [
  "Transferencia matriz",
  "Transferencia sucursal",
  "Codigo envia",
  "Codigo recibe",
  "Fecha emision transferencia",
  "Fecha carga transferencia",
  "Numero transferencia",
  "Tienda kardex transferencia",
] as const;
const DETAIL_COLUMNS = [...KARDEX_COLUMNS, ...TRANSFER_COLUMNS, ...SALES_COLUMNS] as const;
const EMPTY_TABLE_FILTERS = {
  codigoBarra: "",
  referencia: "",
  codigoMarca: "",
  nombreMarca: "",
  categoria: "",
} satisfies Record<TableFilterKey, string>;

type ChartItem = { label: string; value: number; percent: number };

function buildPageCacheKey(queryId: string, parameters: Record<string, string>, page: number, pageSize = PAGE_SIZE) {
  return JSON.stringify({
    queryId,
    parameters,
    page,
    pageSize,
  });
}

function buildQueryStateKey(queryId: string, parameters: Record<string, string>) {
  return JSON.stringify({
    queryId,
    parameters,
    pageSize: PAGE_SIZE,
  });
}

interface SavedQueryState {
  page: number;
  result: QueryResult;
}

function formatExportValue(value: unknown) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

function buildExportFileName(queryName: string, extension: "csv" | "xls") {
  const safeName = queryName
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  const dateStamp = new Date().toISOString().slice(0, 10);

  return `${safeName || "consulta"}_${dateStamp}.${extension}`;
}

function downloadBlob(content: string, fileName: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadCsv(queryName: string, columns: string[], rows: Record<string, unknown>[]) {
  const shouldForceCsvText = (column: string, value: unknown) => {
    const text = formatExportValue(value);
    const normalizedColumn = column
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();

    return (
      text !== "" &&
      /(codigo|barra|referencia|documento|factura|marca|categoria|linea|fabricante|proveedor|tienda)/.test(
        normalizedColumn,
      )
    );
  };
  const escapeCsvValue = (column: string, value: unknown) => {
    const text = formatExportValue(value);

    if (shouldForceCsvText(column, value)) {
      return `="${text.replace(/"/g, '""')}"`;
    }

    return /[",\r\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const content = [
    "sep=;",
    columns.map((column) => escapeCsvValue(column, column)).join(";"),
    ...rows.map((row) => columns.map((column) => escapeCsvValue(column, row[column])).join(";")),
  ].join("\r\n");

  downloadBlob(`\uFEFF${content}`, buildExportFileName(queryName, "csv"), "text/csv;charset=utf-8;");
}

function downloadExcel(queryName: string, columns: string[], rows: Record<string, unknown>[]) {
  const escapeHtml = (value: unknown) =>
    formatExportValue(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  const tableHead = columns.map((column) => `<th class="text-cell">${escapeHtml(column)}</th>`).join("");
  const tableRows = rows
    .map((row) => `<tr>${columns.map((column) => `<td class="text-cell">${escapeHtml(row[column])}</td>`).join("")}</tr>`)
    .join("");
  const content = `
    <html>
      <head>
        <meta charset="utf-8" />
        <style>
          table { border-collapse: collapse; }
          th, td { border: 1px solid #d9e2ea; padding: 6px 8px; font-family: Arial, sans-serif; font-size: 12px; }
          th { background: #eef4f8; font-weight: 700; }
          .text-cell { mso-number-format:"\\@"; }
        </style>
      </head>
      <body>
        <table>
          <thead><tr>${tableHead}</tr></thead>
          <tbody>${tableRows}</tbody>
        </table>
      </body>
    </html>
  `;

  downloadBlob(content, buildExportFileName(queryName, "xls"), "application/vnd.ms-excel;charset=utf-8;");
}

function toNumber(value: unknown) {
  if (typeof value === "number") return value;
  const parsedValue = Number(String(value ?? "").replace(",", "."));

  return Number.isFinite(parsedValue) ? parsedValue : 0;
}

function roundMetric(value: number) {
  return Math.round(value * 100) / 100;
}

function pickRowValue(row: Record<string, unknown>, columns: string[]) {
  for (const column of columns) {
    const value = row[column];

    if (value !== null && value !== undefined && String(value).trim() !== "") {
      return String(value);
    }
  }

  return "Sin dato";
}

function buildTopChartItems(rows: Record<string, unknown>[], columns: string[], limit = 8): ChartItem[] {
  const counts = new Map<string, number>();

  rows.forEach((row) => {
    const label = pickRowValue(row, columns);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  });

  const items = Array.from(counts.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((left, right) => right.value - left.value)
    .slice(0, limit);
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  return items.map((item) => ({
    ...item,
    percent: Math.max(4, (item.value / maxValue) * 100),
  }));
}

function sumFirstAvailableColumn(rows: Record<string, unknown>[], columns: string[]) {
  return rows.reduce((total, row) => total + toNumber(row[columns.find((column) => column in row) ?? ""]), 0);
}

function groupRowsByBarcode(rows: Record<string, unknown>[]) {
  const grouped = new Map<string, Record<string, unknown>[]>();

  rows.forEach((row) => {
    const barcode = String(row["Codigo Barra"] ?? row.CodigoBarra ?? "").trim();

    if (!barcode) return;

    grouped.set(barcode, [...(grouped.get(barcode) ?? []), row]);
  });

  return grouped;
}

function buildBaseMetrics(rowsByBarcode: Map<string, Record<string, unknown>>) {
  return Object.fromEntries(
    Array.from(rowsByBarcode.entries()).map(([codigoBarra, row]) => [
      codigoBarra,
      {
        cantidadCompra: toNumber(row["Cantidad de compra"]),
        sumaUnidadesCompras: toNumber(row["Suma Unidades Compras"]),
        costoInicial: toNumber(row["Costo Inicial"]),
      },
    ]),
  );
}

export function App() {
  const [queries, setQueries] = useState<QueryDefinition[]>([]);
  const [activeQueryId, setActiveQueryId] = useState<string | null>(null);
  const [parameterValues, setParameterValues] = useState<Record<string, string>>({
    fechaDesde: "2026-05-10",
    fechaHasta: "2026-05-11",
  });
  const [result, setResult] = useState<ResultState>(null);
  const [page, setPage] = useState(1);
  const [loadingQueries, setLoadingQueries] = useState(false);
  const [runningQueryId, setRunningQueryId] = useState<string | null>(null);
  const [exportingFormat, setExportingFormat] = useState<"csv" | "excel" | null>(null);
  const [loadingDashboard, setLoadingDashboard] = useState(false);
  const [loadingUnifiedDetail, setLoadingUnifiedDetail] = useState<"kardex" | "transferencias_tiendas" | "ventas" | null>(null);
  const [hasExecuted, setHasExecuted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tableFilters, setTableFilters] = useState<Record<TableFilterKey, string>>({
    codigoBarra: "",
    referencia: "",
    codigoMarca: "",
    nombreMarca: "",
    categoria: "",
  });
  const [unifiedAdjustmentFilters, setUnifiedAdjustmentFilters] = useState<Record<UnifiedAdjustmentFilter, boolean>>({
    positive: false,
    negative: false,
    both: false,
  });
  const [dashboardSummary, setDashboardSummary] = useState<DashboardSummary | null>(null);
  const [unifiedDetailsByBarcode, setUnifiedDetailsByBarcode] = useState<Record<string, Record<string, unknown>>>({});
  const [unifiedDetailMessage, setUnifiedDetailMessage] = useState<string | null>(null);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isDarkTheme, setIsDarkTheme] = useState(false);
  const pageCacheRef = useRef(new Map<string, QueryResult>());
  const queryStateRef = useRef(new Map<string, SavedQueryState>());

  const activeQuery = queries.find((query) => query.id === activeQueryId) ?? null;
  const resultColumns = result?.columns ?? [];
  const resultRows = result?.rows ?? [];
  const totalRows = result && "totalRows" in result ? result.totalRows : resultRows.length;
  const totalPages = result && "totalPages" in result ? result.totalPages : 1;
  const isResultLoading = result && "isLoading" in result ? result.isLoading : false;
  const isResultComplete = result && "isComplete" in result ? result.isComplete : true;
  const isRunningActiveQuery = Boolean(activeQueryId && runningQueryId === activeQueryId);
  const isDashboard = activeQueryId === DASHBOARD_ID;
  const isUnifiedQuery = activeQueryId === "consulta_unificada";
  const pageRows = useMemo(() => {
    return filterRowsForCurrentPage(activeQueryId, resultRows, tableFilters);
  }, [activeQueryId, resultRows, tableFilters]);
  const mergedRows = useMemo(() => {
    if (!isUnifiedQuery) return pageRows;

    return pageRows.map((row) => {
      const salesData = unifiedDetailsByBarcode[getRowBarcode(row)];

      if (!salesData) return row;

      return {
        ...row,
        ...salesData,
      };
    });
  }, [isUnifiedQuery, pageRows, unifiedDetailsByBarcode]);
  const visibleRows = useMemo(() => {
    return filterRowsByAdjustment(activeQueryId, mergedRows, unifiedAdjustmentFilters);
  }, [activeQueryId, mergedRows, unifiedAdjustmentFilters]);
  const visibleColumns = useMemo(() => {
    if (!isUnifiedQuery) return resultColumns;

    const columns = [...resultColumns];
    const loadedDetails = Object.values(unifiedDetailsByBarcode);

    DETAIL_COLUMNS.forEach((column) => {
      if (!columns.includes(column) && loadedDetails.some((detail) => column in detail)) columns.push(column);
    });

    return columns;
  }, [isUnifiedQuery, resultColumns, unifiedDetailsByBarcode]);
  const canDownload = Boolean(activeQuery && resultColumns.length > 0 && resultRows.length > 0);
  const resultLabel = useMemo(() => {
    if (!result) return "Sin resultados";
    const firstRow = resultRows.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
    const lastRow = Math.min((page - 1) * PAGE_SIZE + resultRows.length, totalRows);
    return isResultComplete
      ? `${firstRow}-${lastRow} de ${totalRows} filas`
      : `${firstRow}-${lastRow} de ${totalRows}+ filas cargadas`;
  }, [isResultComplete, page, result, resultRows.length, totalRows]);

  async function loadQueries() {
    setLoadingQueries(true);
    setError(null);

    try {
      const data = await fetchQueries();
      setQueries(data);
      setActiveQueryId((current) => current ?? data[0]?.id ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "No se pudieron cargar las consultas.");
    } finally {
      setLoadingQueries(false);
    }
  }

  async function handleRunSingle(queryId: string, requestedPage = 1) {
    return handleRunSingleWithParameters(queryId, buildRunParameters(queryId), requestedPage);
  }

  function buildRunParameters(queryId: string) {
    return buildQueryRunParameters(queryId, parameterValues, EMPTY_TABLE_FILTERS);
  }

  async function handleRunSingleWithParameters(
    queryId: string,
    parameters: Record<string, string>,
    requestedPage = 1,
  ) {
    const cacheKey = buildPageCacheKey(queryId, parameters, requestedPage);
    const cachedResult = pageCacheRef.current.get(cacheKey);

    if (cachedResult) {
      setHasExecuted(true);
      setResult(cachedResult);
      setPage(requestedPage);
      setError(null);
      queryStateRef.current.set(buildQueryStateKey(queryId, parameters), {
        page: requestedPage,
        result: cachedResult,
      });
      return;
    }

    setRunningQueryId(queryId);
    setHasExecuted(true);
    setResult((current) => (requestedPage === 1 ? null : current));
    setPage(requestedPage);
    setError(null);

    try {
      const nextResult = await runQuery(queryId, parameters, requestedPage, PAGE_SIZE);
      pageCacheRef.current.set(cacheKey, nextResult);
      queryStateRef.current.set(buildQueryStateKey(queryId, parameters), {
        page: requestedPage,
        result: nextResult,
      });
      setResult((current) => {
        // If we already have a non-empty first page and the new result is a loading
        // preview with empty rows, keep the current rows to avoid flicker.
        if (
          requestedPage === 1 &&
          current &&
          Array.isArray(current.rows) &&
          current.rows.length > 0 &&
          nextResult &&
          "isLoading" in nextResult &&
          nextResult.isLoading === true &&
          Array.isArray(nextResult.rows) &&
          nextResult.rows.length === 0
        ) {
          return current;
        }

        return nextResult;
      });
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "No se pudo ejecutar la consulta.");
    } finally {
      setRunningQueryId((current) => (current === queryId ? null : current));
    }
  }

  async function fetchCompleteQueryRows(queryId: string, initialColumns: string[] = []) {
    const allRows: Record<string, unknown>[] = [];
    let columns = initialColumns;
    let exportPage = 1;
    let isComplete = false;
    let totalRows = 0;
    const runParameters = buildRunParameters(queryId);

    while (!isComplete && exportPage <= MAX_EXPORT_PAGES) {
      const cacheKey = buildPageCacheKey(queryId, runParameters, exportPage, EXPORT_PAGE_SIZE);
      const cachedResult = pageCacheRef.current.get(cacheKey);
      const nextResult = cachedResult ?? (await runQuery(queryId, runParameters, exportPage, EXPORT_PAGE_SIZE));

      if (!cachedResult) {
        pageCacheRef.current.set(cacheKey, nextResult);
      }

      columns = nextResult.columns;
      allRows.push(...nextResult.rows);
      totalRows = nextResult.totalRows;
      isComplete = nextResult.isComplete || nextResult.rows.length === 0;
      exportPage += 1;
    }

    if (!isComplete) {
      throw new Error("La exportacion supero el limite de paginas permitido.");
    }

    return { columns, rows: allRows, totalRows: Math.max(totalRows, allRows.length) };
  }

  async function getExportRows(queryId: string) {
    return fetchCompleteQueryRows(queryId, resultColumns);
  }

  async function loadDashboardData() {
    setLoadingDashboard(true);
    setError(null);

    try {
      const summary = await fetchDashboardSummary(parameterValues);
      setDashboardSummary(summary);
    } catch (dashboardError) {
      setError(dashboardError instanceof Error ? dashboardError.message : "No se pudo cargar el dashboard.");
    } finally {
      setLoadingDashboard(false);
    }
  }

  async function handleDownload(format: "csv" | "excel") {
    if (!activeQuery) return;

    setExportingFormat(format);
    setError(null);

    try {
      const exportData = await getExportRows(activeQuery.id);

      if (format === "csv") {
        downloadCsv(activeQuery.name, exportData.columns, exportData.rows);
      } else {
        downloadExcel(activeQuery.name, exportData.columns, exportData.rows);
      }
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "No se pudo descargar la consulta completa.");
    } finally {
      setExportingFormat(null);
    }
  }

  function updateParameter(name: string, value: string) {
    setParameterValues((current) => ({
      ...current,
      [name]: value,
    }));
    setResult(null);
    setUnifiedDetailsByBarcode({});
    setUnifiedDetailMessage(null);
    setHasExecuted(false);
    setPage(1);
  }

  function openDashboard() {
    setActiveQueryId(DASHBOARD_ID);
    setError(null);
  }

  function updateTableFilter(key: TableFilterKey, value: string) {
    setTableFilters((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function updateUnifiedAdjustmentFilter(key: UnifiedAdjustmentFilter, value: boolean) {
    setUnifiedAdjustmentFilters((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function getRowBarcode(row: Record<string, unknown>) {
    const barcode = row["Codigo Barra"] ?? row["CodigoBarra"];
    return String(barcode ?? "").trim();
  }

  function buildSalesSummary(rows: Record<string, unknown>[], baseRow: Record<string, unknown>) {
    if (rows.length === 0) return {};

    const firstRow = rows[0];
    const unitsSold =
      toNumber(firstRow["Suma Cantidades ventas"]) || rows.reduce((total, row) => total + toNumber(row.Cantidad), 0);
    const initialCost = toNumber(baseRow["Costo Inicial"]) || toNumber(firstRow.CostoDolar);

    return {
      "Existencia actual": firstRow.Existencia,
      "Suma Existencia": firstRow["Suma Existencia"],
      "Unidades vendidas": unitsSold,
      "Suma Cantidades ventas": firstRow["Suma Cantidades ventas"] ?? unitsSold,
      NumeroFactura: firstRow.NumeroFactura,
      FechaVenta: firstRow.FechaVenta,
      Tienda: firstRow.Tienda,
      Region: firstRow.Region,
      PrecioDetal: firstRow.PrecioDetal,
      CostoDolar: firstRow.CostoDolar,
      PrecioMayor: firstRow.PrecioMayor,
      PrecioPromocion: firstRow.PrecioPromocion,
      "Utilidad por ventas": initialCost * unitsSold,
    };
  }

  function buildKardexSummary(rows: Record<string, unknown>[], baseRow: Record<string, unknown>) {
    if (rows.length === 0) return {};

    const costoInicial = toNumber(rows[0].CostoInicial);
    const cantidadCompra = toNumber(baseRow["Cantidad de compra"]);
    const ajustesPositivos = rows.reduce(
      (total, row) => total + (String(row.Tipo ?? "").trim().toLowerCase() === "entrada" ? toNumber(row.Cantidad) : 0),
      0,
    );
    const ajustesNegativos = rows.reduce(
      (total, row) => total + (String(row.Tipo ?? "").trim().toLowerCase() === "salida" ? Math.abs(toNumber(row.Cantidad)) : 0),
      0,
    );
    const utilidadPerdida = costoInicial * ajustesNegativos;

    return {
      "Costo Inicial": costoInicial,
      "Unidades de Ajustes Positivos": ajustesPositivos,
      "% Ajustes Positivos": ajustesPositivos ? roundMetric(cantidadCompra / ajustesPositivos) : "",
      "Unidades de Ajustes Negativos": ajustesNegativos,
      "% Ajustes Negativos": ajustesNegativos ? roundMetric(cantidadCompra / ajustesNegativos) : "",
      "Utilidad perdida por ajustes": utilidadPerdida,
      "% Utilidad perdida por ajustes": utilidadPerdida ? roundMetric(cantidadCompra / utilidadPerdida) : "",
    };
  }

  function buildTransferSummary(rows: Record<string, unknown>[]) {
    if (rows.length === 0) return {};

    const firstRow = rows[0];

    return {
      "Transferencia matriz": firstRow.MATRIZ,
      "Transferencia sucursal": firstRow.SUCURSAL,
      "Codigo envia": firstRow.CodigoEnvia,
      "Codigo recibe": firstRow.CodigoRecibe,
      "Fecha emision transferencia": firstRow.FechaEmision,
      "Fecha carga transferencia": firstRow.FECHACARGATRANSFERENCIA,
      "Numero transferencia": firstRow.Numero,
      "Tienda kardex transferencia": firstRow.dimid_tienda,
    };
  }

  async function loadUnifiedDetailForFilteredRows(queryId: "kardex" | "transferencias_tiendas" | "ventas") {
    const rowsWithBarcode = pageRows.filter((row) => getRowBarcode(row));
    const uniqueRowsByBarcode = new Map<string, Record<string, unknown>>();

    rowsWithBarcode.forEach((row) => {
      const barcode = getRowBarcode(row);
      if (!uniqueRowsByBarcode.has(barcode)) uniqueRowsByBarcode.set(barcode, row);
    });

    if (uniqueRowsByBarcode.size === 0) {
      setError("No hay articulos visibles con codigo de barra para cargar detalle.");
      return;
    }

    setLoadingUnifiedDetail(queryId);
    setError(null);
    setUnifiedDetailMessage(null);

    try {
      const nextDetailsByBarcode: Record<string, Record<string, unknown>> = {};
      let loadedCount = 0;

      const codigoBarras = Array.from(uniqueRowsByBarcode.keys());
      const detailResult = await runQuery(
        queryId,
        {
          ...parameterValues,
          detalleUnificada: "1",
          codigoBarras: codigoBarras.join(","),
          baseMetrics: JSON.stringify(buildBaseMetrics(uniqueRowsByBarcode)),
        },
        1,
        EXPORT_PAGE_SIZE,
      );
      const detailRowsByBarcode = groupRowsByBarcode(detailResult.rows);

      for (const codigoBarra of uniqueRowsByBarcode.keys()) {
        const detailRows = detailRowsByBarcode.get(codigoBarra) ?? [];
        const summary = detailRows[0] ?? {};

        if (Object.keys(summary).length > 0) {
          loadedCount += 1;
          nextDetailsByBarcode[codigoBarra] = summary;
        }
      }

      if (loadedCount === 0) {
        setUnifiedDetailMessage("No se encontraron datos de detalle para los articulos visibles.");
        return;
      }

      setUnifiedDetailsByBarcode((current) => {
        const merged = { ...current };

        Object.entries(nextDetailsByBarcode).forEach(([codigoBarra, detail]) => {
          merged[codigoBarra] = {
            ...(merged[codigoBarra] ?? {}),
            ...detail,
          };
        });

        return merged;
      });
      setUnifiedDetailMessage(`Detalle cargado para ${loadedCount} de ${uniqueRowsByBarcode.size} articulos visibles.`);
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : "No se pudo cargar el detalle filtrado.");
    } finally {
      setLoadingUnifiedDetail(null);
    }
  }

  function restoreQueryState(queryId: string) {
    const runParameters = buildRunParameters(queryId);
    const savedState = queryStateRef.current.get(buildQueryStateKey(queryId, runParameters));

    setActiveQueryId(queryId);
    setError(null);

    if (savedState) {
      setResult(savedState.result);
      setPage(savedState.page);
      setHasExecuted(true);
      return;
    }

    setResult(null);
    setHasExecuted(false);
    setPage(1);
  }

  useEffect(() => {
    void loadQueries();
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = isDarkTheme ? "dark" : "light";
  }, [isDarkTheme]);

  // Cuando el backend indique que está "isLoading" (construyendo snapshot), sondeamos periódicamente
  useEffect(() => {
    if (!activeQuery || !result || !("isLoading" in result) || !result.isLoading) return;

    let cancelled = false;

    const poll = async () => {
      try {
        const runParameters = buildRunParameters(activeQuery.id);
        const updated = await runQuery(activeQuery.id, runParameters, result.page ?? 1, PAGE_SIZE);

        if (cancelled) return;

        pageCacheRef.current.set(buildPageCacheKey(activeQuery.id, runParameters, updated.page), updated);
        setResult(updated);

        if ("isLoading" in updated && updated.isLoading) {
          setTimeout(poll, 1500);
        }
      } catch (err) {
        // silencioso: no bloquear la UI por errores de sondeo
        if (!cancelled) setTimeout(poll, 2000);
      }
    };

    void poll();

    return () => {
      cancelled = true;
    };
  }, [activeQuery, isResultLoading, parameterValues]);

  useEffect(() => {
    if (!activeQuery || !hasExecuted || !isResultLoading || isRunningActiveQuery) return;

    const timer = window.setTimeout(() => {
      void handleRunSingle(activeQuery.id, page);
    }, 1200);

    return () => window.clearTimeout(timer);
  }, [activeQuery, hasExecuted, isResultLoading, isRunningActiveQuery, page]);

  return (
    <main className={`app-shell ${isSidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <Database size={24} aria-hidden />
          <div>
            <h1>Unificador Consultas</h1>
            <p>SQL Server + FastAPI</p>
          </div>
        </div>

        <div className="toolbar">
          <button type="button" className="icon-button" onClick={loadQueries} title="Recargar consultas" disabled={loadingQueries}>
            <RefreshCw size={18} aria-hidden />
          </button>
          <span>{queries.length} consultas</span>
        </div>

        <nav className="query-list" aria-label="Vistas por consulta">
          <button
            type="button"
            className={`query-nav-item dashboard-nav-item ${isDashboard ? "is-active" : ""}`}
            onClick={openDashboard}
          >
            <span>
              <strong>Dashboard</strong>
              <small>Graficas de los datos cargados.</small>
            </span>
          </button>
          {queries.map((query) => (
            <button
              type="button"
              className={`query-nav-item ${activeQueryId === query.id ? "is-active" : ""}`}
              key={query.id}
              onClick={() => restoreQueryState(query.id)}
            >
              <span>
                <strong>{query.name}</strong>
                <small>{query.description}</small>
              </span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="workspace">
        <header className="workspace-header">
          <div className="header-leading">
            <div className="header-controls">
              <button
                type="button"
                className="icon-button"
                onClick={() => setIsSidebarCollapsed((current) => !current)}
                title={isSidebarCollapsed ? "Mostrar barra lateral" : "Ocultar barra lateral"}
                aria-label={isSidebarCollapsed ? "Mostrar barra lateral" : "Ocultar barra lateral"}
                aria-expanded={!isSidebarCollapsed}
              >
                <Menu size={18} aria-hidden />
              </button>
              <button
                type="button"
                className="icon-button"
                onClick={() => setIsDarkTheme((current) => !current)}
                title={isDarkTheme ? "Usar tema claro" : "Usar tema oscuro"}
                aria-label={isDarkTheme ? "Usar tema claro" : "Usar tema oscuro"}
              >
                {isDarkTheme ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
              </button>
            </div>
            <div>
              <h2>{isDashboard ? "Dashboard" : activeQuery?.name ?? "Consultas"}</h2>
              <p>
                {isDashboard
                  ? "Graficas generadas desde los endpoints de cada consulta."
                  : activeQuery
                    ? activeQuery.description
                    : "No hay consultas registradas"}
              </p>
            </div>
          </div>
          {isDashboard ? (
            <div className="actions">
              <button type="button" onClick={() => void loadDashboardData()} disabled={loadingDashboard || queries.length === 0}>
                <BarChart3 size={18} aria-hidden />
                {loadingDashboard ? "Cargando" : "Cargar dashboard"}
              </button>
            </div>
          ) : (
          <div className="actions">
            <button
              type="button"
              className="download-button"
              onClick={() => void handleDownload("csv")}
              disabled={!canDownload || isRunningActiveQuery || exportingFormat !== null}
              title="Descargar CSV con la consulta completa"
            >
              <Download size={17} aria-hidden />
              {exportingFormat === "csv" ? "Descargando" : "CSV"}
            </button>
            <button
              type="button"
              className="download-button"
              onClick={() => void handleDownload("excel")}
              disabled={!canDownload || isRunningActiveQuery || exportingFormat !== null}
              title="Descargar Excel con la consulta completa"
            >
              <FileSpreadsheet size={17} aria-hidden />
              {exportingFormat === "excel" ? "Descargando" : "Excel"}
            </button>
            <button type="button" onClick={() => activeQuery && handleRunSingle(activeQuery.id)} disabled={!activeQuery || isRunningActiveQuery}>
              <Play size={18} aria-hidden />
              {isRunningActiveQuery ? "Ejecutando" : "Ejecutar"}
            </button>
          </div>
          )}
        </header>

        {error ? <div className="error-panel">{error}</div> : null}
        {isRunningActiveQuery ? <div className="status-panel">Ejecutando consulta, espera la respuesta de SQL Server...</div> : null}
        {exportingFormat ? <div className="status-panel">Preparando descarga completa, esto puede tardar si hay muchas filas...</div> : null}
        {loadingUnifiedDetail ? <div className="status-panel">Consultando detalle para los articulos filtrados...</div> : null}
        {unifiedDetailMessage ? <div className="status-panel">{unifiedDetailMessage}</div> : null}
        {loadingDashboard ? <div className="status-panel">Consultando endpoints para alimentar las graficas...</div> : null}
        {!isRunningActiveQuery && isResultLoading ? (
          resultRows.length > 0 ? (
            <div className="status-panel">Primera página lista; cargando el resto en segundo plano...</div>
          ) : (
            <div className="status-panel">Cargando esta pagina en segundo plano...</div>
          )
        ) : null}
        {!isRunningActiveQuery && hasExecuted && result && resultRows.length === 0 && !isResultLoading ? (
          <div className="status-panel success">Consulta ejecutada correctamente, sin filas para mostrar.</div>
        ) : null}

        {isDashboard ? (
          <section className="dashboard-view">
            {!dashboardSummary ? (
              <div className="empty-state">Pulsa Cargar dashboard para consultar metricas agregadas.</div>
            ) : (
              <>
                <div className="dashboard-metrics">
                  <div>
                    <span>Filas cargadas</span>
                    <strong>{dashboardSummary.metrics.totalRows.toLocaleString("es-VE")}</strong>
                  </div>
                  <div>
                    <span>Endpoints</span>
                    <strong>{dashboardSummary.metrics.endpoints}</strong>
                  </div>
                  <div>
                    <span>Unidades vendidas</span>
                    <strong>{dashboardSummary.metrics.soldUnits.toLocaleString("es-VE")}</strong>
                  </div>
                  <div>
                    <span>Ajustes + / -</span>
                    <strong>
                      {dashboardSummary.metrics.positiveAdjustments.toLocaleString("es-VE")} / {dashboardSummary.metrics.negativeAdjustments.toLocaleString("es-VE")}
                    </strong>
                  </div>
                </div>

                <div className="dashboard-grid">
                  <section className="dashboard-card">
                    <div className="dashboard-card-title">
                      <BarChart3 size={18} aria-hidden />
                      <h3>Filas por endpoint</h3>
                    </div>
                    <ChartBars items={dashboardSummary.charts.rowsByEndpoint} />
                  </section>

                  <section className="dashboard-card">
                    <div className="dashboard-card-title">
                      <BarChart3 size={18} aria-hidden />
                      <h3>Categorias</h3>
                    </div>
                    <ChartBars items={dashboardSummary.charts.categories} />
                  </section>

                  <section className="dashboard-card">
                    <div className="dashboard-card-title">
                      <BarChart3 size={18} aria-hidden />
                      <h3>Marcas</h3>
                    </div>
                    <ChartBars items={dashboardSummary.charts.brands} />
                  </section>
                </div>
              </>
            )}
          </section>
        ) : (
        <section className="query-view">
          <div className="query-detail">
            <h3>Vista de consulta</h3>
            <dl>
              <div>
                <dt>Identificador</dt>
                <dd>{activeQuery?.id ?? "-"}</dd>
              </div>
              <div>
                <dt>Conexion</dt>
                <dd>{activeQuery ? "SQL Server" : "-"}</dd>
              </div>
              <div>
                <dt>Parametros</dt>
                <dd>
                  {activeQuery?.parameters.length
                    ? activeQuery.parameters.map((parameter) => parameter.label).join(", ")
                    : "Sin parametros"}
                </dd>
              </div>
            </dl>

            {activeQuery?.parameters.length ? (
              <div className="parameter-grid">
                {activeQuery.parameters.map((parameter) => (
                  <label className="parameter-field" key={parameter.name}>
                    <span>{parameter.label}</span>
                    <input
                      type={parameter.type === "date" ? "date" : parameter.type === "number" ? "number" : "text"}
                      value={parameterValues[parameter.name] ?? ""}
                      required={parameter.required}
                      onChange={(event) => updateParameter(parameter.name, event.target.value)}
                    />
                  </label>
                ))}
                {activeQuery?.id === "ventas" ? (
                  <label className="parameter-field">
                    <span>Codigo de barra</span>
                    <input
                      type="search"
                      value={parameterValues.codigoBarra ?? ""}
                      onChange={(event) => updateParameter("codigoBarra", event.target.value)}
                      placeholder="Opcional"
                    />
                  </label>
                ) : null}
              </div>
            ) : null}
          </div>
        </section>
        )}

        {!isDashboard ? <div className="result-surface">
          {isRunningActiveQuery ? <div className="empty-state">Procesando...</div> : null}

          {!isRunningActiveQuery && !hasExecuted && resultRows.length === 0 ? (
            <div className="empty-state">Ejecuta la consulta activa para ver resultados.</div>
          ) : null}

          {!isRunningActiveQuery && hasExecuted && !error && resultRows.length === 0 ? (
            <div className="empty-state">
              {isResultLoading ? "Cargando esta pagina en segundo plano..." : "No hay resultados para los parametros seleccionados."}
            </div>
          ) : null}

          {!isRunningActiveQuery && resultRows.length > 0 ? (
            <>
              <div className="table-filters" aria-label="Filtros locales de resultados">
                {TABLE_FILTERS.map((filter) => (
                  <label className="table-filter-field" key={filter.key}>
                    <span>{filter.label}</span>
                    <input
                      type="search"
                      value={tableFilters[filter.key]}
                      onChange={(event) => updateTableFilter(filter.key, event.target.value)}
                    />
                  </label>
                ))}
                {isUnifiedQuery ? (
                  <div className="table-filter-options">
                    <span>Cargar detalle</span>
                    <div>
                      <button
                        type="button"
                        onClick={() => void loadUnifiedDetailForFilteredRows("ventas")}
                        disabled={loadingUnifiedDetail !== null || pageRows.length === 0}
                      >
                        {loadingUnifiedDetail === "ventas" ? "Cargando ventas" : "Ventas"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void loadUnifiedDetailForFilteredRows("kardex")}
                        disabled={loadingUnifiedDetail !== null || pageRows.length === 0}
                      >
                        {loadingUnifiedDetail === "kardex" ? "Cargando kardex" : "Kardex"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void loadUnifiedDetailForFilteredRows("transferencias_tiendas")}
                        disabled={loadingUnifiedDetail !== null || pageRows.length === 0}
                      >
                        {loadingUnifiedDetail === "transferencias_tiendas" ? "Cargando transferencias" : "Transferencias"}
                      </button>
                    </div>
                  </div>
                ) : null}
                {isUnifiedQuery ? (
                  <div className="table-filter-options">
                    <span>Tipo de ajuste</span>
                    <div>
                      <label>
                        <input
                          type="checkbox"
                          checked={unifiedAdjustmentFilters.positive}
                          onChange={(event) => updateUnifiedAdjustmentFilter("positive", event.target.checked)}
                        />
                        Entrada positiva
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={unifiedAdjustmentFilters.negative}
                          onChange={(event) => updateUnifiedAdjustmentFilter("negative", event.target.checked)}
                        />
                        Salida negativa
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={unifiedAdjustmentFilters.both}
                          onChange={(event) => updateUnifiedAdjustmentFilter("both", event.target.checked)}
                        />
                        Ambos
                      </label>
                    </div>
                  </div>
                ) : null}
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {visibleColumns.map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row, index) => (
                      <tr key={(page - 1) * PAGE_SIZE + index}>
                        {visibleColumns.map((column) => (
                          <td key={column}>{String(row[column] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <footer className="pagination">
                <span>
                  {resultLabel}
                  {visibleRows.length !== resultRows.length ? ` | ${visibleRows.length} filtradas en esta pagina` : ""}
                </span>
                <div className="pagination-actions">
                  <button
                    type="button"
                    onClick={() => activeQuery && handleRunSingle(activeQuery.id, Math.max(1, page - 1))}
                    disabled={page === 1 || isRunningActiveQuery}
                  >
                    <ChevronLeft size={18} aria-hidden />
                    Anterior
                  </button>
                  <strong>
                    Pagina {page} de {totalPages}
                  </strong>
                  <button
                    type="button"
                    onClick={() => activeQuery && handleRunSingle(activeQuery.id, Math.min(totalPages, page + 1))}
                    disabled={(isResultComplete && page === totalPages) || isRunningActiveQuery}
                  >
                    Siguiente
                    <ChevronRight size={18} aria-hidden />
                  </button>
                </div>
              </footer>
            </>
          ) : null}
        </div> : null}
      </section>
    </main>
  );
}

function ChartBars({ items }: { items: ChartItem[] }) {
  if (items.length === 0) {
    return <div className="dashboard-empty">Sin datos para graficar.</div>;
  }

  return (
    <div className="chart-bars">
      {items.map((item) => (
        <div className="chart-row" key={item.label}>
          <div className="chart-row-label" title={item.label}>
            {item.label}
          </div>
          <div className="chart-track">
            <div className="chart-fill" style={{ width: `${item.percent}%` }} />
          </div>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}
