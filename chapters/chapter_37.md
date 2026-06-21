# Chapter 37 — Advanced Filtering & Discovery

## Concepts You'll Learn
- Dynamic query builders: composing SQLAlchemy filters programmatically
- AND/OR filter logic and how to express it in code
- "Similar manga" recommendations via shared attributes
- Composable query patterns that scale with feature growth

## Concept Deep Dive

### Dynamic Query Builders

A discovery page has many filters: genres, status, year range, rating range, sort order. The naive approach is a giant if/else chain:

```python
# Don't do this
query = select(Manga)
if genres:
    query = query.where(...)
if status:
    query = query.where(...)
if year_min:
    query = query.where(...)
if year_max:
    query = query.where(...)
# ... 15 more if statements
```

This works but becomes unmaintainable as filters grow. A **dynamic query builder** constructs the query programmatically from a filter specification:

```python
class MangaQueryBuilder:
    def __init__(self):
        self._query = select(Manga)
        self._filters = []
        self._joins = set()

    def with_genres(self, genres: list[str], mode: str = "AND"):
        self._joins.add("genres")
        if mode == "AND":
            for genre in genres:
                self._filters.append(Genre.name == genre)
        else:  # OR
            self._filters.append(Genre.name.in_(genres))
        return self

    def with_status(self, status: str):
        self._filters.append(Manga.status == status)
        return self

    def with_year_range(self, min_year: int = None, max_year: int = None):
        if min_year:
            self._filters.append(Manga.year >= min_year)
        if max_year:
            self._filters.append(Manga.year <= max_year)
        return self

    def build(self) -> Select:
        query = self._query
        for join in self._joins:
            query = query.join(...)  # Add necessary joins
        for f in self._filters:
            query = query.where(f)
        return query
```

The builder pattern lets you chain filters fluently and add new filters without modifying existing code. Each filter method returns `self`, enabling `builder.with_genres([...]).with_status("ongoing").build()`.

### AND/OR Filter Logic

Genre filtering has a subtle UX decision: when a user selects "Shonen" and "Adventure," do they want manga that are BOTH Shonen AND Adventure, or manga that are EITHER Shonen OR Adventure?

**OR mode** (union): returns manga in any of the selected genres. This is broader and shows more results. Good for discovery.

**AND mode** (intersection): returns manga that have ALL selected genres. This is narrower and more precise. Good for filtering.

Implementing AND for a many-to-many relationship requires some SQL thinking. You cannot just do `WHERE genre IN ('Shonen', 'Adventure')` -- that is OR. For AND, you need to ensure the manga has rows for ALL specified genres:

```sql
-- AND: manga that have BOTH Shonen AND Adventure
SELECT m.id FROM manga m
JOIN manga_genres mg ON m.id = mg.manga_id
JOIN genres g ON mg.genre_id = g.id
WHERE g.name IN ('Shonen', 'Adventure')
GROUP BY m.id
HAVING COUNT(DISTINCT g.name) = 2;  -- Must match ALL 2 genres
```

In SQLAlchemy:

```python
from sqlalchemy import func

subquery = (
    select(manga_genres.c.manga_id)
    .join(Genre)
    .where(Genre.name.in_(genres))
    .group_by(manga_genres.c.manga_id)
    .having(func.count(func.distinct(Genre.name)) == len(genres))
).subquery()

query = select(Manga).where(Manga.id.in_(select(subquery.c.manga_id)))
```

### Similar Manga Recommendations

"Similar manga" is a lightweight recommendation system based on shared attributes. The algorithm: find manga that share the most genres (and optionally author) with the target manga, excluding the target itself.

```sql
SELECT m2.id, m2.title, COUNT(*) as shared_genres
FROM manga_genres mg1
JOIN manga_genres mg2 ON mg1.genre_id = mg2.genre_id AND mg1.manga_id != mg2.manga_id
JOIN manga m2 ON mg2.manga_id = m2.id
WHERE mg1.manga_id = :target_manga_id
GROUP BY m2.id, m2.title
ORDER BY shared_genres DESC
LIMIT 10;
```

This query finds all manga that share at least one genre with the target, counts how many genres they share, and ranks by that count. If "Dragon Ball" is tagged Shonen, Adventure, and Fantasy, a manga tagged Shonen and Adventure would score 2 (sharing two genres).

You can boost the score for shared authors:

```python
score = shared_genre_count * 1.0 + same_author * 2.0
```

This is not machine learning -- it is simple attribute matching. But it produces surprisingly good results for a content library and requires zero training data.

### Composable Query Patterns

As your app grows, you will add more filters: rating range, number of chapters, recently updated, has cover image, etc. The key principle is **composability**: each filter is an independent unit that can be added or removed without affecting others.

