# Chapter 44 — Connection Pooling & Query Optimization

## Concepts You'll Learn
- Connection pool tuning: pool_size, max_overflow, pool_recycle, and what they mean
- Slow query logging: detecting performance problems before users notice
- EXPLAIN ANALYZE: reading PostgreSQL query plans
- Index optimization: knowing what to index and why

## Concept Deep Dive

### Connection Pool Tuning

Every database query requires a connection: a TCP socket between your app and PostgreSQL. Opening a new connection takes 5-20ms (TCP handshake, authentication, session setup). If every request opens a fresh connection, you waste 5-20ms before the query even starts. **Connection pooling** maintains a set of pre-opened connections that are reused across requests.

SQLAlchemy's async engine has several pool parameters:

```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,        # Persistent connections
    max_overflow=20,     # Temporary connections above pool_size
    pool_recycle=3600,   # Recycle connections after 1 hour
    pool_pre_ping=True,  # Verify connection is alive before using
    pool_timeout=30,     # Wait up to 30s for a connection
)
```

**pool_size** (default 5): The number of connections kept permanently open. These are reused across requests. Set this to the number of concurrent database operations your app typically handles. For a FastAPI app handling 50 concurrent requests where ~20% need a DB connection at any given moment, pool_size=10 is reasonable.

**max_overflow** (default 10): When all pool_size connections are busy, SQLAlchemy creates additional temporary connections, up to `pool_size + max_overflow`. These temporary connections are closed when returned to the pool (not kept alive). If even max_overflow is exhausted, the next request waits (up to pool_timeout) or raises an error.

**pool_recycle** (default -1, meaning no recycle): PostgreSQL and network equipment (firewalls, load balancers) may silently close idle connections. If your app grabs a "dead" connection from the pool, the query fails. `pool_recycle=3600` replaces connections older than 1 hour, preventing this. This is especially important in cloud environments where connections are routed through proxies.

**pool_pre_ping** (default False): Before using a connection from the pool, send a lightweight "SELECT 1" to verify it is alive. This catches dead connections that pool_recycle missed. The cost is one extra round-trip (~1ms) per connection checkout. Worth it for reliability.

### Slow Query Logging

You cannot optimize what you cannot measure. A slow query logger records every database query that exceeds a threshold (e.g., 100ms). This tells you exactly which queries need attention.

In SQLAlchemy, you can hook into the engine events:

```python
from sqlalchemy import event
import time
import logging

logger = logging.getLogger("slowquery")

@event.listens_for(engine.sync_engine, "before_cursor_execute")
def before_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info["query_start_time"] = time.perf_counter()

@event.listens_for(engine.sync_engine, "after_cursor_execute")
def after_execute(conn, cursor, statement, parameters, context, executemany):
    elapsed = time.perf_counter() - conn.info["query_start_time"]
    if elapsed > 0.1:  # 100ms threshold
        logger.warning(f"Slow query ({elapsed:.3f}s): {statement[:200]}")
```

Alternatively, create a middleware that wraps each request and logs the total DB time. This gives you per-request visibility rather than per-query.

### EXPLAIN ANALYZE

When you find a slow query, `EXPLAIN ANALYZE` is how you diagnose it. It shows PostgreSQL's query plan: which indexes it uses, how many rows it scans, and where time is spent.

```sql
EXPLAIN ANALYZE
SELECT m.* FROM manga m
JOIN manga_genres mg ON m.id = mg.manga_id
JOIN genres g ON mg.genre_id = g.id
WHERE g.name = 'Shonen'
ORDER BY m.avg_rating DESC
LIMIT 20;
```

The output shows operations like:
- **Seq Scan**: scanning every row in a table (slow for large tables)
- **Index Scan**: using an index (fast)
- **Bitmap Index Scan**: using an index to build a set, then fetching rows (good for multi-column conditions)
- **Sort**: sorting results (check if it is using an index or doing an in-memory sort)
- **Nested Loop / Hash Join / Merge Join**: how tables are joined

The key metrics:
- **actual time**: milliseconds for this operation (first row..last row)
- **rows**: number of rows processed
- **loops**: how many times this operation ran

If you see a Seq Scan on a table with 100,000 rows where you expected an index scan, you are missing an index.

### Index Optimization

Indexes speed up reads at the cost of slower writes (every INSERT/UPDATE must update the index). The art is knowing which columns to index.

**Index when:**
- The column is used in WHERE clauses frequently (e.g., `user_id`, `manga_id`, `status`)
- The column is used in JOIN conditions (foreign keys should always be indexed)
- The column is used in ORDER BY (especially with LIMIT)

**Composite indexes** cover multiple columns. The order matters:

```sql
-- Good for: WHERE manga_id = ? AND chapter_number = ?
-- Also good for: WHERE manga_id = ? (leftmost prefix)
-- NOT useful for: WHERE chapter_number = ? (no leftmost prefix)
CREATE INDEX idx_chapters_manga_num ON chapters (manga_id, chapter_number);
```

