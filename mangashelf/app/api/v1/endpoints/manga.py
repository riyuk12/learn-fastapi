from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def list_manga():
    return [{"id": 1, "title": "One Piece","status": "ongoing", "description": "A manga about a boy who becomes a pirate"}, {"id": 2, "title": "Naruto", "status": "completed", "description": "A manga about a boy who becomes a ninja"}, {"id": 3, "title": "Dragon Ball", "status": "ongoing", "description": "A manga about a boy who becomes a dragon"}]