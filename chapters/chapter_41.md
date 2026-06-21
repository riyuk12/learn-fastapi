# Chapter 41 — Redis Fundamentals & Connection Setup

## Concepts You'll Learn
- Redis data structures: strings, hashes, lists, sets, sorted sets, and TTL
- redis.asyncio library and connection pooling
- The @cached decorator pattern for transparent caching
- Migrating the rate limiter to Redis for multi-instance support

## Concept Deep Dive

### Redis Data Structures

Redis is not just a key-value store -- it is a **data structure server**. Each key maps to a specific data type, and Redis provides atomic operations tailored to each type. Understanding which structure to use for each problem is the key to using Redis effectively.

**Strings**: The simplest type. Stores a single value (string, number, or serialized JSON). Used for caching entire responses, counters, and flags.
```
SET manga:42:detail '{"id": 42, "title": "..."}' EX 300
GET manga:42:detail
INCR page_views:42  # Atomic increment
```

**Hashes**: A map of field-value pairs under a single key. Used for storing objects without serializing/deserializing the entire thing:
```
HSET user:1:stats total_manga 42 chapters_read 350 streak 12
HGET user:1:stats total_manga  # Returns "42"
HINCRBY user:1:stats chapters_read 1  # Atomic increment of one field
```

**Lists**: Ordered sequences. Useful for queues, recent activity feeds, and notification lists:
```
LPUSH user:1:recent_reads "manga:42"  # Push to front
LTRIM user:1:recent_reads 0 19  # Keep only the 20 most recent
LRANGE user:1:recent_reads 0 9  # Get the 10 most recent
```

**Sets**: Unordered collections of unique values. Useful for tags, memberships, and "has the user already done X" checks:
```
SADD manga:42:genres "shonen" "adventure"
SISMEMBER manga:42:genres "shonen"  # O(1) membership check
SINTER manga:42:genres manga:99:genres  # Common genres between two manga
```

**Sorted Sets**: Like sets but each member has a score. Used for leaderboards, ranking, and time-based ordering:
```
ZADD popular_manga 8.5 "manga:42" 9.2 "manga:7" 7.8 "manga:15"
ZREVRANGE popular_manga 0 9  # Top 10 by score
```

**TTL (Time To Live)**: Any key can have an expiration. After TTL seconds, the key is automatically deleted:
```
SET cache:manga:42 '...' EX 300  # Expires in 5 minutes
TTL cache:manga:42  # Seconds remaining
```

### redis.asyncio and Connection Pooling

For your async FastAPI app, use the `redis.asyncio` module (part of the `redis` package). It provides a non-blocking Redis client.

**Connection pooling** is essential. Opening a new TCP connection to Redis for every operation adds ~1ms overhead. A connection pool maintains a set of persistent connections that are reused:

```python
import redis.asyncio as aioredis

pool = aioredis.ConnectionPool.from_url(
    "redis://localhost:6379/0",
    max_connections=20,
    decode_responses=True,  # Return strings, not bytes
)
redis_client = aioredis.Redis(connection_pool=pool)
```

`max_connections=20` means up to 20 concurrent Redis operations. If all 20 are busy, new operations wait for a connection to free up. For most apps, 10-20 connections suffice.

`decode_responses=True` is important: without it, Redis returns `bytes` objects (`b"hello"`), requiring `.decode()` everywhere. With it, you get Python strings directly.

### The @cached Decorator Pattern

The most ergonomic way to add caching is a decorator. You wrap a function, and the decorator handles the check-cache-or-compute-and-store logic transparently:

```python
@cached(ttl=300, key_builder=lambda manga_id: f"manga:{manga_id}:detail")
async def get_manga_detail(manga_id: int):
    # This only runs on cache miss
    return await repo.get_with_relations(manga_id)
```

The decorator's logic:
1. Build the cache key from the function arguments
2. Check Redis for the key
3. If found (cache hit), deserialize and return
4. If not found (cache miss), call the original function
5. Serialize the result and store in Redis with the TTL
6. Return the result

Building this decorator teaches you several Python concepts: decorators with arguments, `functools.wraps`, async function wrapping, and JSON serialization of Pydantic models.

```python
import functools
import json

def cached(ttl: int, key_builder):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = key_builder(*args, **kwargs)
            
            # Check cache
            cached_value = await redis_client.get(cache_key)
            if cached_value:
                return json.loads(cached_value)
            
            # Compute
            result = await func(*args, **kwargs)
            
            # Store
            await redis_client.set(cache_key, json.dumps(result, default=str), ex=ttl)
            return result
        return wrapper
    return decorator
```

### Migrating Rate Limiting to Redis

In Chapter 21, you built a rate limiter. If it uses in-memory storage (a Python dict), it only works for a single server instance. Two instances behind a load balancer each maintain independent counters -- a user could make 200 requests (100 per instance) against a 100-request limit.

