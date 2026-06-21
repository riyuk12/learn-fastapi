# Chapter 46 — Response Compression & Optimization

## Concepts You'll Learn
- Gzip and Brotli compression: how they reduce payload size over the wire
- Sparse fieldsets: letting clients request only the fields they need
- orjson for fast JSON serialization
- Benchmarking: measuring before and after to prove improvements

## Concept Deep Dive

### Gzip and Brotli Compression

Every HTTP response travels as bytes over the network. A JSON response with 100 manga records might be 85KB. On a 3G mobile connection (1 Mbps), that takes 680ms to download. Compression can reduce this to 12KB, downloading in under 100ms. That is nearly a 7x improvement for zero code changes.

**Gzip** is the most widely supported compression format. Every modern browser and HTTP client supports it. The client signals support via the `Accept-Encoding: gzip` header. The server compresses the response and adds `Content-Encoding: gzip`.

**Brotli** is a newer algorithm (by Google) that achieves 15-25% better compression than gzip at similar speeds. Support is nearly universal in modern browsers but less common in API clients. Brotli excels at compressing text (HTML, JSON, CSS), making it ideal for API responses.

FastAPI (via Starlette) includes `GZipMiddleware` out of the box:

```python
from starlette.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=500)
```

The `minimum_size=500` means responses smaller than 500 bytes are not compressed. Compression has CPU overhead -- for tiny responses, the overhead is not worth the savings.

For Brotli, you need the `brotli` package and a custom middleware or the `brotli-asgi` package. Brotli is a nice-to-have; gzip is essential.

### Sparse Fieldsets

When the frontend renders a manga list (grid of cards), it needs: `id`, `title`, `cover_url`, and maybe `avg_rating`. It does NOT need: `description` (500 characters), `chapters` (nested array), `created_at`, `updated_at`, or the twelve other fields on the Manga response.

**Sparse fieldsets** let the client request only the fields it needs: `GET /manga?fields=id,title,cover_url,avg_rating`. The server returns a trimmed response, reducing payload size and serialization time.

```python
@router.get("/manga")
async def list_manga(fields: str = None):
    manga_list = await manga_service.list_all()
    
    if fields:
        requested_fields = set(fields.split(","))
        return [
            {k: v for k, v in manga.dict().items() if k in requested_fields}
            for manga in manga_list
        ]
    
    return manga_list  # Full response
```

This is a simplified implementation. A production version would:
1. Validate that requested fields actually exist on the model
2. Optimize the database query to SELECT only needed columns
3. Handle nested fields (`fields=id,title,author.name`)

The JSON:API specification and GraphQL both standardize this concept. For REST APIs, the `?fields=` query parameter is the convention.

### orjson for Fast Serialization

Python's built-in `json` module is slow. It is written in Python (with some C acceleration) and does not optimize for common patterns. `orjson` is a JSON library written in Rust that is 3-10x faster for serialization and deserialization.

```python
import orjson

# Serialization: orjson returns bytes, not str
data = orjson.dumps({"id": 1, "title": "Dragon Ball", "rating": 9.2})
# b'{"id":1,"title":"Dragon Ball","rating":9.2}'

# orjson handles datetime, UUID, numpy natively
import datetime
orjson.dumps({"created": datetime.datetime.now()})
# b'{"created":"2025-06-15T10:30:00"}'
```

FastAPI supports custom response classes. Replace the default `JSONResponse` with an `ORJSONResponse`:

```python
from fastapi.responses import ORJSONResponse

app = FastAPI(default_response_class=ORJSONResponse)
```

This single line change makes every endpoint serialize with orjson. For an endpoint returning 100 manga records, serialization time drops from ~5ms to ~1ms. This matters at scale: if your API handles 1000 requests/second, you save 4 seconds of CPU time per second.

Note: `ORJSONResponse` requires the `orjson` package and is built into FastAPI (no additional middleware needed).

### Benchmarking

Optimization without measurement is guesswork. You need to benchmark before and after to prove your changes actually help. A good benchmark:

1. **Controls for variability**: run multiple iterations (100+), report the average and p99
2. **Measures the right thing**: response time? payload size? CPU usage? Each matters for different reasons.
3. **Uses realistic data**: benchmark with 100 manga records, not 2

A simple benchmark script using `httpx` (or `requests`):

```python
import httpx
import time
import statistics

async def benchmark(url: str, iterations: int = 100):
    async with httpx.AsyncClient() as client:
        times = []
        sizes = []
        for _ in range(iterations):
            start = time.perf_counter()
            response = await client.get(url)
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)  # ms
            sizes.append(len(response.content))
        
        print(f"Avg time: {statistics.mean(times):.1f}ms")
        print(f"P99 time: {sorted(times)[int(len(times)*0.99)]:.1f}ms")
        print(f"Avg size: {statistics.mean(sizes)/1024:.1f}KB")
```

