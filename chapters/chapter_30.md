# Chapter 30 — Reading Progress Model & API

## Concepts You'll Learn
- The upsert pattern: INSERT ON CONFLICT UPDATE
- Per-user state tracking with composite keys
- Designing for debounced saves from a frontend
- The "recently read" query as a UX-driven data problem

## Concept Deep Dive

### The Upsert Pattern

When a user reads page 15 of a chapter, you need to save their progress. But should you INSERT a new row or UPDATE an existing one? If the user has never read this manga before, it is an INSERT. If they have, it is an UPDATE. Checking first ("does a record exist?") and then deciding creates a race condition: between the check and the write, another request could insert a row, causing a duplicate key error.

The **upsert** (update-or-insert) pattern solves this atomically. PostgreSQL provides `INSERT ... ON CONFLICT ... DO UPDATE`:

```sql
INSERT INTO reading_progress (user_id, manga_id, chapter_id, page_number, updated_at)
VALUES (1, 42, 7, 15, NOW())
ON CONFLICT (user_id, manga_id) DO UPDATE SET
    chapter_id = EXCLUDED.chapter_id,
    page_number = EXCLUDED.page_number,
    updated_at = EXCLUDED.updated_at;
```

`EXCLUDED` refers to the row that would have been inserted. The `ON CONFLICT` clause names the unique constraint that would be violated. This is one atomic SQL statement -- no race conditions, no check-then-act.

In SQLAlchemy, you use the PostgreSQL-specific `insert` with `on_conflict_do_update`:

```python
from sqlalchemy.dialects.postgresql import insert

stmt = insert(ReadingProgress).values(
    user_id=user_id, manga_id=manga_id,
    chapter_id=chapter_id, page_number=page_number,
)
stmt = stmt.on_conflict_do_update(
    index_elements=["user_id", "manga_id"],
    set_={"chapter_id": stmt.excluded.chapter_id,
          "page_number": stmt.excluded.page_number,
          "updated_at": func.now()},
)
await session.execute(stmt)
```

### Per-User State Tracking

Reading progress is **per-user, per-manga**. Every user has their own progress for each manga they read. This means the natural primary key (or unique constraint) is the composite `(user_id, manga_id)`. One user, one progress record per manga.

Why not per-chapter? Because for the "continue reading" use case, you want to know where the user left off in the entire manga, not maintain a separate record for every chapter they have touched. The single progress record tracks the "furthest point" -- the last chapter and page they viewed.

However, you might also want to track which chapters are completed. There are two approaches: (1) a boolean `is_completed` on the progress record meaning the entire manga is finished, or (2) a separate `ChapterProgress` model for per-chapter completion. For now, keep it simple with option (1). You can always add granularity later.

### Debounced Saves

A manga reader frontend does not send an API call on every single page turn. If a user flips through 10 pages in 3 seconds, that would be 10 PUT requests. Instead, the frontend **debounces**: it waits until the user stops flipping for 2-3 seconds, then sends one save request with the current position.

Your API must handle this gracefully. The `PUT /reading/progress` endpoint should be idempotent (calling it twice with the same data is fine) and fast (no heavy processing -- just an upsert). The endpoint receives the current position and blindly upserts. It does not need to validate "is this page number valid for this chapter?" strictly -- the frontend knows what page it is on.

Why PUT and not POST? Because this is an idempotent "set my progress to X" operation, not a "create a new progress entry." PUT semantics match perfectly: "put this state at this location."

### The "Recently Read" Query

"Continue reading" and "recently read" lists are among the most common UX features in reading apps. The query is: find all manga where this user has progress, order by `updated_at` descending, limit to 10-20 results.

```sql
SELECT rp.*, m.title, m.cover_image
FROM reading_progress rp
JOIN manga m ON rp.manga_id = m.id
WHERE rp.user_id = :user_id
  AND rp.is_completed = false
ORDER BY rp.updated_at DESC
LIMIT 10;
```

This query benefits enormously from an index on `(user_id, updated_at DESC)`. Without it, PostgreSQL scans every reading_progress row for the user and sorts them. With the index, it reads the top 10 directly. For a user with hundreds of manga in their history, this makes the difference between 1ms and 50ms.

## Your Task

