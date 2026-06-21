# Chapter 34 — Reading Statistics

## Concepts You'll Learn
- Aggregation queries: COUNT, SUM, GROUP BY in SQLAlchemy
- Materialized/denormalized stats vs live computation
- Precompute vs query-on-demand trade-offs
- Designing a stats service that pulls from multiple data sources

## Concept Deep Dive

### Aggregation Queries

SQL's aggregation functions (COUNT, SUM, AVG, GROUP BY) are purpose-built for computing statistics from large datasets. Instead of fetching 10,000 rows into Python and counting them, you let the database do the math and return a single number.

```sql
-- How many manga has this user completed?
SELECT COUNT(*) FROM reading_progress
WHERE user_id = 1 AND is_completed = true;

-- Pages read per genre
SELECT g.name, COUNT(DISTINCT rp.manga_id) as manga_count
FROM reading_progress rp
JOIN manga m ON rp.manga_id = m.id
JOIN manga_genres mg ON m.id = mg.manga_id
JOIN genres g ON mg.genre_id = g.id
WHERE rp.user_id = 1
GROUP BY g.name
ORDER BY manga_count DESC;
```

In SQLAlchemy, aggregations use `func`:

```python
from sqlalchemy import func, select

stmt = (
    select(func.count(ReadingProgress.id))
    .where(ReadingProgress.user_id == user_id)
    .where(ReadingProgress.is_completed == True)
)
result = await session.execute(stmt)
completed_count = result.scalar()
```

GROUP BY queries return multiple rows. You need `func.count()` with `.group_by()`:

```python
stmt = (
    select(Genre.name, func.count(ReadingProgress.manga_id))
    .join(Manga, ReadingProgress.manga_id == Manga.id)
    .join(manga_genres, Manga.id == manga_genres.c.manga_id)
    .join(Genre, manga_genres.c.genre_id == Genre.id)
    .where(ReadingProgress.user_id == user_id)
    .group_by(Genre.name)
    .order_by(func.count(ReadingProgress.manga_id).desc())
    .limit(5)
)
```

### Materialized/Denormalized Stats

The aggregation queries above are **live queries** -- they compute the result from the source data every time. For a user with 50 manga, this is instant (milliseconds). For a platform-wide stat like "total pages served across all users," scanning the entire reading_progress table on every request is expensive.

**Denormalization** means storing a precomputed result alongside the source data. You already did this conceptually in earlier chapters -- storing `avg_rating` on the Manga model instead of computing it from reviews every time. For user stats, you could maintain a `UserStats` table:

```python
class UserStats(Base):
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    total_manga_read = Column(Integer, default=0)
    total_chapters_read = Column(Integer, default=0)
    total_pages_viewed = Column(Integer, default=0)
    current_streak_days = Column(Integer, default=0)
    last_read_date = Column(Date)
    updated_at = Column(DateTime)
```

This table is updated whenever reading progress changes. The stats endpoint reads from this table instead of aggregating from the source.

### Precompute vs Query-on-Demand

When should you precompute, and when should you query live?

**Query live when:**
- The dataset is small (user has < 100 manga)
- The stat is rarely requested (profile page viewed once a day)
- The stat needs to be exactly real-time (live counts during an event)
- The computation is simple (COUNT with an index)

**Precompute when:**
- The dataset is large (platform-wide aggregations)
- The stat is requested frequently (shown on every page load)
- The computation is expensive (multiple JOINs, window functions)
- Slight staleness is acceptable (stats updated every hour)

For MangaShelf user stats, querying live is fine -- each user's data is small. But the reading streak calculation (consecutive days with activity) is tricky to compute live with SQL. That is a good candidate for precomputation or at least caching.

### Reading Streak Calculation

A "reading streak" is the number of consecutive days the user has read something. This is a classic "gaps and islands" problem in SQL. The approach: get all distinct dates the user read, then find the longest run of consecutive dates ending today.

In Python, this is easier than in SQL:

