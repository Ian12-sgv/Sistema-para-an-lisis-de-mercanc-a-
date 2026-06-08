export interface QueryDefinition {
  id: string;
  name: string;
  description: string;
  requires_connection?: boolean;
  requiresConnection?: boolean;
  parameters: QueryParameter[];
}

export interface QueryParameter {
  name: string;
  label: string;
  type: "string" | "number" | "date" | "boolean";
  required: boolean;
}

export interface QueryResult {
  queryId: string;
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  totalRows: number;
  page: number;
  pageSize: number;
  totalPages: number;
  isLoading: boolean;
  isComplete: boolean;
}

export interface UnifiedQueryResult {
  results: QueryResult[];
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
}

export interface DashboardChartItem {
  label: string;
  value: number;
  percent: number;
}

export interface DashboardSummary {
  metrics: {
    totalRows: number;
    endpoints: number;
    soldUnits: number;
    positiveAdjustments: number;
    negativeAdjustments: number;
  };
  charts: {
    rowsByEndpoint: DashboardChartItem[];
    categories: DashboardChartItem[];
    brands: DashboardChartItem[];
  };
}
