# Chapter 45 — Cursor-Based Pagination

## Concepts You'll Learn
- Why OFFSET pagination breaks at scale (the scan-and-discard problem)
- Keyset/cursor pagination: how it works and why it stays fast
- Encoding cursors as opaque tokens
- Trade-offs: cursor vs offset pagination and when to use each

## Concept Deep Dive

### Why OFFSET Breaks at Scale

OFFSET pagination looks simple: `SELECT * FROM manga ORDER BY id LIMIT 20 OFFSET 1000`. Give me 20 items, starting from the 1001st. But PostgreSQL does not skip to row 1001 -- it scans all 1001 rows, discards the first 1000, and returns the last 20. On page 1, it scans 20 rows. On page 50 (OFFSET 980), it scans 1000 rows. On page 500, it scans 10,000 rows.

The cost grows linearly with the page number. Page 1 takes 1ms. Page 1000 takes 50ms. Page 10000 takes 500ms. For a manga library with 100,000 entries, deep pagination becomes painfully slow.

```sql
-- Page 1: scans 20 rows
SELECT * FROM manga ORDER BY created_at DESC LIMIT 20 OFFSET 0;

-- Page 1000: scans 20,000 rows, returns 20
SELECT * FROM manga ORDER BY created_at DESC LIMIT 20 OFFSET 19980;
```

It gets worse with JOINs and complex WHERE clauses: PostgreSQL must evaluate the filter on all rows before it can determine which ones to skip. This is the fundamental problem with OFFSET.

### Keyset / Cursor Pagination

Cursor pagination (also called keyset pagination) avoids scanning by remembering **where you left off**. Instead of "give me page 50," you say "give me the next 20 items after this specific item."

```sql
-- First page: no cursor, just get the newest 20
SELECT * FROM manga ORDER BY created_at DESC, id DESC LIMIT 20;

-- Next page: "give me items after the last item I saw"
SELECT * FROM manga
WHERE (created_at, id) < ('2025-06-15 10:30:00', 42)
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

The `WHERE (created_at, id) < (...)` clause uses PostgreSQL's **row value comparison**. It jumps directly to the right position using the index on `(created_at DESC, id DESC)`. No scanning, no discarding. Page 1000 is as fast as page 1.

Why include `id` in the cursor? Because `created_at` is not unique. Multiple manga might have the same timestamp. The `id` breaks ties and ensures a deterministic, stable ordering. This is called a **tie-breaker**.

### Encoding Cursors

The cursor value (e.g., `created_at=2025-06-15T10:30:00, id=42`) should not be exposed as raw query parameters. Instead, encode it as an **opaque token**: a base64-encoded JSON string. This hides the implementation details and prevents users from crafting arbitrary cursors.

```python
import base64
import json

def encode_cursor(sort_value, id: int) -> str:
    data = {"v": str(sort_value), "id": id}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

def decode_cursor(cursor: str) -> dict:
    data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return data

