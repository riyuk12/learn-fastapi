# Chapter 3 — Request & Response Models with Pydantic

## Concepts You'll Learn
- Pydantic `BaseModel` for data validation and serialization
- Field validators and custom validation logic
- Using `response_model` to control what FastAPI returns
- Designing schemas for request bodies vs responses

## Concept Deep Dive

### Pydantic BaseModel

Pydantic is the backbone of FastAPI's data handling. When you define a class that inherits from `BaseModel`, you're creating a contract: "this is the shape of data I expect, and here are the rules it must follow." Pydantic validates incoming data, coerces types where sensible, and raises clear errors when the data doesn't match.

```python
from pydantic import BaseModel

class MangaCreate(BaseModel):
    title: str
    description: str | None = None
    status: str
```

When FastAPI sees a route parameter typed as `MangaCreate`, it automatically parses the request body JSON into this model. If the body is missing `title`, or if `title` is an integer, the client gets a detailed 422 Unprocessable Entity response — and you didn't write a single line of validation code.

This is fundamentally different from writing `request.json()` and manually checking each field. Pydantic gives you type safety, automatic documentation, and validation errors that tell the client exactly what went wrong and where. Your Swagger UI also uses these models to show the expected request and response shapes.

### Field Validators and Custom Validation

Basic type checking isn't always enough. You might want a title between 1 and 200 characters, or require at least one genre. Pydantic's `Field` and `field_validator` let you express these constraints.

```python
from pydantic import BaseModel, Field, field_validator

class MangaCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    genres: list[str]

    @field_validator("genres")
    @classmethod
    def at_least_one_genre(cls, v):
        if len(v) == 0:
            raise ValueError("At least one genre is required")
        return v
```

`Field(...)` with the ellipsis means the field is required (no default). The `min_length` and `max_length` parameters handle string length validation. For more complex logic, `@field_validator` lets you write arbitrary Python — just return the validated value or raise `ValueError`.

Pydantic v2 (which is what modern FastAPI uses) also supports `model_validator` for validations that span multiple fields. For example, you might want to ensure that if `status` is "completed", a `completed_at` date must also be provided. But for now, field-level validators will cover our needs.

### response_model

FastAPI's `response_model` parameter on route decorators controls what the client sees in the response. Even if your internal data has 20 fields, the response model can expose only 5. This is critical for security (never accidentally leak a password hash) and for API clarity.

```python
@router.post("/", response_model=MangaResponse, status_code=201)
async def create_manga(manga: MangaCreate):
    # ... create the manga ...
    return manga_data  # FastAPI will filter through MangaResponse
```

FastAPI takes whatever you return and filters/serializes it through the `response_model`. Fields not in the model get stripped. Fields in the model that are missing from your return value cause an error. This acts as a safety net — your internal representation can evolve independently from your API contract.

### Schema Design: Request vs Response

A common mistake is using the same model for both creating a resource and returning it. But creation and retrieval have fundamentally different needs:

- **Create**: the client provides `title`, `description`, `status`, `genres`. They do NOT provide `id` or `created_at` — the server generates those.
- **Response**: the client receives everything from Create plus `id` and `created_at`.

The typical pattern is to have a base model with shared fields, a Create model for input, and a Response model for output:

```python
class MangaBase(BaseModel):
    title: str
    description: str | None = None

class MangaCreate(MangaBase):
    status: str
    genres: list[str]

class MangaResponse(MangaBase):
    id: uuid.UUID
    status: str
    genres: list[str]
    created_at: datetime
```

This inheritance avoids duplication while keeping create and response separate. You'll see this pattern everywhere in production FastAPI applications.

For the enum field `status`, Python's `enum.Enum` (or `str, Enum`) works perfectly with Pydantic and FastAPI. It restricts the field to a fixed set of values and shows them in Swagger as a dropdown.

```python
from enum import Enum

class MangaStatus(str, Enum):
    ONGOING = "ongoing"
    COMPLETED = "completed"
    HIATUS = "hiatus"
    CANCELLED = "cancelled"
```

By inheriting from both `str` and `Enum`, the value serializes as a plain string in JSON but is validated to only accept one of the defined values.

## Your Task

### Step 1: Create the schemas file

Create `app/schemas/__init__.py` and `app/schemas/manga.py`.

### Step 2: Define the MangaStatus enum

In `app/schemas/manga.py`, create a `MangaStatus` enum with values: `ongoing`, `completed`, `hiatus`, and `cancelled`. Make it inherit from both `str` and `Enum` so it serializes cleanly.

### Step 3: Define MangaCreate

Create a `MangaCreate` Pydantic model with:
- `title`: required string, 1-200 characters
- `description`: optional string, defaults to `None`
- `status`: required, must be a `MangaStatus` enum value
- `genres`: required list of strings, must contain at least one item

Add a field validator ensuring `genres` has at least one entry. Optionally, strip and deduplicate genre values.

### Step 4: Define MangaResponse

Create a `MangaResponse` model that includes all fields from `MangaCreate` plus:
- `id`: a UUID
- `created_at`: a datetime

Use `model_config = ConfigDict(from_attributes=True)` so this model can later be built directly from SQLAlchemy ORM objects.

### Step 5: Add a POST endpoint

In `app/api/v1/endpoints/manga.py`, add a `POST /` endpoint that:
- Accepts a `MangaCreate` request body
- Returns a `MangaResponse` with a randomly generated UUID and the current datetime as `created_at`
- Uses `response_model=MangaResponse` and `status_code=201`

For now, you don't need to store anything — just echo back the data with a fake ID and timestamp. You can use `uuid.uuid4()` and `datetime.now(timezone.utc)`.

### Step 6: Test validation

Send POST requests with invalid data and observe the 422 responses:
- Missing title
- Title longer than 200 characters
- Empty genres list
- Invalid status value (e.g., "dropped")

## Expected Outcome
- `POST /api/v1/manga` with valid body returns 201 with a shaped `MangaResponse`
- `POST /api/v1/manga` with missing required fields returns 422 with Pydantic error details
- `POST /api/v1/manga` with empty genres list returns 422
- `POST /api/v1/manga` with invalid status returns 422 mentioning the valid enum values
- Swagger UI at `/docs` shows the request body schema with field descriptions and the enum dropdown for status

## Hints
- Use `from uuid import uuid4` and `from datetime import datetime, timezone` for generating fake IDs and timestamps.
- Remember that `Field(...)` means required. `Field(default=None)` means optional.
- When building the response dict from the request data, you can use `manga.model_dump()` to convert the Pydantic model to a dictionary, then add `id` and `created_at` keys.
- If your `MangaResponse` has `from_attributes=True` in its config, it can accept both dicts and ORM objects — useful when you add the database later.

## What I'll Look For In Review
- Schemas live in `app/schemas/manga.py`, not mixed into the endpoint file
- `MangaStatus` is a proper `str, Enum` with at least 4 values
- `MangaCreate` validates title length and requires at least one genre
- `MangaResponse` adds `id` and `created_at` and uses `response_model` on the endpoint
- The POST endpoint returns 201, not the default 200
