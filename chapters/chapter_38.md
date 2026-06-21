# Chapter 38 — Personal Library

## Concepts You'll Learn
- Library as a first-class entity separate from reading progress
- Status-based tracking inspired by MyAnimeList/AniList
- User-specific CRUD with filtering and sorting
- The relationship between library state and reading progress

## Concept Deep Dive

### Library as a First-Class Entity

In Chapter 30, you built reading progress -- the system knows the user's current position in a manga. But reading progress is not the same as a library. A library is an intentional collection: "I plan to read this," "I am reading this," "I finished this," "I dropped this." A user might add a manga to their library (plan_to_read) before they ever open a single page.

Think of it like the difference between your browser history and your bookshelf. Browser history is automatic -- it records what you visited. Your bookshelf is curated -- you choose what goes on it. Reading progress is browser history. The library is the bookshelf.

This is exactly how MyAnimeList (MAL), AniList, and similar platforms work. The library entry has a **status** that the user manages explicitly, plus metadata like a personal rating and timestamps.

### Status-Based Tracking

The standard statuses for a manga library entry are:

- **plan_to_read**: The user wants to read this eventually (wishlist)
- **reading**: The user is actively reading this
- **completed**: The user has finished this
- **on_hold**: The user paused reading, intends to continue
- **dropped**: The user stopped reading and does not intend to continue

These statuses map to different sections in the UI: a "Currently Reading" shelf, a "Completed" shelf, a "Plan to Read" queue. They also enable interesting analytics: "How many manga have you completed this year?" "What is your drop rate?"

```python
import enum

class LibraryStatus(str, enum.Enum):
    PLAN_TO_READ = "plan_to_read"
    READING = "reading"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"
```

Using a string enum (inheriting from both `str` and `enum.Enum`) makes it serializable as a JSON string automatically. PostgreSQL stores it as a varchar. You get type safety in Python and clean API contracts.

### User-Specific CRUD

The library is entirely user-scoped. Every query must filter by `user_id`. The uniqueness constraint is on `(user_id, manga_id)` -- a user can have one library entry per manga.

The CRUD operations:
- **Add to library**: Creates an entry with a status. If the manga is already in the library, return an error (or update the status, depending on your UX preference).
- **Update status**: Change from "reading" to "on_hold" or "completed."
- **Rate**: Set a personal rating (1-10). This is separate from reviews in Chapter 47 -- you can rate without writing a review.
- **Remove**: Delete from library. The reading progress should remain (they might re-add it later).

An important UX question: should adding a manga to the library automatically set reading progress? And should starting to read automatically add to library? In many apps, starting to read adds to library with status "reading" automatically. Completing the last chapter sets status to "completed." You can implement this sync in the service layer.

### Library and Reading Progress Relationship

The library entry and reading progress are related but separate:

```
LibraryEntry: user_id, manga_id, status, rating, started_at, completed_at
ReadingProgress: user_id, manga_id, chapter_id, page_number, updated_at
```

They both key on `(user_id, manga_id)` but serve different purposes. The library entry is user-managed metadata. Reading progress is system-tracked position.

When a user marks a manga as "completed," you can auto-set reading progress to the last chapter's last page. When reading progress is created for a manga not in the library, you can auto-add it with status "reading."

But be careful: auto-syncing in both directions can create infinite loops. Pick one direction as authoritative. Typically: library status drives high-level state, reading progress drives detailed position. The user sets the status; the system sets the progress.

## Your Task

### Step 1: Create the LibraryEntry Model

Create `app/models/library.py` with:

- `id`: integer or UUID primary key
- `user_id`: FK to User, not null
- `manga_id`: FK to Manga, not null
- `status`: enum (plan_to_read, reading, completed, on_hold, dropped), not null, default plan_to_read
- `rating`: integer, nullable, check constraint between 1 and 10
- `started_at`: date, nullable (set when status changes to "reading")
- `completed_at`: date, nullable (set when status changes to "completed")
- `created_at`: timestamp
- `updated_at`: timestamp

Add a unique constraint on `(user_id, manga_id)`. Add an index on `(user_id, status)` for filtering by status.