### Step 1: Create the ReadingProgress Model

Create `app/models/reading_progress.py` with:

- `id`: integer primary key (or UUID, your choice)
- `user_id`: FK to User, not null
- `manga_id`: FK to Manga, not null
- `chapter_id`: FK to Chapter, not null
- `page_number`: integer, not null
- `is_completed`: boolean, default False
- `updated_at`: timestamp, auto-updated on every change

Add a **unique constraint** on `(user_id, manga_id)`. This is what the upsert's ON CONFLICT targets. Also add an index on `(user_id, updated_at DESC)` for the recently-read query.

Create the Alembic migration.

### Step 2: Create the Reading Progress Repository

Create `app/repositories/reading_progress.py` with:

- `upsert(user_id, manga_id, chapter_id, page_number) -> ReadingProgress`: implements the PostgreSQL upsert using `on_conflict_do_update`
- `get_by_manga(user_id, manga_id) -> ReadingProgress | None`: returns the user's progress for a specific manga
- `get_recently_read(user_id, limit=10) -> list[ReadingProgress]`: returns progress records ordered by `updated_at` DESC, optionally filtering out completed manga
- `mark_completed(user_id, manga_id) -> ReadingProgress`: sets `is_completed = True`

### Step 3: Create the Reading Progress Service

Create `app/services/reading_progress.py` with business logic:

- `save_progress(user_id, manga_id, chapter_id, page_number)`: validates that the manga and chapter exist, then calls the repository upsert
- `get_progress(user_id, manga_id)`: returns progress or None
- `get_reading_history(user_id, limit=20)`: returns recently read manga with progress info, joined with manga details (title, cover)
- `mark_as_completed(user_id, manga_id)`: marks the manga as completed

### Step 4: Create API Endpoints

Add these routes:

- `PUT /reading/progress`: accepts `{manga_id, chapter_id, page_number}` in the body. Uses the authenticated user's ID. Returns the upserted progress record. This endpoint should be fast -- it is called frequently by the reader frontend.
- `GET /reading/progress/{manga_id}`: returns the user's progress for a specific manga, or 404 if they have not started it.
- `GET /reading/history`: returns recently read manga, sorted by `updated_at` DESC. Accept `limit` query param (default 20, max 50). Include manga title and cover URL in the response.
- `POST /reading/progress/{manga_id}/complete`: marks the manga as completed.

### Step 5: Create Request/Response Schemas

In `app/schemas/reading.py`, define:

- `ReadingProgressUpdate`: the PUT request body (manga_id, chapter_id, page_number)
- `ReadingProgressResponse`: the response (includes all fields plus manga title)
- `ReadingHistoryResponse`: a list of progress entries with manga metadata

### Step 6: Test the Upsert

Write a test or manually verify: call `PUT /reading/progress` with manga_id=1, chapter_id=1, page_number=5. Call it again with chapter_id=2, page_number=1. The database should have exactly ONE row for this user+manga combination, updated to chapter 2 page 1.

## Expected Outcome
- `PUT /reading/progress` creates a record on first call, updates on subsequent calls (one row per user per manga)
- `GET /reading/progress/{manga_id}` returns the saved position
- `GET /reading/history` returns recently read manga sorted by last read time
- Marking a manga as completed flags it in the database
- The reading history excludes completed manga (or has a filter for it)
- No duplicate rows are created regardless of how many times the endpoint is called

## Hints
- The SQLAlchemy `on_conflict_do_update` requires using the PostgreSQL dialect: `from sqlalchemy.dialects.postgresql import insert`
- The `index_elements` parameter in `on_conflict_do_update` should match the columns in your unique constraint
- For the `updated_at` auto-update, use `onupdate=func.now()` in the column definition or set it explicitly in the upsert
- Remember to join with Manga when returning reading history so you can include title and cover URL

## What I'll Look For In Review
- The upsert is a single atomic SQL statement, not a SELECT-then-INSERT/UPDATE pattern
- The unique constraint on (user_id, manga_id) is defined in the model and migration
- An index exists on (user_id, updated_at) for the history query
- The PUT endpoint is idempotent and fast (no unnecessary queries)
- The reading history response includes enough manga metadata to render a "continue reading" UI
