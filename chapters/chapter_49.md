# Chapter 49 — Follow System & Activity Feed

## Concepts You'll Learn
- Social graph modeling (follower/following with polymorphic targets)
- Activity tracking with polymorphic targets
- Fan-out-on-read vs fan-out-on-write patterns for feeds

## Concept Deep Dive

### Social Graph Modeling

A social graph represents relationships between entities. In MangaShelf, users can follow two different types of entities: other users and manga series. This is a **polymorphic follow** pattern — the "followed" target is not a single table but varies by type.

The classic approach is to store a `followed_type` discriminator alongside a `followed_id`. This is similar to how you modeled comments with polymorphic targets in Chapter 48. The key difference is that follows are bidirectional in terms of querying — you need to efficiently answer both "who does user X follow?" and "who follows user X?" (or "who follows manga Y?"). This means you need composite indexes on both `(follower_id, followed_type)` and `(followed_type, followed_id)`.

```python
class FollowedType(str, enum.Enum):
    USER = "user"
    MANGA = "manga"
```

A unique constraint on `(follower_id, followed_type, followed_id)` prevents duplicate follows. One subtlety: a user should not be able to follow themselves. This is a business rule you enforce in the service layer, not the database — there is no clean way to express "follower_id != followed_id WHEN followed_type = 'user'" as a database constraint (you could use a check constraint, but it is fragile and couples your schema to business logic).

Think of the social graph like a directed graph in computer science. Each follow is a directed edge from follower to followed. The "following" list is the out-edges of a node; the "followers" list is the in-edges. The feed is essentially a traversal: "walk all out-edges, gather recent activity from each destination node."

### Activity Tracking with Polymorphic Targets

An activity record captures "User X did Action Y on Target Z at Time T." This is the raw material for building feeds. Every interesting action in MangaShelf — writing a review, rating a manga, adding something to a library, completing a series — generates an activity record.

The activity model is polymorphic in two ways: the `action_type` tells you what happened, and `target_type` + `target_id` tell you what it happened to. A `metadata` JSON column stores action-specific details (like the rating value, or the review snippet) so the feed can render meaningful cards without joining back to the source tables.

```python
class ActionType(str, enum.Enum):
    REVIEW = "review"
    RATE = "rate"
    ADD_TO_LIBRARY = "add_to_library"
    COMPLETE_MANGA = "complete_manga"
```

The key design decision is *when* to create activities. You should hook into your existing service layer — after a review is created, after a rating is saved, after a library entry changes. This is the **event sourcing** adjacent pattern: every state change emits an event (the activity record). You are not doing full event sourcing, but you are capturing a log of user actions.

Index `(user_id, created_at DESC)` for "get all activities by user X" and `(target_type, target_id, created_at DESC)` for "get all activities on manga Y." These are the two primary access patterns.

### Fan-Out-on-Read vs Fan-Out-on-Write

When building a feed, you have two fundamental architectural choices:

**Fan-out-on-read** means the feed is assembled at query time. When user A requests their feed, you look up everyone A follows, then query for recent activities from all those sources, merge-sort them by time, and return the result. This is simple to implement and means writes are cheap (just insert the activity). But reads get expensive as users follow more people. For MangaShelf's scale, this is the right choice.

```sql
-- Fan-out-on-read: assemble feed at query time
SELECT a.* FROM activities a
JOIN follows f ON f.followed_id = a.user_id AND f.followed_type = 'user'
WHERE f.follower_id = :current_user_id
ORDER BY a.created_at DESC
LIMIT 20;
```

**Fan-out-on-write** means when an activity is created, you immediately copy it into every follower's personal feed table. Reads become trivial (just query the user's feed table), but writes become expensive — if a user has 10,000 followers, creating one activity means 10,000 inserts. Twitter famously uses a hybrid: fan-out-on-write for most users, fan-out-on-read for celebrities with millions of followers.

For MangaShelf, fan-out-on-read is the pragmatic choice. Your user base is small enough that the read-time query is fast, especially with proper indexes. You would only switch to fan-out-on-write if feed query latency became a bottleneck at scale — and by then, you would likely add Redis-cached feeds as an intermediate step before going full fan-out-on-write.

## Your Task

### Step 1: Create the Follow Model

Create `app/models/follow.py` with a `Follow` model:
- `id` (UUID primary key)
- `follower_id` (UUID FK to users, not nullable)
- `followed_type` (Enum: user, manga)
- `followed_id` (UUID, not nullable — no FK since it is polymorphic)
- `created_at` (timestamp with timezone, server default now)

