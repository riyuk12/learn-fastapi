# Chapter 43 — In-Memory Cache Layer

## Concepts You'll Learn
- Two-tier caching: process memory as L1, Redis as L2
- LRU eviction and the cachetools library
- Cache coherence across multiple application instances
- When in-memory caching helps and when it causes problems

## Concept Deep Dive

### Two-Tier Caching

Redis is fast (~1ms round-trip), but for truly hot data accessed thousands of times per second, even 1ms adds up. **In-memory caching** stores data directly in your Python process's memory -- access time is measured in microseconds (0.001ms), not milliseconds.

The two-tier architecture:

```
Request -> Check Process Memory (L1) -> HIT -> Return (~0.05ms)
                                     -> MISS -> Check Redis (L2) -> HIT -> Store in L1 -> Return (~1ms)
                                                                  -> MISS -> Query DB -> Store in L2 & L1 -> Return (~20ms)
```

This is the same concept as CPU cache hierarchies (L1, L2, L3 cache before main memory). Each tier is faster but smaller than the next. Your L1 (process memory) holds the hottest 100-1000 items. Your L2 (Redis) holds millions of items. The database (L3) holds everything.

What belongs in L1? Data that is:
- Accessed extremely frequently (every request or nearly)
- Small (a few KB, not MB)
- Rarely changes (genre list, tag list, app configuration, feature flags)

### LRU Eviction and cachetools

You cannot store everything in process memory -- you will run out of RAM. An **LRU (Least Recently Used)** cache automatically evicts the least recently accessed items when it reaches capacity. The `cachetools` library provides several cache implementations:

```python
from cachetools import TTLCache, LRUCache

# TTLCache: items expire after a fixed time AND evicts LRU when full
genre_cache = TTLCache(maxsize=100, ttl=3600)  # 100 items, 1 hour TTL

# LRUCache: no time-based expiry, just evicts least recently used when full
hot_cache = LRUCache(maxsize=500)
```

`TTLCache` combines size-based eviction (LRU) with time-based expiration (TTL). This is perfect for your use case: data expires to prevent staleness, and the cache never grows beyond a fixed size.

Using it:

```python
from cachetools import TTLCache
import asyncio

class MemoryCache:
    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = asyncio.Lock()
    
    async def get(self, key: str):
        return self._cache.get(key)
    
    async def set(self, key: str, value):
        async with self._lock:
            self._cache[key] = value
    
    async def delete(self, key: str):
        async with self._lock:
            self._cache.pop(key, None)
    
    async def clear(self):
        async with self._lock:
            self._cache.clear()
```

