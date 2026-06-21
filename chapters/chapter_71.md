# Chapter 71 — API Versioning & Documentation

## Concepts You'll Learn
- API versioning strategies (URL path vs header)
- OpenAPI schema customization
- Deprecation workflow (Sunset header)
- API changelog and migration guides

## Concept Deep Dive

### API Versioning Strategies

APIs evolve. You add fields, change response shapes, remove deprecated features. The question is: how do you make changes without breaking existing clients?

**URL path versioning** puts the version in the URL: `/api/v1/manga`, `/api/v2/manga`. This is the most common approach because it is explicit, visible, and easy to route. Clients know which version they are calling. The downside is that every version requires its own set of routes.

**Header versioning** uses a custom header (like `Accept: application/vnd.mangashelf.v2+json` or `X-API-Version: 2`). The URL stays the same, and the server inspects the header to decide which behavior to use. This is "purer" REST (the URL identifies the resource, the header identifies the representation) but harder to test (you cannot just change the URL in a browser) and easier to forget.

**Query parameter versioning** uses `?version=2`. Rarely used because it pollutes the URL with non-resource-related parameters.

For MangaShelf, **URL path versioning** is the right choice. You already have `/api/v1/`. Now you will create `/api/v2/` with breaking changes. Both versions run simultaneously in the same application.

### Breaking vs Non-Breaking Changes

Not all API changes require a new version. Understanding the distinction prevents unnecessary version proliferation:

**Non-breaking (backward compatible):**
- Adding a new field to a response (existing clients ignore it)
- Adding a new optional query parameter
- Adding a new endpoint
- Adding a new enum value to a response field (if clients handle unknown values)

**Breaking (requires new version):**
- Removing a field from a response
- Renaming a field
- Changing a field's type
- Removing an endpoint
- Making a previously optional field required
- Changing pagination from offset-based to cursor-only

The discipline is: accumulate non-breaking changes in the current version, and batch breaking changes into a new version with a clear migration guide.

### OpenAPI Schema Customization

FastAPI auto-generates an OpenAPI (Swagger) schema, but the default schema is minimal. Good API documentation includes descriptions, examples, proper tags, and request/response examples.

```python
@router.get(
    "/manga/{slug}",
    response_model=MangaResponse,
    summary="Get manga by slug",
    description="Retrieve detailed information about a manga series, including chapter count and average rating.",
    responses={
        200: {
            "description": "Manga found",
            "content": {
                "application/json": {
                    "example": {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "title": "One Piece",
                        "slug": "one-piece",
                        "status": "ongoing",
                        "chapter_count": 1089
                    }
                }
            }
        },
        404: {"description": "Manga not found"},
    },
)
async def get_manga(slug: str):
    ...
```

You can also customize the entire OpenAPI schema at the application level:

```python
app = FastAPI(
    title="MangaShelf API",
    description="API for the MangaShelf manga library and reader platform.",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_tags=[
        {"name": "manga", "description": "Manga browsing and management"},
        {"name": "auth", "description": "Authentication and authorization"},
        {"name": "reader", "description": "Chapter reading and progress"},
    ],
)
```

Tags group endpoints in the Swagger UI. Descriptions on each endpoint help consumers understand what the endpoint does, its side effects, and its error cases.

### Deprecation Workflow

When you release v2, you cannot immediately remove v1. Existing clients depend on it. The proper workflow is:

1. **Release v2** alongside v1. Both work.
2. **Mark v1 as deprecated**. Add `Deprecation` and `Sunset` headers to all v1 responses.
3. **Migration period**. Give clients time (weeks or months) to migrate. Provide a migration guide.
4. **Sunset v1**. After the announced date, v1 returns 410 Gone.

HTTP headers for deprecation:
```
Deprecation: true
Sunset: Sat, 01 Jun 2025 00:00:00 GMT
Link: <https://api.mangashelf.com/docs/migration-v1-to-v2>; rel="deprecation"
```

The `Deprecation` header signals that the endpoint is deprecated. The `Sunset` header gives the exact date when it will be removed. The `Link` header points to migration documentation.

In FastAPI, add these headers via middleware on the v1 router:

