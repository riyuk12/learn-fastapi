# Chapter 42 — Caching Strategy: What, Where, How Long

## Concepts You'll Learn
- Cache-aside pattern and write-through caching
- TTL tuning: matching cache duration to data volatility
- Cache stampede / thundering herd problem and how to prevent it
- Stale-while-revalidate: serving slightly old data while refreshing

## Concept Deep Dive

### Cache-Aside Pattern

The **cache-aside** (or "lazy loading") pattern is what you built in Chapter 41 with the `@cached` decorator. The application checks the cache first. On a miss, it queries the database, stores the result in the cache, and returns it. The cache is populated lazily -- only when data is requested.

```
Request -> Check Cache -> HIT -> Return cached data
                       -> MISS -> Query DB -> Store in cache -> Return data
```

The advantage: only data that is actually accessed gets cached. You do not waste memory caching manga that nobody reads. The disadvantage: the first request for any piece of data always hits the database (cold start), and you must handle cache invalidation on writes.

**Cache invalidation** is famously one of the two hard problems in computer science. When a manga's title is updated, the cached version is stale. You must explicitly delete or update the cache entry:

```python
async def update_manga(manga_id, data):
    manga = await repo.update(manga_id, data)
    await cache.delete(f"manga:{manga_id}:detail")  # Invalidate
    await cache.invalidate_pattern(f"manga:list:*")  # Invalidate lists too
    return manga
```

This is called **write-invalidate**: on write, delete the cache, and let the next read repopulate it. The alternative is **write-through**: on write, update both the database and the cache simultaneously. Write-through keeps the cache always warm but adds complexity (what if the cache update fails after the DB write?).

### TTL Tuning

TTL (Time To Live) controls how long cached data survives. The right TTL depends on how often the data changes and how stale it can be:

| Data | Volatility | Recommended TTL |
|------|-----------|----------------|
| Genre list | Almost never changes | 1 hour or longer |
| Manga detail | Changes on edit (rare) | 5 minutes |
| Manga list (paginated) | Changes when manga added | 1 minute |
| Search results | Changes as manga added/updated | 30 seconds |
| User profile | Changes on edit | 10 minutes |
| Reading progress | Changes constantly | Do not cache (or 10 seconds) |

The principle: **TTL = how wrong can you afford to be?** If a user updates their manga's description and it takes 5 minutes to reflect everywhere, is that acceptable? For most content sites, yes. For a stock trading price, absolutely not.

Short TTLs (10-30 seconds) still provide huge benefits. If 100 users request the manga list in 30 seconds, only 1 hits the database. The other 99 get the cached response in ~1ms instead of ~20ms. That is a 99% cache hit rate with only 30 seconds of potential staleness.

### Cache Stampede / Thundering Herd

Imagine a popular manga's cache entry expires. At that exact moment, 500 concurrent users request it. All 500 see a cache miss. All 500 query the database simultaneously. The database gets hammered with 500 identical queries. This is a **cache stampede** or **thundering herd**.

The solution: a **stampede lock**. When a cache miss occurs, the first request sets a short-lived lock in Redis (using `SETNX` -- SET if Not eXists). Other requests see the lock and either wait (blocking approach) or return stale data (non-blocking approach) while the first request repopulates the cache.

```python
async def get_with_stampede_protection(key: str, ttl: int, compute_fn):
    # Try cache first
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    
    # Try to acquire lock
    lock_key = f"lock:{key}"
    acquired = await redis.set(lock_key, "1", nx=True, ex=10)  # Lock for 10 seconds
    
    if acquired:
        # We got the lock -- compute and cache
        result = await compute_fn()
        await redis.set(key, json.dumps(result, default=str), ex=ttl)
        await redis.delete(lock_key)
        return result
    else:
        # Another request is computing -- wait briefly and retry
        await asyncio.sleep(0.1)
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)
        # Still nothing? Fall through to compute (safety net)
        return await compute_fn()
```

The `nx=True` flag on `SET` is atomic: only one request can acquire the lock. Redis guarantees this even under high concurrency.

### Stale-While-Revalidate

An alternative to stampede locks is **stale-while-revalidate**. You cache data with two TTLs: a short "fresh" TTL and a longer "stale" TTL. When the fresh TTL expires, the data is still available (stale). A background task refreshes the cache. Requests during revalidation get the stale data (slightly old but fast).

In practice, you store the data with a long TTL and a separate "fresh_until" timestamp:

```python
async def set_with_stale(key: str, value: str, fresh_ttl: int, stale_ttl: int):
    data = {
        "value": value,
        "fresh_until": time.time() + fresh_ttl,
    }
    await redis.set(key, json.dumps(data), ex=stale_ttl)

async def get_with_stale(key: str, compute_fn):
    cached = await redis.get(key)
    if cached:
        data = json.loads(cached)
        if time.time() < data["fresh_until"]:
            return data["value"]  # Fresh
        else:
            # Stale -- trigger background refresh, return stale data
            asyncio.create_task(refresh_cache(key, compute_fn))
            return data["value"]  # Stale but fast
    # Total miss
    return await compute_fn()
```

This pattern is inspired by the HTTP `Cache-Control: stale-while-revalidate` directive. The user never waits for a cache refresh -- they always get data instantly, even if it is slightly old.

## Your Task

### Step 1: Apply @cached to Key Endpoints

Using the decorator from Chapter 41, add caching to:

- **Manga detail** (`get_manga_by_id`): TTL 5 minutes. Key: `manga:{manga_id}:detail`
- **Manga list** (paginated): TTL 1 minute. Key: `manga:list:page:{page}:size:{size}`
- **Search results**: TTL 30 seconds. Key: `search:{query_hash}` (hash the query params)
- **User profile**: TTL 10 minutes. Key: `user:{user_id}:profile`

### Step 2: Implement Cache Invalidation on Writes

In your manga service, invalidate relevant caches on write operations:

- **Create manga**: invalidate `manga:list:*` (all list pages)
- **Update manga**: invalidate `manga:{id}:detail` and `manga:list:*` and relevant search caches
- **Delete manga**: invalidate `manga:{id}:detail` and `manga:list:*`

Create a helper method like `invalidate_manga_caches(manga_id)` that handles all the necessary invalidations.

### Step 3: Implement Stampede Lock

Create a function `get_or_compute_with_lock(key, ttl, compute_fn)` in your cache service that:

1. Checks the cache
2. On miss, attempts to acquire a lock using `SETNX`
3. If lock acquired, computes the value, stores it, releases the lock
4. If lock not acquired, waits briefly (100ms) and retries the cache
5. Has a safety fallback: if waiting too long, compute directly

Apply this to the most popular endpoint (manga detail) to protect against stampedes.

### Step 4: Add Cache Hit/Miss Metrics

Add logging or simple metrics to track cache effectiveness:

- Log cache hits and misses at DEBUG level
- Create an admin endpoint `GET /admin/cache/stats` that returns:
  - Total keys in Redis (approximate, using `DBSIZE`)
  - Memory usage (using `INFO memory`)
  - Optionally, hit/miss counts if you maintain them

### Step 5: Test Cache Behavior

Test these scenarios:

1. **Cache hit**: request manga detail twice. Second request should be fast (~1ms) and not hit the database.
2. **Cache invalidation**: update a manga. Next request should get fresh data (not cached old data).
3. **TTL expiry**: request manga detail, wait for TTL to expire, request again. Should hit the database.
4. **Pattern invalidation**: create a manga, verify all manga list cache entries are invalidated.

### Step 6: Document Your Caching Strategy

Add a comment block or docstring in `app/services/cache.py` that documents:
- Which endpoints are cached and their TTLs
- How invalidation works for each write operation
- The stampede lock strategy

This is not a markdown file -- it is an inline code comment that future-you (or a teammate) can reference when adding new cached endpoints.

## Expected Outcome
- Second request for manga detail returns in ~1ms (from Redis) instead of ~20ms (from database)
- Updating a manga immediately reflects in subsequent requests (cache invalidated)
- The stampede lock prevents multiple simultaneous database queries for the same cache key
- Cache stats are visible via the admin endpoint
- The app works correctly with Redis running (cached) and without Redis (degrades gracefully)

## Hints
- For `invalidate_pattern`, remember to use `scan_iter` not `KEYS`. Deleting many keys? Use a pipeline: collect keys with scan, delete in batches with pipeline.
- Hash search query parameters for cache keys: `hashlib.md5(json.dumps(sorted(params.items())).encode()).hexdigest()` produces a deterministic hash.
- The stampede lock's `ex=10` timeout is a safety net: if the computing request crashes, the lock auto-releases after 10 seconds so others can proceed.
- Do not cache responses that contain presigned URLs with short expiry times without accounting for the URL lifetime in the TTL.

## What I'll Look For In Review
- TTL values are reasonable and documented (not arbitrary numbers)
- Cache invalidation covers all write paths (create, update, delete)
- The stampede lock uses SETNX for atomic lock acquisition
- Cache key naming is consistent and hierarchical (e.g., `manga:{id}:detail`, not `mangadetail42`)
- The app does not crash when Redis is unavailable -- it degrades to direct database queries