Redis solves this because all instances share the same Redis. The rate limiting algorithm (sliding window, token bucket) works the same way, but the storage is centralized:

```python
async def check_rate_limit(key: str, limit: int, window: int) -> bool:
    """Sliding window rate limiter using Redis sorted set."""
    now = time.time()
    window_start = now - window
    
    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)  # Remove old entries
    pipe.zadd(key, {str(now): now})               # Add current request
    pipe.zcard(key)                                # Count requests in window
    pipe.expire(key, window)                       # Set TTL on the key
    results = await pipe.execute()
    
    request_count = results[2]
    return request_count <= limit
```

Using a Redis **pipeline** sends all four commands in a single round-trip. This is important: four separate Redis calls would be 4ms; a pipeline is ~1ms.

## Your Task

### Step 1: Set Up Redis Connection

Create `app/db/redis.py`:

- Create an async Redis connection pool from `settings.REDIS_URL`
- Export a `get_redis()` async function (or dependency) that returns the Redis client
- Add connection pool configuration: `max_connections`, `decode_responses=True`
- Add a health check function: `ping()` that verifies Redis connectivity

Add `REDIS_URL` (default `redis://localhost:6379/0`) to `app/core/config.py`.

### Step 2: Create the Cache Service

Create `app/services/cache.py` with a `CacheService` class:

- `__init__(self, redis)`: accepts the Redis client
- `get(key: str) -> str | None`: get a cached value
- `set(key: str, value: str, ttl: int = 300) -> None`: store a value with TTL
- `delete(key: str) -> None`: delete a specific key
- `invalidate_pattern(pattern: str) -> int`: delete all keys matching a glob pattern (e.g., `manga:42:*`). Use `SCAN` with the pattern, not `KEYS` (KEYS blocks Redis on large databases).
- `exists(key: str) -> bool`: check if a key exists

The service handles JSON serialization/deserialization internally. The caller passes Python objects; the service converts to/from JSON strings.

### Step 3: Build the @cached Decorator

Create the `@cached` decorator in `app/services/cache.py` (or `app/utils/cache.py`):

- Parameters: `ttl` (seconds), `key_builder` (a callable that receives the same arguments as the decorated function and returns a string key)
- It should work with async functions
- On cache hit, return the cached value (deserialized from JSON)
- On cache miss, call the function, cache the result, return it
- If Redis is down, catch the connection error and fall through to the function (do not crash the app because Redis is unavailable)

### Step 4: Integrate Redis into Application Lifecycle

In your app's lifespan/startup handler:

1. Create the Redis connection pool
2. Verify connectivity with a PING
3. Log: "Redis connected: localhost:6379"

On shutdown:
1. Close the connection pool gracefully

### Step 5: Migrate the Rate Limiter to Redis

Refactor your rate limiter middleware from Chapter 21 to use Redis instead of in-memory storage:

1. Use a sorted set per rate-limit key (e.g., `ratelimit:user:1` or `ratelimit:ip:1.2.3.4`)
2. Implement the sliding window algorithm using Redis commands (ZREMRANGEBYSCORE, ZADD, ZCARD, EXPIRE)
3. Use a pipeline to execute all commands in a single round-trip
4. The rate limiter should continue to work if Redis is down (fall back to allowing requests, or use an in-memory fallback)

### Step 6: Write a Simple Integration Test

Create a test (or a manual verification script) that:

1. Sets a value in Redis with a 5-second TTL
2. Gets it back (should succeed)
3. Waits 6 seconds
4. Gets it again (should return None)
5. Tests the cache decorator on a mock function (verify it calls the function once, then returns cached)

## Expected Outcome
- Redis is connected and verified on app startup
- `CacheService` can get, set, delete, and pattern-invalidate
- The `@cached` decorator transparently caches async function results
- The rate limiter uses Redis, so limits are shared across app instances
- If Redis is down, the app still works (graceful degradation, not crashes)
- The connection pool is properly sized and closed on shutdown

## Hints
- Use `redis.asyncio.from_url(url, decode_responses=True)` for the simplest setup
- For `invalidate_pattern`, use `async for key in redis.scan_iter(pattern): await redis.delete(key)`. Never use `KEYS` in production -- it blocks the entire Redis server.
- The `@cached` decorator needs access to the Redis client. You can pass it as a parameter to the decorator factory, or use a module-level client instance.
- When serializing for cache, handle datetime objects: `json.dumps(data, default=str)` converts datetimes to strings.

## What I'll Look For In Review
- The Redis connection pool is properly configured with a reasonable max_connections value
- The CacheService uses SCAN (not KEYS) for pattern-based invalidation
- The @cached decorator handles Redis failures gracefully (catch exceptions, fall through)
- The rate limiter uses a pipeline to minimize Redis round-trips
- The connection pool is closed on app shutdown to prevent connection leaks
