# Chapter 35 — PostgreSQL Full-Text Search

## Concepts You'll Learn
- tsvector and tsquery: PostgreSQL's built-in full-text search engine
- GIN indexes for fast text search
- Search ranking with ts_rank
- pg_trgm extension for fuzzy/typo-tolerant search

## Concept Deep Dive

### tsvector and tsquery

PostgreSQL has a full-text search engine built right in. No external service needed. It works with two data types: **tsvector** (the document, preprocessed for searching) and **tsquery** (the search query, also preprocessed).

A `tsvector` is a sorted list of **lexemes** -- normalized words. PostgreSQL strips stop words ("the", "a", "is"), applies stemming ("running" becomes "run"), and records word positions:

```sql
SELECT to_tsvector('english', 'The Dragon Ball Super manga is amazing');
-- Result: 'amaz':7 'ball':3 'dragon':2 'manga':5 'super':4
```

Notice: "The", "is" are removed (stop words). "amazing" becomes "amaz" (stemming). Each word has a position number.

A `tsquery` is the search condition:

```sql
SELECT plainto_tsquery('english', 'dragon ball');
-- Result: 'dragon' & 'ball'
```

`plainto_tsquery` converts user input into an AND-combined query. `to_tsquery` expects explicit operators (`&` for AND, `|` for OR). For a search bar, `plainto_tsquery` is safer since users do not type operators.

Matching is done with the `@@` operator:

```sql
SELECT * FROM manga
WHERE to_tsvector('english', title || ' ' || description) @@ plainto_tsquery('english', 'dragon ball');
```

### GIN Indexes

The query above works, but it recomputes `to_tsvector` for every row on every search. For a table with 10,000 manga, that is slow. **GIN indexes** (Generalized Inverted Indexes) precompute and store the tsvector, making searches near-instant.

You have two options: index a generated column, or index an expression.

**Option 1: Stored tsvector column (recommended)**
```sql
ALTER TABLE manga ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, ''))
    ) STORED;

CREATE INDEX idx_manga_search_vector ON manga USING GIN (search_vector);
```

The `GENERATED ALWAYS AS ... STORED` column auto-updates when title or description changes. The GIN index on this column makes searches O(log n) instead of O(n).

**Option 2: Expression index**
```sql
CREATE INDEX idx_manga_search ON manga USING GIN (
    to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, ''))
);
```

Option 1 is preferable because you can reference `search_vector` directly in queries, making the code cleaner.

### Search Ranking with ts_rank

Finding matching results is step one. **Ranking** them by relevance is step two. `ts_rank` scores each result based on how well it matches the query:

```sql
SELECT title, ts_rank(search_vector, query) AS rank
FROM manga, plainto_tsquery('english', 'dragon') AS query
WHERE search_vector @@ query
ORDER BY rank DESC;
```

`ts_rank` considers: how many query terms match, where they appear (title matches are often weighted higher than description matches), and how close the terms are to each other.

You can weight different parts of the document. PostgreSQL supports four weight classes (A, B, C, D):

```sql
-- Weight title (A) higher than description (B)
to_tsvector('english', setweight(to_tsvector('english', title), 'A') ||
            setweight(to_tsvector('english', description), 'B'))
```

With weights, a match in the title ranks higher than the same match in the description.

### pg_trgm for Fuzzy Matching

Full-text search is great for exact words, but users make typos. Searching "drgon ball" returns nothing because "drgon" is not a valid English word and does not stem to "dragon." The **pg_trgm** (trigram) extension solves this.

Trigrams are all three-character substrings of a word. "dragon" produces: "  d", " dr", "dra", "rag", "ago", "gon", "on ". "drgon" produces: "  d", " dr", "drg", "rgo", "gon", "on ". They share several trigrams, so pg_trgm considers them similar.

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX idx_manga_title_trgm ON manga USING GIN (title gin_trgm_ops);