# Usage:
cursor = encode_cursor("2025-06-15T10:30:00", 42)
# "eyJ2IjogIjIwMjUtMDYtMTVUMTA6MzA6MDAiLCAiaWQiOiA0Mn0="
```

The client never decodes or manipulates the cursor. It receives it from one response and passes it to the next request. It is an opaque page token.

### Trade-Offs: Cursor vs Offset

| Feature | Offset | Cursor |
|---------|--------|--------|
| Performance | Degrades with page number | Constant |
| Random page access | Yes (go to page 50) | No (sequential only) |
| Implementation | Simple | Moderate |
| Stable under inserts | No (items shift between pages) | Yes |
| UI pattern | Page numbers (1, 2, 3...) | "Load more" / infinite scroll |

**Use offset when:**
- The dataset is small (under 10,000 items)
- Users need random page access (admin dashboards, back-office tools)
- Simplicity matters more than performance

**Use cursor when:**
- The dataset is large or growing
- The UI uses infinite scroll or "load more"
- Consistency matters (no skipped/duplicated items when data changes)
- Performance at any depth must be constant

For MangaShelf, the public-facing manga list and search results should use cursor pagination (users scroll through lots of results). Admin dashboards can keep offset pagination for convenience.

## Your Task

### Step 1: Create Pagination Schemas

Create `app/schemas/pagination.py` with:

**CursorPaginationParams** (input):
- `cursor`: optional string (the encoded cursor from the previous response)
- `limit`: int (default 20, max 100)

**CursorPage** (output, generic):
- `items`: list of the resource type
- `next_cursor`: optional string (None if no more items)
- `has_more`: boolean
- `limit`: int (echo back the limit)

**OffsetPaginationParams** (input, keep for admin):
- `page`: int (default 1)
- `page_size`: int (default 20, max 100)

**OffsetPage** (output):
- `items`: list
- `total`: int
- `page`: int
- `page_size`: int
- `total_pages`: int

### Step 2: Implement Cursor Encoding/Decoding

Create utility functions in `app/utils/pagination.py`:

- `encode_cursor(sort_value: Any, id: int) -> str`: serializes to base64 JSON
- `decode_cursor(cursor: str) -> tuple[Any, int]`: deserializes, returns (sort_value, id)
- Handle decoding errors gracefully (invalid base64, missing fields) -- return a 400 error

### Step 3: Implement Cursor Pagination in the Repository

Add a cursor-paginated query method to your manga repository:

```python
async def list_cursor(
    self,
    cursor: tuple | None,  # (sort_value, id) or None for first page
    limit: int,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
) -> tuple[list[Manga], bool]:  # (items, has_more)
```

The method should:
1. Build the base query with ORDER BY (sort_column, id) in the specified direction
2. If a cursor is provided, add a WHERE clause: `(sort_column, id) < (cursor_value, cursor_id)` for DESC or `>` for ASC
3. Fetch `limit + 1` items (the +1 tells you if there are more pages)
4. Return the items (truncated to limit) and `has_more` (True if limit+1 items were found)

### Step 4: Apply Cursor Pagination to Manga List

Modify `GET /manga` to support cursor pagination:

```
GET /manga?limit=20                          # First page
GET /manga?cursor=eyJ2Ijoi...&limit=20       # Next page
```

The response:
```json
{
  "items": [...],
  "next_cursor": "eyJ2IjoiMjAyNS0wNi0xNVQxMDozMDowMCIsImlkIjo0Mn0=",
  "has_more": true,
  "limit": 20
}
```

If `has_more` is false, `next_cursor` is null.

### Step 5: Support Multiple Sort Fields

The cursor must encode the sort field's value. For `sort_by=rating`, the cursor contains the rating and ID. For `sort_by=title`, it contains the title and ID.

Make the cursor encoding handle different types: strings (title), floats (rating), datetimes (created_at), integers (year). The decode function must also handle type restoration -- dates encoded as strings need to be parsed back.

### Step 6: Keep Offset Pagination for Admin

Ensure your admin endpoints (manga management, user management, task list) still use offset pagination. Create an `OffsetPaginator` utility that takes a base query and applies `.offset()` and `.limit()`, returning total count and items.

### Step 7: Test Pagination Correctness

Verify these properties:
1. **Completeness**: paginating through ALL pages returns every item exactly once (no items skipped or duplicated)
2. **Stability**: inserting a new item while paginating does not cause items to shift between pages
3. **Performance**: page 1 and page 100 have the same query time (verify with EXPLAIN ANALYZE)
4. **Edge cases**: empty results, single-item result, cursor for the last page returns `has_more: false`

## Expected Outcome
- `GET /manga?limit=20` returns the first 20 manga with a next_cursor
- Following next_cursor pages through all manga returns every item exactly once
- Page 1 and page 1000 have identical query performance (~5ms)
- Invalid cursors return 400 Bad Request, not 500
- Admin endpoints still support offset pagination with page numbers
- Multiple sort fields work with cursors (created_at, title, rating)

## Hints
- The "fetch limit + 1" trick avoids a COUNT query to determine has_more. If you get 21 items (limit=20), there are more pages. Return only the first 20.
- For DESC ordering, use `<` comparison: `WHERE (created_at, id) < (:cursor_val, :cursor_id)`. For ASC, use `>`.
- PostgreSQL supports row value comparisons natively: `WHERE (created_at, id) < ('2025-06-15', 42)` works as a single comparison.
- In SQLAlchemy, use `sqlalchemy.tuple_(Model.created_at, Model.id) < sqlalchemy.tuple_(cursor_val, cursor_id)` for row value comparison.

## What I'll Look For In Review
- Cursors are opaque tokens (base64-encoded), not raw sort values in the URL
- The cursor includes both the sort value AND the ID as a tie-breaker
- The "limit + 1" pattern is used instead of a separate COUNT query
- Invalid cursors produce a 400, not a 500
- Both cursor and offset pagination exist: cursor for public APIs, offset for admin