The `asyncio.Lock` is important: `TTLCache` is not thread-safe. If multiple async tasks write concurrently, you get race conditions. The lock serializes writes while reads can happen concurrently (since Python's dict reads are thread-safe for our purposes).

### Cache Coherence Across Instances

Here is the catch with in-memory caching: if you run multiple instances of your app (behind a load balancer), each instance has its own L1 cache. When instance A receives a write that updates the genre list, it clears its own L1 cache. But instance B's L1 cache still holds the old genre list. Instance B serves stale data until its TTL expires.

This is the **cache coherence** problem. Solutions:

1. **Accept the staleness**: For a genre list that changes once a month, having instance B serve the old list for up to 1 hour is fine. This is the simplest approach and works for most data.

2. **Short TTLs**: Set L1 TTL to 60 seconds. Maximum staleness is 60 seconds. The cost is slightly more Redis hits, but for ultra-hot data, even 60 seconds of L1 caching saves massive Redis traffic.

3. **Redis Pub/Sub invalidation**: When any instance invalidates a cache key, it publishes a message on a Redis channel. All instances subscribe and clear their L1 caches. This is the most correct solution but adds complexity.

For MangaShelf, option 1 or 2 is sufficient. Only consider Pub/Sub if you run 10+ instances and staleness causes user-visible issues.

### When In-Memory Caching Helps (and Hurts)

**Helps:**
- Genre list: requested on every search/discover page, changes almost never
- Tag list: popular tags requested frequently, changes when mods approve new tags
- App configuration: feature flags, rate limit thresholds
- Static lookups: status enums, reading mode options

**Hurts (do not do this):**
- User-specific data: each user's data is different, you would cache N items for N users, filling memory
- Frequently changing data: reading progress changes on every page turn -- caching it creates stale reads
- Large objects: a 500KB manga detail with all chapters wastes memory. L1 is for small, hot data.

A good rule of thumb: if the data is the same for all users and fits in one cache entry, it is a candidate for L1. If it varies per user or per entity, keep it in Redis (L2) only.

## Your Task

### Step 1: Create the Memory Cache Service

Create `app/services/memory_cache.py` with a `MemoryCacheService` class:

- Uses `cachetools.TTLCache` internally
- `get(key: str) -> Any | None`
- `set(key: str, value: Any) -> None`
- `delete(key: str) -> None`
- `clear() -> None`
- `stats() -> dict`: returns `{"size": current_items, "maxsize": max_items}`

Use an `asyncio.Lock` for write operations.

### Step 2: Create the Layered Cache

Create a `LayeredCache` class (in `app/services/cache.py` or a new file) that coordinates L1 and L2:

- `get(key: str) -> Any | None`: check L1, then L2 (Redis), populate L1 on L2 hit
- `set(key: str, value: Any, l1_ttl: int = 60, l2_ttl: int = 300) -> None`: store in both L1 and L2
- `delete(key: str) -> None`: delete from both L1 and L2
- `invalidate_pattern(pattern: str) -> None`: delete from L2 (Redis pattern), clear all of L1 (since we cannot pattern-match in a dict)

The layered cache should use the CacheService (Redis) from Chapter 41 as L2 and the MemoryCacheService as L1.

### Step 3: Cache Ultra-Hot Data in L1

Identify data that should be in L1 and apply the layered cache:

- **Genre list**: `GET /genres` -- cache in L1 for 1 hour. This data changes extremely rarely.
- **Popular tags**: `GET /tags/popular` -- cache in L1 for 30 minutes.
- **App configuration / feature flags**: If you have any global config, cache it in L1.

For these endpoints, the flow should be: check L1 (memory), check L2 (Redis), query database. Store the result in both layers.

### Step 4: Measure the Difference

Add timing to demonstrate the performance difference. Log or return timing info for each cache tier:

- L1 hit: ~0.05ms (just a dict lookup)
- L2 hit: ~1-2ms (network round-trip to Redis)
- Database: ~10-50ms (SQL query execution)

You can measure this by wrapping each tier's get operation with `time.perf_counter()` and logging the result at DEBUG level.

### Step 5: Create Admin Cache Management Endpoints

- `POST /admin/cache/clear`: clears both L1 and L2 caches. Useful when deploying new code or fixing bad cached data.
- `GET /admin/cache/stats`: returns L1 stats (size, maxsize) and L2 stats (dbsize, memory usage from Redis INFO).

These endpoints require admin role.

### Step 6: Document Cache Coherence Strategy

Add comments in the layered cache code explaining:
- Why L1 TTL should be shorter than L2 TTL (to limit staleness across instances)
- What data is safe for L1 (same for all users, rarely changes)
- How cache clearing works (each instance clears its own L1; Redis clear is global)

## Expected Outcome
- The genre list loads in ~0.05ms on L1 cache hit (measurable via logging)
- After L1 TTL expires, it loads from Redis in ~1ms (L2 hit)
- After both expire, it loads from the database in ~20ms and repopulates both caches
- `POST /admin/cache/clear` flushes both layers
- `GET /admin/cache/stats` shows L1 and L2 statistics
- The app works correctly with both caches empty (cold start)

## Hints
- `cachetools.TTLCache` requires `maxsize` and `ttl` in its constructor. A maxsize of 1000 and ttl of 3600 (1 hour) is reasonable for L1.
- The `asyncio.Lock` should be used for writes only. Reads from `TTLCache` do not need locking in a single-threaded async context (Python's GIL prevents true parallel execution of coroutines in a single process).
- For the layered get: on an L2 hit, store in L1 with the L1 TTL (not the remaining L2 TTL). The L1 TTL is always shorter.
- If `cachetools` is not installed, add it to your requirements: `pip install cachetools`.

## What I'll Look For In Review
- L1 uses TTLCache with a reasonable maxsize (not unbounded -- that is a memory leak)
- L1 TTL is shorter than L2 TTL (to limit staleness across instances)
- The layered cache populates L1 on L2 hits (no unnecessary database queries)
- Admin can clear both cache layers for operational purposes
- Only truly global, rarely-changing data is stored in L1 (not user-specific data)
