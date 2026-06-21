# Chapter 31 — Bookmarks & Continue Reading

## Concepts You'll Learn
- User-owned resources: ensuring users can only access their own data
- Uniqueness constraints scoped to a user
- "Continue reading" as a UX-driven query that shapes your API design
- Designing endpoints around user workflows, not just CRUD

## Concept Deep Dive

### User-Owned Resources

Bookmarks are a **user-owned resource**: they belong to a specific user, and no other user should see, modify, or delete them. This seems obvious, but it is a common source of security bugs. If your endpoint is `DELETE /bookmarks/{id}`, a malicious user could guess or enumerate bookmark IDs and delete other users' bookmarks.

The defense is straightforward: every query for bookmarks must filter by the authenticated user's ID. Not just "does this bookmark exist?" but "does this bookmark exist AND does it belong to the current user?"

```python
# WRONG: anyone can delete any bookmark by ID
async def delete_bookmark(bookmark_id: int):
    bookmark = await repo.get_by_id(bookmark_id)
    if not bookmark:
        raise HTTPException(404)
    await repo.delete(bookmark)

# RIGHT: scoped to the current user
async def delete_bookmark(bookmark_id: int, current_user: User = Depends(get_current_user)):
    bookmark = await repo.get_by_id_and_user(bookmark_id, current_user.id)
    if not bookmark:
        raise HTTPException(404)  # 404, not 403 -- don't leak that it exists
    await repo.delete(bookmark)
```

Returning 404 instead of 403 ("Forbidden") is intentional. If you return 403, the attacker knows the bookmark exists but belongs to someone else. 404 reveals nothing -- it could be nonexistent or not theirs. This is called **information hiding** and it is a security best practice for user-owned resources.

### Uniqueness Constraints Per User

A user should not be able to bookmark the same manga+chapter+page combination twice. But two different users absolutely should. This requires a uniqueness constraint scoped to the user:

```python
class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    manga_id = Column(Integer, ForeignKey("manga.id"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "manga_id", "chapter_id", "page_number",
                         name="uq_bookmark_user_manga_chapter_page"),
    )
```

When a user tries to bookmark a page they have already bookmarked, the database raises an `IntegrityError`. Catch this and return a meaningful error message ("You have already bookmarked this page") rather than a 500.

### The "Continue Reading" Query

"Continue reading" is the most important feature on a reading app's home screen. It answers: "what manga am I in the middle of?" The definition is precise: manga where the user has reading progress AND has NOT completed it, ordered by when they last read.

This is not just a database query -- it is a UX-driven API design decision. The frontend needs enough data to render a card for each in-progress manga: title, cover image, the chapter name, the page number, maybe a progress percentage. All of this must come in a single API call to avoid N+1 requests from the frontend.

```sql
SELECT
    m.id, m.title, m.cover_image,
    rp.chapter_id, c.title as chapter_title, c.chapter_number,
    rp.page_number,
    rp.updated_at as last_read_at
FROM reading_progress rp
JOIN manga m ON rp.manga_id = m.id
JOIN chapters c ON rp.chapter_id = c.id
WHERE rp.user_id = :user_id
  AND rp.is_completed = false
ORDER BY rp.updated_at DESC
LIMIT 10;
```

This query joins three tables. In SQLAlchemy, you can express this with eager loading (joinedload) or an explicit join. The key decision: return this as a dedicated "continue reading" response shape, not as a generic ReadingProgress list. Shape the response around the frontend's needs.

### Designing Endpoints Around User Workflows

REST purists would put bookmarks at `/bookmarks` and reading progress at `/reading/progress`. But users do not think in database tables. They think in workflows: "What am I currently reading?" "Let me save this page." "Show my bookmarks for this manga."

Good API design groups endpoints by user workflow:

- `/reading/continue` -- the continue reading list (combines progress + manga data)
- `/reading/progress/{manga_id}` -- save or get progress for a specific manga
- `/bookmarks` -- all bookmarks (cross-manga)
- `/manga/{id}/bookmarks` -- bookmarks for a specific manga (nested resource)

Having both `/bookmarks` and `/manga/{id}/bookmarks` is not redundant -- they serve different use cases. The first is "show me all my bookmarks" (library view). The second is "show me my bookmarks in this manga" (reader view).

## Your Task

### Step 1: Create the Bookmark Model

Create `app/models/bookmark.py` with:

