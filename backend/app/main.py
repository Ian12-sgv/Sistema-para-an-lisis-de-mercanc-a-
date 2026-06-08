from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.queries import router as queries_router
from app.core.config import settings

app = FastAPI(
    title="Unificador Consultas API",
    version="0.1.0",
    description="API para ejecutar y unificar consultas SQL Server.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(queries_router, prefix="/api")

