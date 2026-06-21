from enum import Enum
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


class MangaStatus(str, Enum):
    """Allowed publication states. Inheriting from str makes it serialize
    as a plain string in JSON, while Enum restricts it to these values."""
    ONGOING = "ongoing"
    COMPLETED = "completed"
    HIATUS = "hiatus"
    CANCELLED = "cancelled"


class MangaBase(BaseModel):
    """Fields shared by input and output — the things the client provides
    and that also appear in responses."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class MangaCreate(MangaBase):
    """INPUT model: exactly what a client sends to create a manga.
    Note there is no id or created_at here — the server generates those."""
    status: MangaStatus
    genres: list[str]

    @field_validator("genres")
    @classmethod
    def at_least_one_genre(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one genre is required")
        return v


class MangaResponse(MangaCreate):
    """OUTPUT model: everything in MangaCreate plus server-generated fields.
    These are required (no default) because the endpoint/DB always supplies them."""
    id: UUID
    created_at: datetime

    # Lets this model be built directly from ORM objects later (manga.title, etc.),
    # not just from dicts. Harmless now, essential once SQLAlchemy arrives.
    model_config = ConfigDict(from_attributes=True)
