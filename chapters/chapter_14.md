# Chapter 14 — Advanced Queries: Joins, Eager Loading, Pagination

## Concepts You'll Learn
- `selectinload` and `joinedload` for eager loading relationships
- The N+1 query problem and how to diagnose it
- Offset pagination with total count and page metadata
- Sorting with dynamic columns

## Concept Deep Dive

### The N+1 Problem

The N+1 problem is one of the most common performance pitfalls in ORM-based applications. Here's how it happens:

1. You query 20 manga records (1 query).
2. For each manga, you access `manga.genres` (which triggers a lazy load).
3. That's 20 additional queries to fetch genres — one per manga.

Total: 1 + 20 = 21 queries for what should logically be 2 queries (one for manga, one for all related genres). With 100 manga, it's 101 queries. With nested relationships (manga -> chapters -> pages), it gets exponentially worse.

The insidious part is that lazy loading works correctly — you get the right data. It's just devastatingly slow. And because each individual query is fast, you might not notice until you have real data volume.

To see this in action, temporarily set `echo=True` on your SQLAlchemy engine:

```python
engine = create_async_engine(DATABASE_URL, echo=True)
```

This logs every SQL query. Hit your manga list endpoint and count the queries. If you see one `SELECT` from `manga` followed by N `SELECT` from `manga_genre`/`genre`, you have an N+1 problem.

### selectinload and joinedload

SQLAlchemy provides eager loading strategies that solve N+1 by fetching related data upfront:

**`selectinload`** fires a second query using `IN` to fetch all related objects:

```python
from sqlalchemy.orm import selectinload

stmt = select(Manga).options(selectinload(Manga.genres))
result = await db.execute(stmt)
mangas = result.scalars().all()
# Query 1: SELECT * FROM manga
# Query 2: SELECT * FROM genre JOIN manga_genre WHERE manga_genre.manga_id IN (id1, id2, ...)
```

Two queries total, regardless of how many manga there are. Each manga's `.genres` is already populated — no lazy loading needed.

**`joinedload`** uses a SQL JOIN to fetch everything in one query:

```python
from sqlalchemy.orm import joinedload

stmt = select(Manga).options(joinedload(Manga.genres))
result = await db.execute(stmt)
mangas = result.unique().scalars().all()
# Query 1: SELECT * FROM manga JOIN manga_genre JOIN genre
```

One query, but the result set can be much larger (one row per manga-genre combination). Note the `.unique()` call — it's required with `joinedload` to deduplicate the results.

**When to use which:**
- `selectinload`: best for one-to-many and many-to-many relationships. Predictable query count. Works well with pagination.
- `joinedload`: best for one-to-one and many-to-one relationships. One query, but can create huge result sets for one-to-many.

For our manga-genre relationship (many-to-many), `selectinload` is the right choice. You can chain them for multiple relationships:

```python
stmt = select(Manga).options(
    selectinload(Manga.genres),
    selectinload(Manga.authors),
)
```

### Offset Pagination with Metadata

In Chapter 4, you used basic offset/limit pagination. Now it's time to add metadata so clients know how many total results exist and how many pages there are:

```json
{
    "items": [...],
    "total": 47,
    "page": 2,
    "limit": 20,
    "pages": 3
}
```

This requires two queries: one for the data (`SELECT ... LIMIT 20 OFFSET 20`) and one for the count (`SELECT COUNT(*) FROM manga WHERE ...`). The count query must apply the same filters as the data query but doesn't need sorting, limit, or offset.

```python
from sqlalchemy import func

# Count query
count_stmt = select(func.count()).select_from(Manga).where(...)
total = (await db.execute(count_stmt)).scalar_one()

# Data query
data_stmt = select(Manga).where(...).offset(offset).limit(limit)
items = (await db.execute(data_stmt)).scalars().all()

pages = (total + limit - 1) // limit  # Ceiling division
```

Create a Pydantic response model for paginated results:

```python
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    pages: int
```

### Sorting with Dynamic Columns

Allowing clients to sort by different columns (`?sort_by=title&order=asc`) requires mapping the query parameter to a model column dynamically:

```python
SORTABLE_COLUMNS = {
    "title": Manga.title,
    "created_at": Manga.created_at,
    "status": Manga.status,
}

sort_column = SORTABLE_COLUMNS.get(sort_by, Manga.created_at)
if order == "desc":
    sort_column = sort_column.desc()
stmt = stmt.order_by(sort_column)
```

Always whitelist sortable columns. Never pass the raw query parameter to `order_by()` — that's a SQL injection vector.

## Your Task

### Step 1: Enable SQL logging temporarily

Set `echo=True` on your engine. Hit `GET /api/v1/manga` and count the SQL queries in the logs. If you have N manga with genres, you should see the N+1 problem in action.

### Step 2: Add eager loading to repository methods

Update your `MangaRepository` methods (especially `get_multi` and any filtered listing methods) to use `selectinload` for `Manga.genres` and `Manga.authors`. Also update `get` (by ID) to eager-load relationships.

### Step 3: Verify N+1 is solved

With eager loading in place and `echo=True`, hit the endpoint again. You should see exactly 2-3 queries regardless of how many manga exist (one for manga, one for genres, one for authors).

### Step 4: Create a paginated response schema

Create `app/schemas/common.py` (if you haven't already) with a `PaginatedResponse` generic model containing `items`, `total`, `page`, `limit`, and `pages`.

### Step 5: Add count queries to the repository

Add a `count(db, filters)` method to your `MangaRepository` that returns the total count of matching records. The filters should match whatever filters the list method applies.

### Step 6: Update the manga list endpoint

Modify `GET /api/v1/manga` to return the paginated response shape:

```json
{
    "items": [
        {"id": "...", "title": "One Piece", "genres": [...], ...},
        ...
    ],
    "total": 47,
    "page": 2,
    "limit": 20,
    "pages": 3
}
```

The endpoint (or service) should:
1. Run the count query with filters
2. Run the data query with filters, pagination, sorting, and eager loading
3. Calculate `pages` from `total` and `limit`
4. Return the assembled response

### Step 7: Add sorting

Add `sort_by` and `order` query parameters:
- `sort_by`: one of `title`, `created_at`, `status`. Default: `created_at`
- `order`: one of `asc`, `desc`. Default: `desc`

Whitelist the sortable columns in your repository or service.

### Step 8: Turn off SQL echo

Set `echo=False` (or remove it) before committing. SQL logging is too noisy for normal development.

## Expected Outcome
- `GET /api/v1/manga` returns a paginated response with `items`, `total`, `page`, `limit`, `pages`
- With 20 manga, the endpoint executes 2-3 SQL queries (not 21+)
- Sorting works: `?sort_by=title&order=asc` returns alphabetically sorted results
- All filters (status, genre) work in combination with pagination and sorting
- Swagger UI documents the paginated response shape

## Hints
- When using `selectinload` with pagination, the eager loading applies only to the paginated subset (not all records). This is efficient.
- `func.count()` with `select_from(Manga)` avoids issues with counting from joined tables.
- For the paginated response generic, you can use `Generic[T]` from `typing`, but FastAPI's Swagger might not fully resolve the generic. An alternative is to create model-specific paginated types: `PaginatedMangaResponse`.
- Ceiling division: `pages = -(-total // limit)` is a Python trick, or use `math.ceil(total / limit)`.

## What I'll Look For In Review
- Eager loading is used for all list/detail queries involving relationships
- N+1 is provably solved (was tested with `echo=True` and query count is constant)
- Paginated response includes accurate `total` and `pages` values
- Sorting is whitelisted (only allowed columns, not arbitrary input)
- Count query applies the same filters as the data query
