import pytest
from fastapi import HTTPException

from app.api.routes.queries import get_snapshot_status
from app.models.query import SnapshotStatusRequest
from app.services.query_runner import common, get_query_snapshot_status
from app.services.query_runner.common import get_cache_parameters
from app.services.unified_snapshot import append_snapshot_rows, build_snapshot_id, finalize_snapshot, reset_snapshot

KARDEX_PARAMETERS = {"fechaDesde": "2026-02-03", "codigoBarra": "status-test"}


def kardex_snapshot_id() -> str:
    return build_snapshot_id("kardex", get_cache_parameters("kardex", KARDEX_PARAMETERS))


@pytest.fixture
def clean_kardex_snapshot():
    snapshot_id = kardex_snapshot_id()
    reset_snapshot(snapshot_id)
    yield snapshot_id
    reset_snapshot(snapshot_id)
    with common._snapshot_build_lock:
        common._building_snapshots.discard(snapshot_id)


def test_queries_without_snapshot_are_always_ready():
    status = get_query_snapshot_status("transferencias_tiendas", {"fechaDesde": "2026-02-03", "fechaHasta": "2026-02-04"})

    assert (status.ready, status.building) == (True, False)


def test_status_reports_building_while_background_job_runs(clean_kardex_snapshot):
    with common._snapshot_build_lock:
        common._building_snapshots.add(clean_kardex_snapshot)

    status = get_query_snapshot_status("kardex", KARDEX_PARAMETERS)

    assert (status.ready, status.building) == (False, True)


def test_status_reports_ready_once_snapshot_exists(clean_kardex_snapshot):
    next_index = append_snapshot_rows(clean_kardex_snapshot, 0, [{"CodigoBarra": "status-test"}])
    finalize_snapshot(clean_kardex_snapshot, KARDEX_PARAMETERS, ["CodigoBarra"], next_index)

    status = get_query_snapshot_status("kardex", KARDEX_PARAMETERS)

    assert (status.ready, status.building) == (True, False)


def test_status_reports_failure_when_not_building_and_not_ready(clean_kardex_snapshot):
    status = get_query_snapshot_status("kardex", KARDEX_PARAMETERS)

    assert (status.ready, status.building) == (False, False)


def test_status_route_returns_404_for_unknown_query():
    with pytest.raises(HTTPException) as error:
        get_snapshot_status(SnapshotStatusRequest(queryId="no_existe", parameters={}))

    assert error.value.status_code == 404


def test_status_route_serializes_with_camel_case_aliases(clean_kardex_snapshot):
    status = get_snapshot_status(SnapshotStatusRequest(queryId="kardex", parameters=KARDEX_PARAMETERS))

    assert status.model_dump(by_alias=True) == {"queryId": "kardex", "ready": False, "building": False}
