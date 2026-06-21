from fastapi import APIRouter
from app.schemas.manga import MangaResponse, MangaCreate
import uuid
from datetime import datetime, timezone

router = APIRouter()

@router.get("/")
def list_manga():
    return [{"id": 1, "title": "One Piece","status": "ongoing", "description": "A manga about a boy who becomes a pirate"}, {"id": 2, "title": "Naruto", "status": "completed", "description": "A manga about a boy who becomes a ninja"}, {"id": 3, "title": "Dragon Ball", "status": "ongoing", "description": "A manga about a boy who becomes a dragon"}]

@router.post("/", response_model=MangaResponse, status_code=201)
def create_manga(manga: MangaCreate):
    return MangaResponse(**manga.model_dump(), id=uuid.uuid4(), created_at=datetime.now(timezone.utc))