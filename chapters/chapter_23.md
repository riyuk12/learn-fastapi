# Chapter 23 — Manga CRUD: Full Implementation

## Concepts You'll Learn
- Nested resource routes and RESTful URL design
- Cascade delete behavior in practice
- Partial updates with PATCH and the difference from PUT
- Completing the full REST resource lifecycle

## Concept Deep Dive

### Nested Resource Routes

When one resource belongs to another, the URL should reflect that relationship. Chapters belong to manga, so the URL for chapters is nested under the manga:

```
POST   /api/v1/manga/{manga_id}/chapters         # Create a chapter for this manga
GET    /api/v1/manga/{manga_id}/chapters         # List all chapters of this manga
GET    /api/v1/chapters/{chapter_id}              # Get a specific chapter
PATCH  /api/v1/chapters/{chapter_id}              # Update a chapter
DELETE /api/v1/chapters/{chapter_id}              # Delete a chapter
```

Notice the pattern: operations that require the parent context (create, list) use the nested URL. Operations on a specific chapter (get, update, delete) use the chapter's own ID — they don't need the manga ID because the chapter ID is globally unique.

This is a pragmatic REST convention. Some APIs nest everything (`/manga/{id}/chapters/{id}`), but this leads to unnecessarily long URLs and redundant validation (you'd have to verify that the chapter actually belongs to the specified manga). Using flat URLs for individual resource operations is simpler and equally RESTful.

### Cascade Delete in Practice

In Chapter 22, you set up `ondelete="CASCADE"` on foreign keys. Now it's time to put it to work. When a manga is deleted:

1. All its chapters are automatically deleted by PostgreSQL (FK cascade)
2. All pages belonging to those chapters are automatically deleted (FK cascade on pages)

This happens at the database level — your Python code doesn't need to manually delete chapters and pages. However, you need to be aware of it for two reasons:

First, cascade delete is powerful and irreversible. Deleting a manga with 200 chapters and 4,000 pages wipes all of that in one operation. This is why manga deletion should be admin-only (Chapter 19).

Second, if you have related resources that should NOT be cascaded (like user reviews of a manga), you'd use `ondelete="SET NULL"` or `ondelete="RESTRICT"` instead of CASCADE. The choice depends on your business rules.

When deleting via the ORM with `cascade="all, delete-orphan"` on the relationship, SQLAlchemy handles the cascade in Python (loading and deleting children). With `ondelete="CASCADE"` on the FK, the database handles it. Both achieve the same result, but database-level cascading is more efficient (no need to load children into memory just to delete them).

For deleting a single record efficiently without loading it first:

```python
from sqlalchemy import delete

stmt = delete(Manga).where(Manga.id == manga_id)
await db.execute(stmt)
```

But be aware: this bypasses ORM-level cascades. Only database-level cascades fire with this approach.

### Partial Updates with PATCH

HTTP has two verbs for updating resources:

- **PUT**: Replace the entire resource. The client sends the complete new representation. Any field not included is set to its default/null.
- **PATCH**: Partial update. The client sends only the fields they want to change. Everything else stays as-is.

PATCH is almost always what you want for an API. Imagine a manga with 10 fields — if you just want to change the description, you shouldn't need to resend the title, status, genres, and everything else.

The Pydantic pattern for PATCH uses optional fields:

```python
class MangaUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: MangaStatus | None = None
    genres: list[str] | None = None
```

Every field is optional. When processing the update, you only modify fields that were actually provided (not `None`):

```python
update_data = manga_update.model_dump(exclude_unset=True)
```

The `exclude_unset=True` is critical. Without it, `model_dump()` includes all fields with their `None` defaults, which would overwrite existing values with `None`. With `exclude_unset=True`, only fields the client explicitly included in the JSON body are returned. If the client sends `{"description": "new desc"}`, `update_data` is `{"description": "new desc"}` — title and status are untouched.

### Full REST Resource Lifecycle

A complete REST resource has these operations:

| Operation | HTTP Method | URL | Status Code |
|-----------|------------|-----|-------------|
| Create | POST | /manga | 201 |
| List | GET | /manga | 200 |
| Read one | GET | /manga/{id} | 200 |
| Update | PATCH | /manga/{id} | 200 |
| Delete | DELETE | /manga/{id} | 204 |

Note the status codes: 201 for creation (a new resource was created), 204 for deletion (success but no content to return). These conventions help API clients handle responses correctly.

For MangaShelf, you need this lifecycle for manga, chapters, and eventually pages. The pattern is the same for each resource — only the business logic inside varies.

## Your Task

### Step 1: Complete manga CRUD

Ensure your manga endpoints cover the full lifecycle:

- `POST /api/v1/manga` — Create (moderator+, already done)
- `GET /api/v1/manga` — List with filters, pagination, sorting (already done)
- `GET /api/v1/manga/{manga_id}` — Get one (already done)
- `PATCH /api/v1/manga/{manga_id}` — Partial update (moderator+)
- `DELETE /api/v1/manga/{manga_id}` — Delete (admin only)

For PATCH, create a `MangaUpdate` schema with all optional fields. The service should:
1. Fetch the existing manga
2. Apply only the provided fields
3. If title changed, regenerate the slug and check uniqueness
4. If genres changed, re-resolve them
5. Return the updated manga

For DELETE, return 204 with no body.

### Step 2: Create chapter schemas

In `app/schemas/chapter.py`, create:

- `ChapterCreate`: `chapter_number` (Decimal), `title` (optional string)
- `ChapterUpdate`: `chapter_number` (optional Decimal), `title` (optional string)
- `ChapterResponse`: all fields including `id`, `manga_id`, `page_count`, `created_at`

### Step 3: Create chapter repository and service

Create `app/repositories/chapter.py` with `ChapterRepository` extending `BaseRepository[Chapter]`. Add methods:
- `get_by_manga_id(db, manga_id, skip, limit)` — list chapters for a manga, ordered by chapter_number
- `get_by_manga_and_number(db, manga_id, chapter_number)` — for uniqueness checks

Create `app/services/chapter.py` with `ChapterService` that:
- Validates the manga exists when creating a chapter
- Checks for duplicate chapter numbers
- Handles the chapter lifecycle

### Step 4: Create chapter endpoints

Create `app/api/v1/endpoints/chapters.py` with:

- `POST /api/v1/manga/{manga_id}/chapters` — Create a chapter (moderator+). Validates manga exists, checks chapter_number uniqueness, creates the chapter.
- `GET /api/v1/manga/{manga_id}/chapters` — List chapters for a manga, ordered by `chapter_number`. Public endpoint.
- `GET /api/v1/chapters/{chapter_id}` — Get a single chapter with its pages. Public endpoint.
- `PATCH /api/v1/chapters/{chapter_id}` — Update a chapter (moderator+).
- `DELETE /api/v1/chapters/{chapter_id}` — Delete a chapter (admin). Cascade deletes pages.

### Step 5: Wire chapter routes

Include the chapter router in `app/api/v1/router.py`. You may need two include_router calls: one for `/manga/{manga_id}/chapters` (nested) and one for `/chapters` (flat). Or design your router to handle both patterns.

### Step 6: Test cascade delete

1. Create a manga
2. Create 3 chapters for it
3. Delete the manga
4. Verify all chapters are gone (query the database directly or try to GET them)

### Step 7: Test the full workflow

1. Create a manga with genres
2. Add 3 chapters (Chapter 1, Chapter 2, Chapter 2.5)
3. List chapters — should be ordered by chapter_number (1, 2, 2.5)
4. Update Chapter 2's title
5. Try to create another Chapter 2 → 409 Conflict
6. Delete Chapter 2.5 → 204
7. List chapters — only Chapter 1 and Chapter 2 remain
8. PATCH the manga's description → only description changes, other fields unchanged
9. Delete the manga → chapters cascade-deleted

## Expected Outcome
- Full CRUD for manga (create, read, list, update, delete)
- Full CRUD for chapters (create, read, list, update, delete)
- PATCH endpoints handle partial updates correctly (only update provided fields)
- DELETE endpoints return 204 No Content
- Cascade delete works: deleting manga removes its chapters
- Chapter listing is ordered by chapter_number
- Duplicate chapter numbers per manga return 409
- All write operations require appropriate roles (moderator/admin)

## Hints
- `model_dump(exclude_unset=True)` is the key to PATCH semantics. Without `exclude_unset`, you'll overwrite existing values with None.
- For the delete endpoint, use `status_code=204` on the decorator and return `None` (or use `Response(status_code=204)`).
- When updating manga genres, you'll need to clear the existing genre associations and set the new ones. `manga.genres = new_genre_list` handles this.
- For the nested chapter creation URL, `manga_id` comes from the path parameter, not from the request body. Don't include `manga_id` in `ChapterCreate`.
- If you need both `/manga/{id}/chapters` and `/chapters/{id}` routes, consider having two routers or using a single router with both paths registered.

## What I'll Look For In Review
- Full REST lifecycle for both manga and chapters with correct HTTP methods and status codes
- PATCH uses `exclude_unset=True` for true partial updates
- DELETE returns 204 with no response body
- Chapter listing is ordered by `chapter_number`
- Duplicate chapter numbers are caught and return 409
- Cascade delete is verified and working
