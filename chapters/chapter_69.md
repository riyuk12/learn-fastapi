# Chapter 69 — Analytics & Event Tracking

## Concepts You'll Learn
- Event-driven analytics architecture
- Time-series data with PostgreSQL table partitioning
- Aggregation pipelines for analytics
- Separating analytics queries from OLTP (transactional) queries

## Concept Deep Dive

### Event-Driven Analytics

Analytics answers questions about user behavior: What are the most popular manga? What do people search for? When do users read? How fast is the user base growing? These questions require tracking events — discrete actions that users take — and aggregating them over time.

The pattern is simple: every time something interesting happens, write an event to an analytics table. The event captures what happened, who did it (optionally), and when. Later, aggregation queries roll up these raw events into meaningful metrics.

```python
class AnalyticsEvent:
    event_type: str     # "page_view", "search", "reading_session", "registration"
    user_id: UUID | None  # nullable for anonymous events (page views)
    metadata: dict      # {"manga_id": "...", "query": "naruto", "page": 5}
    created_at: datetime  # partitioning key
```

The `metadata` JSON column is intentionally schemaless. Different event types need different data: a page view needs manga_id, a search needs the query string, a reading session needs chapter and duration. Using JSON lets you track any event without adding columns.

The key design principle: **write events generously, aggregate lazily**. Capture everything that might be useful. Aggregation can always be refined later, but you cannot analyze events you did not record.

### Time-Series Data with Table Partitioning

Analytics events are append-only time-series data: you write a lot of rows, and you almost always query them within a time window ("page views last 7 days," "search terms this month"). As the events table grows to millions of rows, queries slow down because PostgreSQL must scan or index the entire table.

**Declarative table partitioning** in PostgreSQL splits a table into smaller physical partitions based on a key (typically a timestamp). Each partition contains a time range (e.g., one month). When you query for events in January, PostgreSQL only scans the January partition, ignoring all other months.

```sql
CREATE TABLE analytics_events (
    id UUID DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL,
    user_id UUID,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Create monthly partitions
CREATE TABLE analytics_events_2024_01 PARTITION OF analytics_events
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE analytics_events_2024_02 PARTITION OF analytics_events
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
```

