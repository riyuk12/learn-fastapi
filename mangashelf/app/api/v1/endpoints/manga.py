from fastapi import APIRouter, Depends, Query, HTTPException
from app.schemas.manga import MangaResponse, MangaCreate, MangaStatus
import uuid
from datetime import datetime, timezone
from app.db.fake_db import MANGA_DB

router = APIRouter()


class PaginationParams:
    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        self.page = page
        self.limit = limit
        self.offset = (page - 1) * limit


@router.get("/", response_model=list[MangaResponse])
def list_manga(
    pagination: PaginationParams = Depends(),
    status: MangaStatus | None = None,
    genre: str | None = None,
):
    results = list(MANGA_DB.values())
    if status:
        results = [m for m in results if m["status"] == status]
    if genre:
        results = [m for m in results if genre in m["genres"]]
    return results[pagination.offset : pagination.offset + pagination.limit]


@router.post("/", response_model=MangaResponse, status_code=201)
def create_manga(manga: MangaCreate):
    new_id = str(uuid.uuid4())
    MANGA_DB[new_id] = {"id": new_id, **manga.model_dump(), "created_at": datetime.now(timezone.utc)}
    return MANGA_DB[new_id]


@router.get("/{manga_id}", response_model=MangaResponse)
def get_manga(manga_id: uuid.UUID):
    manga = MANGA_DB.get(str(manga_id))
    if manga is None:
        raise HTTPException(status_code=404, detail="Manga not found")
    return manga
