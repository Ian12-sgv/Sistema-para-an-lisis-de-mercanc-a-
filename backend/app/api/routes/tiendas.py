import logging

from fastapi import APIRouter, HTTPException

from app.models.query import Tienda
from app.services.tiendas import list_tiendas

router = APIRouter(prefix="/tiendas", tags=["tiendas"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[Tienda])
def get_tiendas():
    """Tiendas y bodegas activas para el filtro "Existencia en"."""
    try:
        return list_tiendas()
    except Exception as error:
        logger.exception("No se pudieron listar las tiendas")
        raise HTTPException(status_code=500, detail="No se pudieron cargar las tiendas.") from error