Add a unique constraint on `(follower_id, followed_type, followed_id)`. Add indexes on `(follower_id, followed_type)` and `(followed_type, followed_id)`.

### Step 2: Create the Activity Model

Create `app/models/activity.py` with an `Activity` model:
- `id` (UUID primary key)
- `user_id` (UUID FK to users, not nullable)
- `action_type` (Enum: review, rate, add_to_library, complete_manga)
- `target_type` (String, e.g., "manga", "review")
- `target_id` (UUID)
- `metadata` (JSON, nullable — stores extra data like rating value, review snippet)
- `created_at` (timestamp with timezone, server default now, indexed DESC)

Add a composite index on `(user_id, created_at DESC)`.

### Step 3: Generate an Alembic Migration

Run Alembic to generate a migration for both new models. Review the generated SQL to make sure the indexes and constraints are correct.

### Step 4: Create Follow Repository and Service

Create `app/repositories/follow_repository.py` with methods:
- `create_follow(follower_id, followed_type, followed_id)` — insert, raise if duplicate
- `delete_follow(follower_id, followed_type, followed_id)` — remove follow
- `get_followers(followed_type, followed_id, limit, cursor)` — who follows this entity
- `get_following(follower_id, followed_type, limit, cursor)` — what does this user follow
- `is_following(follower_id, followed_type, followed_id)` — boolean check

Create `app/services/follow_service.py` that wraps the repository and adds:
- Validation that user cannot follow themselves
- Validation that the target entity actually exists (check users table or manga table)
- Follow/unfollow toggle logic

### Step 5: Create Activity Repository and Service

Create `app/repositories/activity_repository.py` with methods:
- `create_activity(user_id, action_type, target_type, target_id, metadata)`
- `get_user_activities(user_id, limit, cursor)` — activities by a single user
- `get_feed_activities(followed_user_ids, followed_manga_ids, limit, cursor)` — fan-out-on-read query

Create `app/services/activity_service.py` that:
- Provides a `record_activity()` method
- Is called from existing services: ReviewService, RatingService, LibraryService when they perform create/update actions
- Includes the relevant metadata (e.g., for a rating activity, include the score)

### Step 6: Create Follow Endpoints

In `app/api/v1/endpoints/follows.py`:
- `POST /users/{user_id}/follow` — follow a user
- `DELETE /users/{user_id}/follow` — unfollow a user
- `POST /manga/{manga_id}/follow` — follow a manga
- `DELETE /manga/{manga_id}/follow` — unfollow a manga
- `GET /users/{user_id}/followers` — list followers (cursor paginated)
- `GET /users/{user_id}/following` — list following (cursor paginated)
- `GET /users/me/following` — current user's following list

### Step 7: Create Feed Endpoint

In `app/api/v1/endpoints/feed.py`:
- `GET /feed` — returns activities from followed users and followed manga, paginated by `created_at` cursor, most recent first. Each activity item should include enough data to render a feed card (user display name, action description, target title, timestamp).

### Step 8: Hook Activity Creation into Existing Services

Modify your existing `ReviewService`, rating logic, and `LibraryService` to call `activity_service.record_activity()` after successful operations. Pass relevant metadata so the feed items are self-contained.

## Expected Outcome
- A user can follow/unfollow other users and manga series
- Following yourself returns a 400 error
- Duplicate follows are handled gracefully (409 or idempotent)
- Activities are automatically created when users review, rate, add to library, or complete manga
- `GET /feed` returns a time-ordered stream of activities from followed entities
- Feed uses cursor-based pagination (no offset)
- Feed items contain enough metadata to render without additional API calls

## Hints
- For the feed query, use a UNION of "activities from followed users" and "activities from followed manga" — or do two subqueries and merge. The UNION approach is cleaner SQL.
- Remember to use `select_in_load` or similar to avoid N+1 when fetching user data for feed items.
- The cursor for time-based pagination is the `created_at` timestamp of the last item — use `WHERE created_at < :cursor ORDER BY created_at DESC LIMIT :limit`.
- When recording activities from existing services, be careful not to let activity creation failures break the main operation. Wrap in try/except or make it fire-and-forget.

## What I'll Look For In Review
- Polymorphic follow model with correct unique constraint and indexes
- Service-layer validation (no self-follow, target exists)
- Activity creation is wired into existing services without tight coupling
- Feed query is efficient (single query or minimal queries, not N+1)
- Cursor-based pagination on the feed endpoint using timestamps
