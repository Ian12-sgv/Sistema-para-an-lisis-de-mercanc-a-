export type QueryId =
  | "consulta_base"
  | "ventas"
  | "kardex"
  | "transferencias_tiendas"
  | "consulta_unificada";

export interface QueryDefinition {
  id: QueryId | string;
  name: string;
  description: string;
  orderBy?: string;
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

export interface QueryRunRequest {
  queryId: QueryId | string;
  parameters: Record<string, string | number | boolean | null>;
  page: number;
  pageSize: number;
}

export interface QueryResult {
  queryId: QueryId | string;
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

export interface UnifiedQueryRequest {
  queryIds: Array<QueryId | string>;
  parameters: Record<string, string | number | boolean | null>;
}

export interface UnifiedQueryResult {
  results: QueryResult[];
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
}
