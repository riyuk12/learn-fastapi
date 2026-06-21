# Chapter 4 — Path Params, Query Params, and Filtering

## Concepts You'll Learn
- Path parameters with automatic type coercion
- Query parameters with defaults and `Optional` types
- Using `Enum` types in query parameters
- Building a shared parameter pattern with `Depends`

## Concept Deep Dive

### Path Parameters with Type Coercion

Path parameters let you embed variable data directly in the URL. When you write `/manga/{manga_id}`, FastAPI captures whatever appears at that position and passes it to your function. The magic is in the type hint:

```python
@router.get("/{manga_id}")
async def get_manga(manga_id: uuid.UUID):
    ...
```

FastAPI sees `manga_id: uuid.UUID` and automatically attempts to parse the path segment as a UUID. If someone requests `/manga/not-a-uuid`, they get a 422 error before your function even executes. If the path segment is a valid UUID, your function receives an actual `uuid.UUID` object, not a string. This is type coercion — the framework converts the raw string from the URL into the Python type you declared.

This works with `int`, `float`, `str`, `uuid.UUID`, and even `Enum` types. It's one of FastAPI's most ergonomic features: your function always receives properly typed data, and invalid requests are rejected automatically.

### Query Parameters with Defaults

Query parameters are the `?key=value` pairs after the URL path. In FastAPI, any function parameter that is NOT a path parameter and NOT a Pydantic model is automatically treated as a query parameter.

```python
@router.get("/")
async def list_manga(
    status: MangaStatus | None = None,
    genre: str | None = None,
    page: int = 1,
    limit: int = 20,
):
    ...
```

Here, `page` and `limit` have defaults, so they're optional in the URL. `status` and `genre` default to `None`, meaning "no filter." A request to `/manga?status=ongoing&page=2` would call this function with `status=MangaStatus.ONGOING`, `genre=None`, `page=2`, `limit=20`.

Notice that `MangaStatus | None = None` means the status query parameter, when provided, must be one of the valid enum values. If someone sends `?status=dropped`, they get a 422 error. FastAPI generates the Swagger UI with a dropdown for this parameter.

For `page` and `limit`, you'll typically want to constrain them. A `limit` of 10,000 would be a denial-of-service vector. Use `Query()` from FastAPI to add constraints:

```python
from fastapi import Query

async def list_manga(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    ...
```

`ge=1` means "greater than or equal to 1" and `le=100` means "less than or equal to 100." These constraints appear in the Swagger docs and are enforced automatically.

### Optional vs Required Parameters

The distinction between optional and required is expressed through defaults:

- **Required**: no default value. `title: str` means the client MUST provide it.
- **Optional with default**: `page: int = 1` means "use 1 if not provided."
- **Optional, no value**: `genre: str | None = None` means "might not be present at all."

This is plain Python type hinting — FastAPI just reads it and does the right thing. There's no framework-specific configuration needed.

### Depends for Shared Parameter Patterns

When multiple endpoints share the same parameters (like pagination), you can extract them into a dependency. This keeps your function signatures clean and ensures consistency.

```python
from fastapi import Depends, Query

class PaginationParams:
    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        self.page = page
        self.limit = limit
        self.offset = (page - 1) * limit

@router.get("/")
async def list_manga(pagination: PaginationParams = Depends()):
    # Use pagination.page, pagination.limit, pagination.offset
    ...
```

`Depends()` with no arguments on a class type tells FastAPI to instantiate the class, injecting the query parameters. This is dependency injection — the framework handles creating and wiring the object. If you later add a `sort_by` parameter to pagination, you change it in one place and every endpoint that uses `PaginationParams` gets it automatically.

## Your Task

### Step 1: Create an in-memory "database"

At the top of `app/api/v1/endpoints/manga.py` (or in a separate temporary module), create a list of 8-10 manga dictionaries. Each should have `id` (a UUID string or object), `title`, `description`, `status` (using your `MangaStatus` enum values), `genres` (a list of strings like `["action", "adventure"]`), and `created_at`. This list is your temporary database — you'll replace it with PostgreSQL later.

### Step 2: Add GET by ID

Add a `GET /{manga_id}` endpoint that:
- Accepts `manga_id` as a `UUID` path parameter
- Searches the in-memory list for a matching manga
- Returns the manga if found, or raises `HTTPException(status_code=404)` if not

### Step 3: Add query parameter filtering

Modify your `GET /` list endpoint to accept query parameters:
- `status`: optional `MangaStatus` filter
- `genre`: optional string filter (match if the genre is in the manga's genre list)
- `page`: integer, default 1, minimum 1
- `limit`: integer, default 20, minimum 1, maximum 100

Apply the filters to the in-memory list. For pagination, use slicing: if `page=2` and `limit=5`, return items 5-9 (index based on offset calculation).

### Step 4: Extract pagination into a dependency

Create a `PaginationParams` class (can live in `app/api/v1/endpoints/manga.py` for now, or in `app/schemas/common.py`) that encapsulates `page` and `limit` with their defaults and constraints. Use `Depends()` to inject it into the list endpoint.

### Step 5: Test all paths

Test these scenarios:
- `GET /api/v1/manga` — returns all manga (up to default limit)
- `GET /api/v1/manga?status=ongoing` — returns only ongoing manga
- `GET /api/v1/manga?genre=action` — returns manga containing the "action" genre
- `GET /api/v1/manga?status=ongoing&genre=action&page=1&limit=2` — combined filters with pagination
- `GET /api/v1/manga/{valid-uuid}` — returns one manga
- `GET /api/v1/manga/{nonexistent-uuid}` — returns 404
- `GET /api/v1/manga/not-a-uuid` — returns 422

## Expected Outcome
- Query parameter filtering works: status, genre, and combinations thereof
- Pagination correctly slices the results (page 1 with limit 2 returns first 2 items)
- Path parameter type coercion works: invalid UUIDs return 422
- Nonexistent manga IDs return 404
- Swagger UI shows all query parameters with their types, defaults, and constraints

## Hints
- For filtering, start with the full list and progressively narrow it: `if status: results = [m for m in results if m["status"] == status]`.
- Remember that `page=1, limit=20` means offset 0. The formula is `offset = (page - 1) * limit`.
- When comparing a string enum query param to your stored data, you may need `.value` depending on how you stored the status in your fake data.
- Use `from uuid import UUID` for the type hint. FastAPI handles the string-to-UUID conversion.

## What I'll Look For In Review
- The in-memory data is well-structured with consistent field names
- Path parameter `manga_id` is typed as `UUID`, not `str`
- Query parameters have sensible defaults and constraints (especially `limit`)
- Filtering logic is correct and handles combinations of filters
- A `PaginationParams` dependency (or similar) is used to DRY up pagination logic