Run this before and after each optimization to quantify the improvement.

## Your Task

### Step 1: Add GZip Middleware

Add `GZipMiddleware` to your FastAPI app with `minimum_size=500`. Place it correctly in the middleware stack (after CORS, before your custom middleware).

Verify it works: make a request with `Accept-Encoding: gzip` header and check that the response has `Content-Encoding: gzip`. Compare the `Content-Length` with and without the header.

### Step 2: Implement Sparse Fieldsets on Manga List

Modify `GET /manga` (and/or `GET /manga/discover`) to accept a `fields` query parameter:

- Parse the comma-separated field names
- Validate each field against the allowed set (the fields on your MangaResponse schema)
- Return only the requested fields
- If `fields` is not provided, return the full response (backward compatible)

Create a reusable utility for this (since other endpoints might use it later):

```python
def apply_sparse_fields(items: list[dict], fields: set[str]) -> list[dict]:
    return [{k: v for k, v in item.items() if k in fields} for item in items]
```

### Step 3: Switch to ORJSONResponse

Install `orjson` and configure FastAPI to use `ORJSONResponse` as the default response class. This is a one-line change in your app factory.

Verify: responses should be identical in content. The only difference is serialization speed (measurable in benchmarks).

### Step 4: Write the Benchmark Script

Create `scripts/benchmark.py` (or `tests/benchmark.py`) that:

1. Hits `GET /manga?limit=100` (full response) and measures:
   - Average response time over 100 requests
   - Average response body size
2. Hits `GET /manga?limit=100&fields=id,title,cover_url` (sparse) and measures the same
3. Runs with and without `Accept-Encoding: gzip` to measure compression impact
4. Prints a comparison table:

```
Scenario                    | Avg Time | Avg Size
Full, no gzip               | 45ms     | 85KB
Full, with gzip             | 42ms     | 12KB
Sparse, no gzip             | 38ms     | 15KB
Sparse, with gzip           | 35ms     | 3KB
```

### Step 5: Optimize Manga List Serialization

Look for other serialization bottlenecks:

- Are you generating presigned URLs for all 100 manga covers serially? Use `asyncio.gather` to parallelize.
- Are you loading unnecessary relationships (chapters, pages) when listing manga? Use lazy loading for list endpoints, eager loading for detail endpoints.
- Does your Pydantic model do unnecessary validation on output? Consider using `.model_dump()` with `mode="json"` for faster serialization.

### Step 6: Document Performance Results

Add a comment block at the top of your benchmark script with the results you measured. This serves as a baseline for future optimizations:

```python
"""
Performance Benchmark Results (2026-04-01)
==========================================
Environment: MacOS, Python 3.12, PostgreSQL 16, 100 manga records

Before optimizations:
  Full response: 45ms avg, 85KB
  
After GZip + sparse fields + orjson:
  Full+gzip: 42ms avg, 12KB (86% size reduction)
  Sparse+gzip: 35ms avg, 3KB (96% size reduction)
  
orjson vs json: 2.5x faster serialization
"""
```

## Expected Outcome
- Responses are gzip-compressed when the client supports it (check `Content-Encoding` header)
- `GET /manga?limit=100` response drops from ~85KB to ~12KB with gzip
- `GET /manga?fields=id,title,cover_url` returns only the requested fields
- Sparse + gzip response is ~3KB (96% reduction from the unoptimized baseline)
- orjson serialization is measurably faster (2-3x improvement visible in benchmarks)
- The benchmark script produces reproducible, comparable results

## Hints
- GZipMiddleware compresses the response body, not the request. The client must send `Accept-Encoding: gzip` for the server to compress.
- For sparse fieldsets, validate fields against a whitelist. Do not allow arbitrary field names -- an attacker could probe for hidden fields.
- `orjson.dumps()` returns `bytes`, not `str`. `ORJSONResponse` handles this correctly. If you use orjson manually, remember this difference.
- When benchmarking, make sure your app is not in debug mode (no auto-reload, no debug logging). Debug overhead skews results.

## What I'll Look For In Review
- GZip middleware is configured with a reasonable minimum_size (not compressing tiny responses)
- Sparse fieldsets validate the requested fields against an allowed set
- ORJSONResponse is the default (not manually applied per-endpoint)
- The benchmark script is reproducible and measures both time and size
- Results are documented so future optimizations can be compared against a baseline
