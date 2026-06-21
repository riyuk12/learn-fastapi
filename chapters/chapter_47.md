# Chapter 47 — Reviews & Ratings

## Concepts You'll Learn
- One-per-user constraint: unique on (user_id, manga_id)
- Aggregate rating calculation and keeping it updated
- Denormalization for read performance: storing computed values alongside source data
- When to denormalize and how to keep denormalized data consistent

## Concept Deep Dive

### One-Per-User Constraint

A user should write exactly one review per manga. Not zero-or-many, not unlimited. One. This constraint is both a business rule ("edit your review" instead of "post another one") and a data integrity guarantee. Without it, a user could inflate a manga's rating by posting hundreds of 10/10 reviews.

The enforcement is a unique constraint on `(user_id, manga_id)`:

```python
class Review(Base):
    __tablename__ = "reviews"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    manga_id = Column(Integer, ForeignKey("manga.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-10
    title = Column(String(200))
    body = Column(Text)
    has_spoilers = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint("user_id", "manga_id", name="uq_review_user_manga"),
        CheckConstraint("rating >= 1 AND rating <= 10", name="ck_review_rating_range"),
    )
```

When a user tries to review a manga they have already reviewed, the database raises an `IntegrityError`. Your service layer catches this and returns a helpful message: "You have already reviewed this manga. Use PUT to update your review."

Note the `CheckConstraint` on rating. This is defense-in-depth: your Pydantic schema validates the range on input, but the database constraint catches anything that slips through (bulk imports, direct SQL, bugs).

### Aggregate Rating Calculation

Every manga needs an average rating displayed on its card: "8.5/10 (342 reviews)." Computing this live on every request requires joining with the reviews table and running AVG():

```sql
SELECT AVG(rating), COUNT(*) FROM reviews WHERE manga_id = 42;
```

For one manga, this is trivial. For a list of 20 manga, it becomes 20 subqueries or a complex GROUP BY. For a list of 100 manga on a discover page, it is unacceptably slow.

The solution: calculate the aggregate once (when a review is created, updated, or deleted) and store it directly on the Manga model.

```python
async def recalculate_manga_rating(manga_id: int):
    result = await session.execute(
        select(func.avg(Review.rating), func.count(Review.id))
        .where(Review.manga_id == manga_id)
    )
    avg_rating, rating_count = result.one()
    
    await session.execute(
        update(Manga)
        .where(Manga.id == manga_id)
        .values(
            avg_rating=round(float(avg_rating), 2) if avg_rating else 0,
            rating_count=rating_count,
        )
    )
```

Now `GET /manga` returns `avg_rating` and `rating_count` directly from the Manga row. No joins. No aggregation. O(1) per manga.

### Denormalization for Read Performance

Storing `avg_rating` and `rating_count` on the Manga model is **denormalization**: duplicating data to optimize reads. The canonical data lives in the Reviews table. The denormalized copy lives on Manga for fast access.

Denormalization introduces a consistency obligation: whenever the source data changes, the copy must be updated. If you forget to recalculate after deleting a review, the manga shows a stale rating. This is the trade-off: faster reads in exchange for more complex writes.

The pattern is: create a `recalculate_*` function that derives the value from the source, and call it from every write path (create, update, delete). Wrap the review mutation and the recalculation in the same database transaction so they either both succeed or both fail:

```python
async def create_review(user_id, manga_id, rating, title, body, has_spoilers):
    async with session.begin():
        review = Review(user_id=user_id, manga_id=manga_id, ...)
        session.add(review)
        await session.flush()  # Ensure the review is written
        await recalculate_manga_rating(manga_id)
    return review
```

### When to Denormalize

Denormalize when ALL of these are true:
1. The computed value is read far more often than it is written (ratings are read on every list view, written only on review create/update/delete)
2. The computation is expensive relative to the read (AVG with GROUP BY vs a single column read)
3. Slight staleness during the recalculation is acceptable (milliseconds between the review write and the rating update)

Do NOT denormalize when:
- The source data changes frequently (per-request counters)
- The computation is simple (COUNT on an indexed column is fast)
- Consistency is critical (financial data, inventory counts)

For MangaShelf, `avg_rating` and `rating_count` are perfect candidates. They are read thousands of times per minute (every manga list load) and written maybe a few times per day (when a user creates or edits a review).

## Your Task

### Step 1: Create the Review Model

Create `app/models/review.py` with:

- `id`: integer primary key
- `user_id`: FK to User, not null
- `manga_id`: FK to Manga, not null
- `rating`: integer, not null, check constraint 1-10
- `title`: string (max 200), nullable
- `body`: text, nullable
- `has_spoilers`: boolean, default False
- `created_at`: timestamp
- `updated_at`: timestamp (auto-updated)