```python
@app.middleware("http")
async def add_deprecation_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = "Sat, 01 Jun 2025 00:00:00 GMT"
    return response
```

## Your Task

### Step 1: Design a Breaking Change for v2

Choose a real breaking change to implement in v2. Some options:
- **Pagination**: v2 uses cursor-based pagination exclusively — remove offset/limit support. The response shape changes: `{"items": [...], "cursor": "...", "has_more": true}` instead of `{"items": [...], "total": 100, "page": 1}`.
- **Review schema**: v2 nests the user object inside the review and changes the rating scale from 1-10 to 1-5 (or vice versa).
- **Manga response**: v2 renames fields (e.g., `cover_url` becomes `cover_image.url` with additional fields like `cover_image.blurhash`).

Pick one (or more) that feels meaningful. The point is to practice the versioning workflow.

### Step 2: Create the v2 Router Structure

Create `app/api/v2/` directory with:
- `__init__.py` with the v2 router
- `endpoints/` directory
- Copy the endpoints that have breaking changes from v1 to v2 and modify them

For endpoints that have NOT changed, you have two options:
- **Re-export**: The v2 router includes the unchanged v1 endpoint (code reuse)
- **Duplicate**: Copy the endpoint to v2 (allows independent evolution)

The re-export approach is more DRY. Import the unchanged v1 endpoint functions into the v2 router.

### Step 3: Implement the Breaking Changes

In the v2 endpoints:
- Change the response schemas (create new Pydantic models in v2 schemas)
- Update the endpoint implementations to use the new schemas
- Ensure the behavior matches the new contract

### Step 4: Mount Both Versions

In your `app/main.py`, mount both routers:

```python
app.include_router(v1_router, prefix="/api/v1")
app.include_router(v2_router, prefix="/api/v2")
```

Both versions must work simultaneously. A request to `/api/v1/manga` returns the v1 response format, and `/api/v2/manga` returns the v2 format.

### Step 5: Add Deprecation Headers to v1

Create middleware or a dependency that adds deprecation headers to all v1 responses:
- `Deprecation: true`
- `Sunset: <date 6 months from now>`
- Optionally include a `Link` header pointing to migration docs

### Step 6: Customize OpenAPI Documentation

Create `app/core/openapi.py` to customize the OpenAPI schema:
- Add a meaningful title and description for the API
- Organize endpoints with tags (manga, auth, reader, library, social, admin)
- Add request/response examples to at least 5 key endpoints
- Add proper error response documentation (400, 401, 403, 404, 422)
- Generate separate OpenAPI schemas for v1 and v2 if possible, or a combined one with clear version tagging

### Step 7: Create the API Changelog

Create `docs/api-changelog.md` documenting:
- What changed between v1 and v2
- Why each breaking change was made
- A migration guide: for each breaking change, show the v1 format, the v2 format, and what clients need to change
- The deprecation timeline for v1

## Expected Outcome
- `/api/v1/` and `/api/v2/` both work simultaneously
- v2 has at least one breaking change with new response schemas
- v1 responses include Deprecation and Sunset headers
- Swagger docs at `/docs` (or `/api/docs`) show well-organized, documented endpoints with examples
- API changelog documents the migration path from v1 to v2
- Unchanged endpoints are shared between v1 and v2 (code reuse)

## Hints
- For sharing endpoints between versions, you can import the endpoint function and add it to both routers. Just make sure the response model is appropriate for each version.
- FastAPI's `include_router` with `prefix` handles the URL versioning. You do not need separate FastAPI app instances.
- For OpenAPI examples, use `model_config` with `json_schema_extra` on your Pydantic models to provide example values automatically.
- The Sunset header date should be an HTTP date format: `Sat, 01 Jun 2025 00:00:00 GMT`. Use Python's `email.utils.formatdate` or hardcode it.

## What I'll Look For In Review
- Both API versions work correctly and simultaneously
- The breaking change is genuine (different response shape/behavior between v1 and v2)
- Deprecation headers are present on v1 responses
- OpenAPI docs have meaningful descriptions, tags, and at least some request/response examples
- The changelog clearly explains what changed and how to migrate
