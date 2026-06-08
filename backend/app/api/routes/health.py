from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "environment": settings.app_env,
        "databaseConfigured": settings.has_database_credentials,
    }

