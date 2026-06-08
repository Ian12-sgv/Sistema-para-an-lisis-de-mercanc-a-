from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ParameterType = Literal["string", "number", "date", "boolean"]


class QueryParameter(BaseModel):
    name: str
    label: str
    type: ParameterType
    required: bool = True


class QueryDefinition(BaseModel):
    id: str
    name: str
    description: str
    sql_file: str
    order_by: str = Field(alias="orderBy")
    requires_connection: bool = True
    parameters: list[QueryParameter] = Field(default_factory=list)


class QueryRunRequest(BaseModel):
    query_id: str = Field(alias="queryId")
    parameters: dict[str, Any] = Field(default_factory=dict)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=200, alias="pageSize", ge=1, le=1000)


def _normalize_result_value(column: str, value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, str) and "fecha" in column.lower() and "T" in value:
        date_part = value.split("T", 1)[0]
        try:
            datetime.strptime(date_part, "%Y-%m-%d")
            return date_part
        except ValueError:
            return value

    return value


def _normalize_result_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {column: _normalize_result_value(column, value) for column, value in row.items()}
        for row in rows
    ]


class QueryResult(BaseModel):
    query_id: str = Field(alias="queryId")
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int = Field(alias="rowCount")
    total_rows: int = Field(default=0, alias="totalRows")
    page: int = 1
    page_size: int = Field(default=200, alias="pageSize")
    total_pages: int = Field(default=1, alias="totalPages")
    is_loading: bool = Field(default=False, alias="isLoading")
    is_complete: bool = Field(default=True, alias="isComplete")

    @model_validator(mode="after")
    def normalize_date_values(self):
        self.rows = _normalize_result_rows(self.rows)
        return self


class UnifiedQueryRequest(BaseModel):
    query_ids: list[str] = Field(alias="queryIds")
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query_ids")
    @classmethod
    def validate_query_ids(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("queryIds must include at least one query id.")

        return value


class UnifiedQueryResult(BaseModel):
    results: list[QueryResult]
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int = Field(alias="rowCount")

    @model_validator(mode="after")
    def normalize_date_values(self):
        self.rows = _normalize_result_rows(self.rows)
        return self


class DashboardRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


class DashboardChartItem(BaseModel):
    label: str
    value: float
    percent: float


class DashboardSummary(BaseModel):
    metrics: dict[str, Any]
    charts: dict[str, list[DashboardChartItem]]


class CacheWarmupRequest(BaseModel):
    query_id: str = Field(alias="queryId")
    parameters: dict[str, Any] = Field(default_factory=dict)