- `id`: integer or UUID primary key
- `user_id`: FK to User, not null
- `manga_id`: FK to Manga, not null
- `chapter_id`: FK to Chapter, not null
- `page_number`: integer, not null
- `note`: optional text (max 500 characters) for user annotations
- `created_at`: timestamp

Add a unique constraint on `(user_id, manga_id, chapter_id, page_number)`. Add an index on `(user_id, created_at DESC)` for listing bookmarks in reverse chronological order.

Create the Alembic migration.

### Step 2: Create the Bookmark Repository

Create `app/repositories/bookmark.py` with:

- `create(user_id, manga_id, chapter_id, page_number, note) -> Bookmark`: creates a bookmark, handling IntegrityError for duplicates
- `get_by_id_and_user(bookmark_id, user_id) -> Bookmark | None`: fetches a bookmark scoped to the user
- `list_by_user(user_id, limit, offset) -> list[Bookmark]`: all bookmarks for a user, newest first
- `list_by_manga(user_id, manga_id) -> list[Bookmark]`: bookmarks for a specific manga
- `update_note(bookmark_id, user_id, note) -> Bookmark`: update the note on a bookmark
- `delete(bookmark_id, user_id) -> bool`: delete a bookmark, scoped to user

Every method that accesses a specific bookmark must include `user_id` in the query. No exceptions.

### Step 3: Create the Bookmark Service

Create `app/services/bookmark.py` with:

- Business logic for creating bookmarks (validate that manga, chapter exist)
- Duplicate handling: catch IntegrityError and raise a friendly "already bookmarked" error
- Listing bookmarks with manga metadata (join with manga for title and cover)

### Step 4: Create Bookmark Endpoints

- `POST /bookmarks`: create a bookmark. Body: `{manga_id, chapter_id, page_number, note?}`. Returns 201 with the bookmark.
- `GET /bookmarks`: list all bookmarks for the current user. Support pagination (limit/offset). Include manga title and chapter title in the response.
- `GET /manga/{manga_id}/bookmarks`: list bookmarks for a specific manga.
- `PATCH /bookmarks/{id}`: update the note on a bookmark.
- `DELETE /bookmarks/{id}`: delete a bookmark. Returns 204 No Content.

### Step 5: Create the Continue Reading Endpoint

Create `GET /reading/continue` that returns the top 10 in-progress manga:

1. Query reading_progress for the current user where `is_completed = false`
2. Join with Manga (for title, cover) and Chapter (for chapter title, chapter number)
3. Order by `updated_at` DESC
4. Return a list of objects shaped for the UI:
   ```json
   {
     "manga_id": 42,
     "manga_title": "One Piece",
     "cover_url": "https://...",
     "current_chapter": {"id": 7, "number": 7, "title": "The Old Man at the Helm"},
     "current_page": 15,
     "last_read_at": "2026-03-31T14:30:00Z"
   }
   ```

### Step 6: Create Request/Response Schemas

In `app/schemas/bookmark.py`:

- `BookmarkCreate`: manga_id, chapter_id, page_number, note (optional)
- `BookmarkUpdate`: note only
- `BookmarkResponse`: all fields plus manga_title, chapter_title
- `ContinueReadingItem`: the shape described above
- `ContinueReadingResponse`: a list of ContinueReadingItem

## Expected Outcome
- Users can bookmark specific pages with optional notes
- Bookmarking the same page twice returns a clear error (not a 500)
- `GET /bookmarks` lists all bookmarks with manga/chapter context
- `GET /manga/{id}/bookmarks` shows bookmarks scoped to one manga
- `DELETE /bookmarks/{id}` only works for the owner (returns 404 for others)
- `GET /reading/continue` returns in-progress manga with all needed UI data
- The continue reading list updates when the user reads more (most recent first)

## Hints
- Catch `sqlalchemy.exc.IntegrityError` in the repository and raise a domain-specific exception. The route handler converts this to a 409 Conflict.
- For the continue reading endpoint, use SQLAlchemy's `joinedload` or explicit `.join()` to avoid N+1 queries
- The `note` field is optional on create and can be added/changed later via PATCH
- Test the user-scoping by creating bookmarks with two different users and verifying neither can see the other's

## What I'll Look For In Review
- Every bookmark query is scoped to the authenticated user's ID (no IDOR vulnerabilities)
- Duplicate bookmarks are handled gracefully with a 409, not a 500
- The continue reading endpoint returns all data the UI needs in one call (no N+1 from the frontend)
- The response shapes are designed for frontend consumption, not just database mirrors
- Bookmark delete returns 404 (not 403) when the bookmark belongs to another user