The leftmost prefix rule: a composite index on `(A, B, C)` can be used for queries filtering on `(A)`, `(A, B)`, or `(A, B, C)`, but NOT for `(B)` or `(C)` alone.

**Covering indexes** include all columns needed by a query, so PostgreSQL can answer it from the index alone without hitting the table ("index-only scan"):

```sql
CREATE INDEX idx_reading_progress_user ON reading_progress (user_id, updated_at DESC)
INCLUDE (manga_id, chapter_id, page_number);
```

## Your Task

### Step 1: Tune the Connection Pool

Update `app/db/session.py` (or wherever you create the async engine):

- Set `pool_size` to 10 (adjust based on your expected concurrency)
- Set `max_overflow` to 20
- Set `pool_recycle` to 3600
- Enable `pool_pre_ping`
- Set `pool_timeout` to 30

Add these values to `app/core/config.py` so they can be configured per environment (dev might use pool_size=5, production might use 20).

### Step 2: Create Slow Query Logging Middleware

Create middleware (or SQLAlchemy event hooks) that logs queries taking longer than 100ms. The log should include:

- The SQL statement (truncated to 200 characters for readability)
- The execution time in milliseconds
- The endpoint that triggered the query (if available from the request context)

Configure the threshold via `settings.SLOW_QUERY_THRESHOLD_MS` (default 100).

### Step 3: Run EXPLAIN ANALYZE on Key Queries

Connect to your PostgreSQL database and run EXPLAIN ANALYZE on these queries (adapt to your actual schema):

1. The discover endpoint's filtered query (from Chapter 37) with genre + status + rating filters
2. The reading history query (from Chapter 30) ordered by updated_at
3. The similar manga query (from Chapter 37) with the genre intersection
4. The search query (from Chapter 35) with tsvector matching

Document your findings in code comments near the relevant repository methods. Note which queries use indexes and which fall back to sequential scans.

### Step 4: Add Missing Indexes

Based on your EXPLAIN ANALYZE findings, create an Alembic migration that adds:

- Composite index on `chapters (manga_id, chapter_number)` -- critical for adjacent chapter lookups
- Index on `reading_progress (user_id, updated_at DESC)` if not already added in Chapter 30
- Index on `library_entries (user_id, status)` for filtered library queries
- Index on `manga_tags (tag_id)` for finding manga by tag (the FK index on manga_id should already exist)
- Any other indexes identified by your EXPLAIN ANALYZE analysis

### Step 5: Re-Run EXPLAIN ANALYZE After Indexes

After adding indexes, re-run the same EXPLAIN ANALYZE queries. Document the before and after:

- Query 1: 50ms (Seq Scan) -> 5ms (Index Scan)
- Query 2: 30ms -> 2ms
- etc.

This concrete evidence of improvement is the goal. Add these findings as comments in the migration file or the repository.

### Step 6: Add Connection Pool Monitoring

Create an admin endpoint `GET /admin/db/pool-stats` that returns the connection pool's state:

- Pool size (configured)
- Checked-in connections (idle, available)
- Checked-out connections (in use)
- Overflow connections (temporary, above pool_size)
- Total connections (checked-in + checked-out + overflow)

SQLAlchemy's pool object exposes these via `pool.status()`.

## Expected Outcome
- Connection pool is configured with production-appropriate values
- Queries over 100ms are logged with the SQL statement and duration
- EXPLAIN ANALYZE shows which queries use indexes and which do not
- New indexes drop slow query times from ~50ms to ~5ms
- Admin can view connection pool stats to monitor database connection health
- The pool handles connection failures gracefully (pool_pre_ping catches dead connections)

## Hints
- In SQLAlchemy async, access the sync_engine for event listeners: `engine.sync_engine`. Async engine is a wrapper.
- For pool stats, use `engine.pool.status()` which returns a string summary. Parse it or use `pool.size()`, `pool.checkedout()`, `pool.checkedin()`, `pool.overflow()` methods.
- When running EXPLAIN ANALYZE, use a database client (psql, pgAdmin, DBeaver), not through SQLAlchemy -- you want to see the raw query plan output.
- If a query uses a Seq Scan despite an index existing, PostgreSQL may have decided the index is not worth it (e.g., the table is tiny). Use `SET enable_seqscan = off;` temporarily to test if the index would be used.

## What I'll Look For In Review
- Pool settings are configurable via environment variables, not hardcoded
- pool_pre_ping is enabled for connection reliability
- Slow query logging has a configurable threshold and does not log query parameters (which might contain sensitive data)
- EXPLAIN ANALYZE results are documented as comments in the codebase (before/after index)
- Indexes follow the leftmost prefix rule for composite indexes
