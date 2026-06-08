import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.models.query import CacheWarmupRequest, DashboardRequest, DashboardSummary, QueryDefinition, QueryResult, QueryRunRequest, UnifiedQueryRequest, UnifiedQueryResult
from app.services.query_catalog import get_query, list_queries
from app.services.query_runner import build_dashboard_summary, run_query, unify_queries

router = APIRouter(prefix="/queries", tags=["queries"])
logger = logging.getLogger(__name__)


def warmup_query_cache(query_id: str, parameters: dict):
    try:
        run_query(query_id, parameters, page=1, page_size=1000)
    except Exception:
        logger.exception("Cache warmup failed for query_id=%s", query_id)


@router.get("", response_model=list[QueryDefinition])
def get_queries():
    return list_queries()


@router.post("/run", response_model=QueryResult)
def run_single_query(request: QueryRunRequest, background_tasks: BackgroundTasks):
    try:
        return run_query(request.query_id, request.parameters, request.page, request.page_size, background_tasks)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Query execution failed for query_id=%s", request.query_id)
        raise HTTPException(status_code=500, detail="No se pudo ejecutar la consulta.") from error


@router.post("/unify", response_model=UnifiedQueryResult)
def run_unified_queries(request: UnifiedQueryRequest):
    try:
        return unify_queries(request.query_ids, request.parameters)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Query unification failed for query_ids=%s", request.query_ids)
        raise HTTPException(status_code=500, detail="No se pudieron unificar las consultas.") from error


@router.post("/dashboard", response_model=DashboardSummary)
def get_dashboard_summary(request: DashboardRequest):
    try:
        return build_dashboard_summary(request.parameters)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Dashboard summary failed")
        raise HTTPException(status_code=500, detail="No se pudo generar el dashboard.") from error


@router.post("/cache/warmup")
def warmup_cache(request: CacheWarmupRequest, background_tasks: BackgroundTasks):
    try:
        get_query(request.query_id)
        background_tasks.add_task(warmup_query_cache, request.query_id, request.parameters)
        return {"status": "queued", "queryId": request.query_id}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        logger.exception("Cache warmup queue failed for query_id=%s", request.query_id)
        raise HTTPException(status_code=500, detail="No se pudo preparar el cache.") from error