```python
from datetime import date, timedelta

def calculate_streak(read_dates: list[date]) -> int:
    if not read_dates:
        return 0
    
    today = date.today()
    dates = sorted(set(read_dates), reverse=True)
    
    # Must include today or yesterday to have a current streak
    if dates[0] < today - timedelta(days=1):
        return 0
    
    streak = 1
    for i in range(1, len(dates)):
        if dates[i - 1] - dates[i] == timedelta(days=1):
            streak += 1
        else:
            break
    return streak
```

Query the distinct dates from reading_progress where `updated_at` falls within a reasonable window (last 365 days), compute the streak in Python. This hybrid approach leverages the database for filtering and Python for the logic.

## Your Task

### Step 1: Create the Stats Service

Create `app/services/stats.py` with a `StatsService` class that computes all user statistics:

- `get_user_stats(user_id) -> UserStatsResponse`: the main method that assembles all stats
- `_get_library_stats(user_id) -> dict`: total manga in library, by status (reading, completed, etc.)
- `_get_reading_stats(user_id) -> dict`: chapters completed, pages viewed (approximate from progress data)
- `_get_streak(user_id) -> int`: current reading streak in consecutive days
- `_get_top_genres(user_id, limit=5) -> list[dict]`: most-read genres with counts

### Step 2: Implement Library Stats

Query the LibraryEntry model (from Chapter 38, but if you have not built it yet, use ReadingProgress):

- Total manga with any reading progress
- Manga completed (is_completed = true)
- Manga in progress (has progress, not completed)

### Step 3: Implement Reading Activity Stats

From the ReadingProgress model:

- Count distinct manga_ids (total manga touched)
- Count how many have is_completed = true (chapters completed is trickier -- you may need to track this separately or approximate)
- For pages viewed, use the max page_number from each progress record as an approximation (or track page view events separately if you add that later)

### Step 4: Implement Reading Streak

1. Query all distinct dates from `reading_progress.updated_at` for the user (within the last year)
2. Extract just the date portion (not datetime)
3. Calculate the streak using the consecutive-days algorithm
4. Return both the current streak and the longest streak ever (bonus)

### Step 5: Implement Top Genres

Join reading_progress with manga and the manga-genre association:

1. GROUP BY genre, COUNT distinct manga
2. ORDER BY count DESC, LIMIT 5
3. Return genre name and count

### Step 6: Create the Stats Endpoint

Create `GET /users/me/stats` that returns:

```json
{
  "library": {
    "total_manga": 42,
    "completed": 15,
    "in_progress": 20,
    "plan_to_read": 7
  },
  "reading": {
    "chapters_read": 350,
    "pages_viewed": 8750
  },
  "streak": {
    "current_days": 12,
    "longest_days": 30
  },
  "top_genres": [
    {"genre": "Shonen", "count": 18},
    {"genre": "Seinen", "count": 12},
    {"genre": "Fantasy", "count": 9}
  ]
}
```

### Step 7: Add Response Schema

Create `app/schemas/stats.py` with nested Pydantic models matching the response shape above. Use clear type annotations.

## Expected Outcome
- `GET /users/me/stats` returns comprehensive reading statistics
- Library counts (total, completed, in progress) are accurate
- The reading streak correctly counts consecutive days
- Top genres reflect actual reading patterns
- The endpoint responds within a reasonable time (under 200ms for a typical user)
- A user with no reading history gets zeroed-out stats, not an error

## Hints
- Use `func.date(ReadingProgress.updated_at)` or `cast(ReadingProgress.updated_at, Date)` to extract dates for the streak calculation
- For the streak, query dates in descending order and check from today backwards -- stop at the first gap
- If LibraryEntry from Chapter 38 does not exist yet, compute library stats from ReadingProgress instead
- Use `func.count(distinct(ReadingProgress.manga_id))` for counting unique manga

## What I'll Look For In Review
- All stats are computed from actual data, not hardcoded
- The streak calculation handles edge cases: no activity today (streak from yesterday), no activity at all (streak = 0), single-day activity
- Aggregation happens in SQL (not fetching all rows into Python and counting)
- The response is a clean, nested JSON structure that a frontend can render directly
- A new user with zero data gets a valid response (all zeros), not an error or null fields