Create the Alembic migration.

### Step 2: Create the Library Repository

Create `app/repositories/library.py` with:

- `add(user_id, manga_id, status, rating=None) -> LibraryEntry`: creates an entry, handling duplicates
- `get_entry(user_id, manga_id) -> LibraryEntry | None`: get a specific entry
- `list_by_user(user_id, status=None, sort_by="updated_at", sort_dir="desc", limit=20, offset=0) -> list[LibraryEntry]`: list with optional status filter and sorting
- `update(user_id, manga_id, **fields) -> LibraryEntry`: update status, rating, etc.
- `remove(user_id, manga_id) -> bool`: delete from library
- `count_by_status(user_id) -> dict[str, int]`: count entries per status

Sorting should support: `date_added` (created_at), `rating`, `title` (requires join with Manga), `updated_at`.

### Step 3: Create the Library Service

Create `app/services/library.py` with business logic:

- `add_to_library(user_id, manga_id, status)`: validate manga exists, check for duplicates (return 409), set `started_at` if status is "reading"
- `update_entry(user_id, manga_id, status=None, rating=None)`: update fields. If status changes to "reading" and `started_at` is null, set it. If status changes to "completed," set `completed_at`.
- `remove_from_library(user_id, manga_id)`: remove entry. Do NOT delete reading progress.
- `get_library(user_id, status, sort, limit, offset)`: list library entries with manga details (title, cover, author)
- `get_library_stats(user_id)`: return counts per status

### Step 4: Create Library Endpoints

- `POST /library`: add manga to library. Body: `{manga_id, status, rating?}`. Returns 201.
- `GET /library`: list library entries. Query params: `status`, `sort` (date_added, rating, title), `sort_dir` (asc, desc), `limit`, `offset`. Include manga details in the response.
- `GET /library/{manga_id}`: get the entry for a specific manga (or 404 if not in library).
- `PATCH /library/{manga_id}`: update status and/or rating. Body: `{status?, rating?}`.
- `DELETE /library/{manga_id}`: remove from library. Returns 204.
- `GET /library/stats`: return counts per status.

### Step 5: Create Request/Response Schemas

In `app/schemas/library.py`:

- `LibraryAdd`: manga_id, status, rating (optional)
- `LibraryUpdate`: status (optional), rating (optional)
- `LibraryEntryResponse`: all fields plus manga title, cover_url, author
- `LibraryListResponse`: list of entries with pagination metadata
- `LibraryStatsResponse`: `{plan_to_read: 5, reading: 12, completed: 30, ...}`

### Step 6: Auto-Sync with Reading Progress

In the library service, add optional auto-sync:
- When a user starts reading (reading progress is created) and the manga is not in the library, auto-add it with status "reading"
- When a user changes library status to "completed," check if you should update reading progress's `is_completed` flag

Implement this carefully to avoid circular dependencies between services. Use one service as the coordinator (library service calls reading progress repository directly, or use an event/hook pattern).

## Expected Outcome
- Users can add manga to their library with a status
- `GET /library?status=reading` shows only currently reading manga
- Sorting by rating, title, or date added works correctly
- `GET /library/stats` shows counts: `{reading: 5, completed: 12, ...}`
- Changing status to "completed" auto-sets `completed_at`
- Removing from library does not delete reading progress
- Duplicate library entries are rejected with 409

## Hints
- Use `sa.CheckConstraint('rating >= 1 AND rating <= 10')` for the rating constraint in the model
- For sorting by title (which is on the Manga table), you need to join with Manga in the repository query
- The `started_at` and `completed_at` fields are dates, not datetimes -- you do not need second precision for "when did I start reading this manga"
- For library stats, use a single GROUP BY query rather than multiple COUNT queries

## What I'll Look For In Review
- The unique constraint on (user_id, manga_id) prevents duplicate entries
- Status transitions auto-set started_at and completed_at appropriately
- Library queries support filtering by status AND sorting by multiple fields
- The response includes manga metadata (not just IDs) so the frontend can render cards
- Removing from library preserves reading progress (separate concerns)