```python
# Each filter is a standalone function
def filter_by_rating(query, min_rating, max_rating):
    if min_rating is not None:
        query = query.where(Manga.avg_rating >= min_rating)
    if max_rating is not None:
        query = query.where(Manga.avg_rating <= max_rating)
    return query

def filter_by_year(query, min_year, max_year):
    # similar pattern
    return query

def sort_by(query, sort_field, direction="desc"):
    column = getattr(Manga, sort_field, Manga.created_at)
    order = column.desc() if direction == "desc" else column.asc()
    return query.order_by(order)
```

You can compose these as a pipeline: start with a base query, apply each filter if its parameter is present. New filters are just new functions -- the existing ones do not change.

## Your Task

### Step 1: Create the Discovery Query Builder

Create `app/repositories/discovery.py` with a `MangaDiscoveryQuery` class or a set of composable filter functions. Support these filters:

- **Genres**: list of genre names with AND/OR mode
- **Status**: manga publication status
- **Year range**: min_year and max_year
- **Rating range**: min_rating and max_rating
- **Sort**: by title, year, avg_rating, recently_added, recently_updated

Each filter should be optional. Omitting a filter means "no constraint on that dimension."

### Step 2: Create the Discovery Endpoint

Create `GET /manga/discover` with these query parameters:

- `genres`: comma-separated genre names (e.g., `genres=Shonen,Adventure`)
- `genre_mode`: "and" or "or" (default "or")
- `status`: string
- `year_min`, `year_max`: integers
- `rating_min`, `rating_max`: floats (1.0 to 10.0)
- `sort`: one of "relevance", "rating", "year", "title", "recent"
- `sort_dir`: "asc" or "desc" (default "desc")
- `limit`, `offset`: pagination

The endpoint constructs the query dynamically using only the provided filters.

### Step 3: Implement the Genre AND Filter

For `genre_mode=and`, implement the HAVING COUNT approach described above. Test it: selecting "Shonen" AND "Adventure" should only return manga tagged with BOTH genres.

For `genre_mode=or`, a simple `IN` clause suffices. Use `DISTINCT` to avoid duplicate manga when a manga matches multiple genres.

### Step 4: Create the Similar Manga Endpoint

Create `GET /manga/{manga_id}/similar` that:

1. Loads the target manga's genres (and author)
2. Finds manga sharing the most genres with the target
3. Boosts manga by the same author
4. Excludes the target manga itself
5. Returns the top 10 similar manga

Include the `shared_genres` count (or computed score) in the response so the frontend can display "Similar because: Shonen, Adventure."

### Step 5: Add Discovery Response Schema

Create `app/schemas/discovery.py`:

- `DiscoverFilters`: the parsed filter parameters (use a Pydantic model or FastAPI dependencies to parse and validate)
- `DiscoverResponse`: results list with total count, applied filters echo, and pagination info
- `SimilarMangaResponse`: manga details plus `shared_attributes` list

### Step 6: Test Complex Filter Combos

Test these scenarios:
- No filters: returns all manga, sorted by default
- Genres only: `?genres=Shonen` returns all Shonen manga
- Genres AND status: `?genres=Shonen&status=ongoing`
- Year + rating range: `?year_min=2020&rating_min=7.0`
- All filters combined: verify they compose correctly (AND logic between different filter types)
- Similar manga: verify results share attributes with the target

## Expected Outcome
- `GET /manga/discover` supports any combination of filters
- Genre AND mode correctly requires all specified genres
- Genre OR mode returns manga matching any specified genre
- Results are properly sorted and paginated
- `GET /manga/{id}/similar` returns manga with shared genres/author
- No combination of filters causes a SQL error or empty-string crash
- Omitting all filters returns a reasonable default (all manga, sorted by recency)

## Hints
- For the AND genre filter, the key is `HAVING COUNT(DISTINCT genre) = len(genres)`. If you use `COUNT(*)` without `DISTINCT`, duplicate genre assignments would give wrong results.
- Use SQLAlchemy's `.distinct()` on the manga query when filtering by genres in OR mode to avoid duplicate rows
- For sorting by "relevance" when no search query is present, fall back to a sensible default (avg_rating or recently updated)
- The similar manga query is essentially a self-join through the genre association table

## What I'll Look For In Review
- Filters are composed dynamically, not via a giant if/else block
- Genre AND/OR modes produce genuinely different results
- The query builder handles edge cases: empty genre list, invalid sort field, rating out of range
- Similar manga uses actual shared-attribute counting, not random selection
- The endpoint does not break when all filters are omitted or when unusual combinations are used