In SQLAlchemy, you can define the partitioned table with raw SQL in an Alembic migration (SQLAlchemy's ORM does not have native partitioning syntax, but you can execute partition DDL directly).

**Partition management**: You need to create new partitions before they are needed (if February's partition does not exist on February 1st, inserts will fail). Automate this with a Celery beat task that creates next month's partition on the first of each month. Old partitions can be dropped (or archived) to reclaim space — dropping a partition is instant, unlike deleting millions of rows.

### Aggregation Pipelines

Raw events are not directly useful for dashboards. "10 million page_view events" is not helpful; "top 20 manga by views this week" is. Aggregation transforms raw events into answers.

You have two aggregation strategies:

**On-demand aggregation** — Run the aggregation query when the admin requests it. Simple and always up-to-date, but slow for large datasets.

```sql
SELECT metadata->>'manga_id' AS manga_id, COUNT(*) AS views
FROM analytics_events
WHERE event_type = 'page_view'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY metadata->>'manga_id'
ORDER BY views DESC
LIMIT 20;
```

**Pre-aggregation** — Run aggregation on a schedule (Celery beat) and store results in a summary table. Dashboards query the summary table, which is fast. The trade-off is that data is slightly stale (up to the aggregation interval).

```python
# Celery task: runs every hour
@celery_app.task
def aggregate_popular_manga():
    # Query raw events, compute top manga
    results = db.execute(aggregation_query)
    # Upsert into a summary table
    for row in results:
        db.execute(upsert_summary, manga_id=row.manga_id, views=row.views)
```

For MangaShelf, use a combination: pre-aggregate expensive queries (popular manga, daily stats) on a schedule, and do on-demand aggregation for ad-hoc admin queries.

### Analytics vs OLTP Queries

OLTP (Online Transaction Processing) queries are the bread and butter of your application: "get manga by ID," "insert a review," "update reading progress." They touch one or a few rows, are fast, and happen during user requests.

Analytics queries are fundamentally different: they scan thousands or millions of rows, use GROUP BY and aggregations, and are computationally expensive. Running them on your primary database during peak traffic can slow down user-facing queries.

Solutions:
- **Read replica** (Chapter 70): Route analytics queries to a replica, keeping the primary fast.
- **Partitioning**: Reduces the scan scope for time-windowed queries.
- **Pre-aggregation**: Moves the heavy computation to off-peak hours.
- **Materialized views**: PostgreSQL can maintain pre-computed query results that refresh on demand.

For MangaShelf, partitioning plus Celery-based pre-aggregation is the practical approach. You will add read replicas in Chapter 70.

## Your Task

### Step 1: Create the AnalyticsEvent Model with Partitioning

Create an Alembic migration that creates the `analytics_events` table as a partitioned table:
- Partition by range on `created_at`
- Create partitions for the current month and next month
- Add an index on `(event_type, created_at)` for efficient filtering
- Add a GIN index on `metadata` for JSON queries

Since SQLAlchemy ORM does not natively support `PARTITION BY`, write the table creation as raw SQL in the Alembic migration. You can still create a SQLAlchemy model for ORM operations (reads and writes work normally on partitioned tables).

### Step 2: Create a Partition Management Task

Create a Celery beat task (`manage_analytics_partitions`) that:
- Runs on the first of each month (or daily for safety)
- Creates the partition for the next month if it does not exist
- Optionally drops partitions older than a retention period (e.g., 12 months)

### Step 3: Create the Analytics Service

Create `app/services/analytics.py` with:
- `track_event(event_type, user_id, metadata)` — inserts a raw analytics event
- Make this non-blocking: failures should not affect the user's request. Consider using a background task or Celery task for the insert.

### Step 4: Instrument Key User Actions

Call `track_event()` from your existing code:
- **Page views**: When manga detail is fetched, track `page_view` with `manga_id`
- **Search queries**: When search is performed, track `search` with the `query` string and `results_count`
- **Reading sessions**: When reading progress is saved, track `reading_session` with `manga_id`, `chapter_id`, `pages_read`
- **Registrations**: When a new user registers, track `registration`

### Step 5: Create Admin Analytics Endpoints

In your admin router, add:

`GET /admin/analytics/popular-manga`:
- Query parameters: `window` (7d, 30d, 90d), `limit` (default 20)
- Returns top manga by page view count within the time window
- Include manga title and cover URL (join or lookup from cache)

`GET /admin/analytics/search-terms`:
- Query parameters: `window`, `limit`
- Returns top searched terms with count
- Extract from `metadata->>'query'` in search events

`GET /admin/analytics/user-growth`:
- Query parameters: `window`, `granularity` (day, week, month)
- Returns registration count over time: `[{"date": "2024-01-15", "count": 12}, ...]`

`GET /admin/analytics/reading-activity`:
- Query parameters: `window`, `granularity`
- Returns reading session count and total pages read over time

### Step 6: Create Pre-Aggregation Tasks

Create Celery beat tasks:
- `aggregate_daily_stats` — runs at midnight, computes and stores: total views, total searches, total reading sessions, new users for the day
- `aggregate_popular_manga` — runs hourly, computes top 100 manga by views in the last 7 days

Store aggregated results in a `analytics_summaries` table:
- `summary_type` (string: "daily_stats", "popular_manga")
- `summary_date` (date)
- `data` (JSON — the aggregated results)
- `created_at`

The admin endpoints should first check the summary table (fast). If no recent summary exists, fall back to on-demand aggregation (slow but accurate).

### Step 7: Verify Partitioning Works

Insert test events across multiple months and verify:
- Events are routed to the correct partition
- Queries with time filters only scan relevant partitions (use `EXPLAIN ANALYZE`)
- The partition management task creates new partitions correctly

## Expected Outcome
- Analytics events are tracked for page views, searches, reading sessions, and registrations
- The events table is partitioned by month for efficient time-range queries
- Partition management runs automatically (creating new partitions, optionally dropping old ones)
- Admin analytics endpoints return popular manga, top search terms, user growth, and reading activity
- Pre-aggregation tasks compute daily/hourly summaries for fast dashboard queries
- Event tracking does not slow down user-facing requests

## Hints
- For the partitioned table in Alembic, use `op.execute()` with raw SQL. SQLAlchemy's `create_table` does not support `PARTITION BY`.
- To check that partition pruning is working, prepend `EXPLAIN (ANALYZE, COSTS)` to your query and look for "Partitions removed" in the output.
- For `track_event()`, consider inserting via a Celery task so the analytics write does not add latency to the user's request. But for simplicity, a direct async insert is fine for now — the insert is a single row and very fast.
- The `metadata` JSON queries use the `->>'key'` operator for text extraction. Index them with a GIN index on the `metadata` column for performance.

## What I'll Look For In Review
- Table is partitioned by range on `created_at`, not a regular table
- Partition management is automated (not requiring manual partition creation)
- Event tracking is decoupled from user-facing request latency
- Analytics endpoints use time-window filtering that benefits from partitioning
- Pre-aggregation exists for expensive queries, with on-demand fallback