-- Fuzzy search
SELECT title, similarity(title, 'drgon ball') AS sim
FROM manga
WHERE title % 'drgon ball'  -- % means "similar to"
ORDER BY sim DESC;
```

The `%` operator uses a similarity threshold (default 0.3). You can combine full-text search for exact matches with trigram similarity for fuzzy fallback: first try tsvector search, if too few results, fall back to trigram.

## Your Task

### Step 1: Add the Search Vector Column

Create an Alembic migration that:

1. Adds a `search_vector` column of type `tsvector` to the Manga table. Use a generated column if your PostgreSQL version supports it (12+), otherwise add a plain tsvector column that you maintain with triggers or application code.
2. Creates a GIN index on `search_vector`
3. Backfills existing rows: `UPDATE manga SET search_vector = to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, ''))`

If using a generated column, the backfill is automatic. If using a plain column, add a trigger or ensure your application code updates it on INSERT/UPDATE.

### Step 2: Enable pg_trgm

In the same or a separate migration:

1. Run `CREATE EXTENSION IF NOT EXISTS pg_trgm`
2. Create a GIN trigram index on the title column: `CREATE INDEX idx_manga_title_trgm ON manga USING GIN (title gin_trgm_ops)`

### Step 3: Create the Search Repository

Create `app/repositories/search.py` (or add to the manga repository) with:

- `full_text_search(query: str, limit: int, offset: int) -> list[Manga]`: uses `search_vector @@ plainto_tsquery('english', query)` with `ts_rank` ordering
- `fuzzy_search(query: str, limit: int, threshold: float = 0.3) -> list[Manga]`: uses pg_trgm similarity on the title
- `search(query: str, limit: int, offset: int) -> list[Manga]`: combines both -- tries full-text first, falls back to fuzzy if insufficient results

### Step 4: Create the Search Endpoint

Create `GET /search` with:

- `q`: required query string parameter
- `limit`: optional (default 20, max 50)
- `offset`: optional (default 0)

The endpoint should:
1. Run full-text search first
2. If fewer than `limit` results, supplement with fuzzy matches (excluding already-found manga)
3. Return results with a relevance score

Response shape:
```json
{
  "query": "drgon ball",
  "results": [
    {"id": 1, "title": "Dragon Ball", "cover_url": "...", "relevance": 0.85},
    {"id": 2, "title": "Dragon Ball Z", "cover_url": "...", "relevance": 0.72}
  ],
  "total": 2
}
```

### Step 5: Update the Manga Model

If you are not using a generated column, update your Manga model to include the `search_vector` column. Ensure that when a manga's title or description is updated, the search vector is recomputed. You can do this in the service layer before saving.

### Step 6: Test Search Quality

Test these cases:
- Exact match: "Dragon Ball" finds "Dragon Ball"
- Partial match: "Dragon" finds "Dragon Ball", "Dragon Quest", etc.
- Typo: "drgon" or "draogn" finds "Dragon Ball" via fuzzy search
- Multiple terms: "ball super" finds "Dragon Ball Super"
- No results: "xyzabc123" returns an empty list, not an error

## Expected Outcome
- `GET /search?q=dragon` returns manga with "dragon" in title or description, ranked by relevance
- `GET /search?q=drgon` (typo) still finds "Dragon Ball" via fuzzy matching
- Results are ranked: exact title matches appear before description matches
- The search is fast (under 50ms) thanks to GIN indexes
- New manga are automatically searchable after creation (search vector is maintained)

## Hints
- In SQLAlchemy, use `func.to_tsvector`, `func.plainto_tsquery`, and `func.ts_rank` from `sqlalchemy.func`
- The `@@` operator in SQLAlchemy is `.match()` on a tsvector column, or use `.op('@@')` for explicit control
- For the Alembic migration, use `op.execute()` to run raw SQL for creating extensions and indexes that are not easily expressed in Alembic's Python API
- Test with `EXPLAIN ANALYZE` to verify your queries use the GIN index (look for "Bitmap Index Scan")

## What I'll Look For In Review
- The search_vector column has a GIN index and is maintained automatically (generated column or application logic)
- Full-text search and fuzzy search are combined: exact matches first, fuzzy as fallback
- The search endpoint does not crash on empty queries, special characters, or very long input
- Results include a relevance score so the frontend can display them meaningfully
- The Alembic migration handles backfilling existing data, not just new rows