Add unique constraint on `(user_id, manga_id)`.

### Step 2: Add Denormalized Rating Columns to Manga

Create an Alembic migration that adds to the Manga model:

- `avg_rating`: float, default 0.0
- `rating_count`: integer, default 0

If you already have a rating column from an earlier chapter, ensure it is named consistently.

### Step 3: Create the Review Repository

Create `app/repositories/review.py`:

- `create(user_id, manga_id, rating, title, body, has_spoilers) -> Review`
- `get_by_id(review_id) -> Review | None`
- `get_by_user_and_manga(user_id, manga_id) -> Review | None`
- `list_by_manga(manga_id, limit, offset) -> list[Review]`: ordered by created_at DESC
- `update(review_id, **fields) -> Review`
- `delete(review_id) -> None`
- `calculate_manga_rating(manga_id) -> tuple[float, int]`: returns (avg_rating, count)

### Step 4: Create the Review Service

Create `app/services/review.py`:

- `create_review(user_id, manga_id, data)`:
  1. Check that the manga exists
  2. Create the review (catch IntegrityError for duplicate)
  3. Recalculate and update manga's avg_rating and rating_count
  4. Invalidate manga detail cache
  
- `update_review(user_id, manga_id, data)`:
  1. Find the existing review (by user_id + manga_id)
  2. Update the fields
  3. Recalculate manga rating
  4. Invalidate cache

- `delete_review(user_id, manga_id)`:
  1. Find and delete the review
  2. Recalculate manga rating (it will change)
  3. Invalidate cache

- `get_manga_reviews(manga_id, limit, offset)`: list reviews with user info (username, avatar)

### Step 5: Create Review Endpoints

- `POST /manga/{manga_id}/reviews`: create a review. Body: `{rating, title?, body?, has_spoilers?}`. Returns 201. Returns 409 if already reviewed.
- `GET /manga/{manga_id}/reviews`: list reviews for a manga. Support pagination. Include reviewer's username.
- `GET /manga/{manga_id}/reviews/me`: get the current user's review for this manga (or 404).
- `PUT /manga/{manga_id}/reviews/me`: update the current user's review. Body: same as create.
- `DELETE /manga/{manga_id}/reviews/me`: delete the current user's review. Returns 204.

Note the route design: `/reviews/me` for the user's own review. This avoids the user needing to know the review ID.

### Step 6: Create Review Schemas

In `app/schemas/review.py`:

- `ReviewCreate`: rating (1-10, required), title (optional), body (optional), has_spoilers (default False)
- `ReviewUpdate`: same as create but all fields optional
- `ReviewResponse`: all fields plus reviewer username
- `ReviewListResponse`: list of reviews with pagination

### Step 7: Verify Rating Consistency

Write a test or manual verification:

1. Create 3 reviews for manga #1: ratings 7, 8, 9
2. Check manga #1: `avg_rating` should be 8.0, `rating_count` should be 3
3. Delete the review with rating 9
4. Check manga #1: `avg_rating` should be 7.5, `rating_count` should be 2
5. Update the rating-7 review to rating 10
6. Check manga #1: `avg_rating` should be 9.0, `rating_count` should be 2

## Expected Outcome
- Users can create one review per manga (second attempt returns 409)
- `GET /manga/{id}/reviews` lists reviews with reviewer info
- Creating, updating, or deleting a review immediately updates the manga's avg_rating and rating_count
- `GET /manga/{id}` shows accurate avg_rating and rating_count without any JOIN to the reviews table
- The rating check constraint prevents values outside 1-10
- The `has_spoilers` flag is available for frontend to show/hide review content

## Hints
- Use `round(float(avg), 2)` when storing avg_rating to avoid floating-point precision issues (8.333333333 -> 8.33)
- The `func.avg()` in SQLAlchemy returns `Decimal` by default in PostgreSQL. Cast to float for JSON serialization.
- For `GET /manga/{id}/reviews`, eager-load the User relationship to include username without N+1 queries
- When no reviews exist (all deleted), `func.avg()` returns None. Handle this: set avg_rating to 0.0 and rating_count to 0.

## What I'll Look For In Review
- The unique constraint on (user_id, manga_id) is in the model and migration
- Rating recalculation happens in the same transaction as the review write
- All three write paths (create, update, delete) trigger recalculation
- The avg_rating handles edge cases: zero reviews, single review, deleted last review
- Cache invalidation is triggered after rating updates so stale ratings are never served
