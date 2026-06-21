from fastapi import APIRouter
from app.api.v1.endpoints import manga

router = APIRouter()
router.include_router(manga.router, prefix="/manga", tags=["manga"])