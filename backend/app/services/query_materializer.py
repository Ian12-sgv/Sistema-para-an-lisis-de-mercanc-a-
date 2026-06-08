from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Condition, Lock
from typing import Any

from app.db.sql_server import sql_server_connection


@dataclass
class MaterializedQueryJob:
    sql: str
    parameters: list[Any]
    page_size: int
    pages: list[list[dict[str, Any]]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    total_rows: int = 0
    completed: bool = False
    error: str | None = None
    condition: Condition = field(default_factory=Condition)


_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, MaterializedQueryJob] = {}
_jobs_lock = Lock()


def build_materialized_sql(sql: str, order_by: str | None = None) -> str:
    if not order_by:
        return sql

    return f"{sql}\nORDER BY {order_by}"


def get_or_start_job(cache_key: str, sql: str, parameters: list[Any], page_size: int) -> MaterializedQueryJob:
    with _jobs_lock:
        existing_job = _jobs.get(cache_key)
        if existing_job is not None:
            return existing_job

        job = MaterializedQueryJob(sql=sql, parameters=parameters, page_size=page_size)
        _jobs[cache_key] = job
        _executor.submit(_load_job_pages, job)

        return job


def _load_job_pages(job: MaterializedQueryJob) -> None:
    try:
        with sql_server_connection() as connection:
            cursor = connection.cursor()
            cursor.arraysize = max(job.page_size, 500)
            cursor.execute(job.sql, job.parameters)

            columns = [column[0] for column in cursor.description or []]
            with job.condition:
                job.columns = columns
                job.condition.notify_all()

            while True:
                batch = cursor.fetchmany(job.page_size)
                if not batch:
                    break

                page_rows = [dict(zip(columns, row)) for row in batch]

                with job.condition:
                    job.pages.append(page_rows)
                    job.total_rows += len(page_rows)
                    job.condition.notify_all()

        with job.condition:
            job.completed = True
            job.condition.notify_all()
    except Exception as error:
        with job.condition:
            job.error = str(error)
            job.completed = True
            job.condition.notify_all()


def get_materialized_page(job: MaterializedQueryJob, page: int, wait_seconds: float = 0.5) -> tuple[list[str], list[dict[str, Any]], int, bool, str | None]:
    page_index = max(0, page - 1)

    with job.condition:
        if len(job.pages) <= page_index and not job.completed:
            job.condition.wait(timeout=wait_seconds)

        rows = job.pages[page_index] if len(job.pages) > page_index else []
        return job.columns, rows, job.total_rows, job.completed, job.error
