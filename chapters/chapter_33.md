# Chapter 33 — Prefetch Endpoints & HTTP Caching

## Concepts You'll Learn
- Prefetching strategy: predicting what the user needs next
- HTTP conditional requests with ETag and If-None-Match
- Cache-Control headers and what "private" vs "public" means
- 304 Not Modified: saving bandwidth without serving stale data

## Concept Deep Dive

### Prefetching Strategy

When a user is reading chapter 5, there is a high probability they will read chapter 6 next. If the frontend waits until they finish chapter 5 to start loading chapter 6's images, there is a noticeable delay between chapters. **Prefetching** means the frontend starts loading the next chapter's data while the user is still reading the current one.

But the frontend should not prefetch the full chapter reader response (all images, all variants). That wastes bandwidth. Instead, you provide a **lightweight prefetch endpoint** that returns only the information needed to start loading images: the page URLs and basic metadata, without expensive data like blurhashes or webtoon layout calculations.

The prefetch flow:
1. User opens chapter 5. Frontend calls `GET /chapters/5/pages` (full data)
2. Frontend immediately calls `GET /chapters/5/prefetch` (lightweight data for chapters 6 and 7)
3. Frontend begins preloading the first few images of chapter 6 into the browser cache
4. User finishes chapter 5, opens chapter 6. Images are already cached. It feels instant.

This is how Netflix preloads the next episode's first frames and how Google preloads search results you are likely to click.

### ETags and Conditional Requests

An **ETag** (entity tag) is a fingerprint of a resource's content. When the server returns a response, it includes an `ETag` header -- a hash or version string representing that exact response. On subsequent requests, the client sends `If-None-Match: <etag>` header. The server checks: has anything changed? If the ETag matches (nothing changed), it returns `304 Not Modified` with no body. The client uses its cached copy.

```
First request:
  Client: GET /chapters/5/pages
  Server: 200 OK
          ETag: "a1b2c3d4e5"
          Body: { ... full response ... }

Second request:
  Client: GET /chapters/5/pages
          If-None-Match: "a1b2c3d4e5"
  Server: 304 Not Modified
          (no body)
```

For chapter pages, the ETag can be a hash of the page URLs or a hash of the page records' updated_at timestamps. If no pages have been added, removed, or reprocessed, the ETag stays the same.

In FastAPI, you compute the ETag, check the incoming header, and short-circuit:

```python
import hashlib

@router.get("/chapters/{chapter_id}/pages")
async def get_chapter_pages(chapter_id: int, request: Request):
    pages = await reader_service.get_pages(chapter_id)
    
    # Compute ETag from page data
    etag_source = "|".join(f"{p.id}:{p.updated_at}" for p in pages)
    etag = hashlib.md5(etag_source.encode()).hexdigest()
    
    # Check if client has current version
    if request.headers.get("if-none-match") == f'"{etag}"':
        return Response(status_code=304)
    
    response = build_full_response(pages)
    return JSONResponse(
        content=response,
        headers={"ETag": f'"{etag}"', "Cache-Control": "private, max-age=300"},
    )
```

### Cache-Control Headers

`Cache-Control` tells the client (and any intermediary proxies/CDNs) how to cache the response:

- **`private`**: only the browser can cache this, not CDNs or proxies. Use for user-specific data (reading progress, bookmarks) or presigned URLs (they are per-user secrets).
- **`public`**: CDNs and proxies can cache it. Use for data identical for all users (genre list, public manga metadata).
- **`max-age=300`**: the response is fresh for 300 seconds. The client will not even send a request during this window.
- **`no-cache`**: the client must always revalidate with the server (send If-None-Match). Confusingly, this does NOT mean "do not cache" -- it means "always check."
- **`no-store`**: truly never cache this. Use for sensitive data like auth tokens.

For chapter pages with presigned URLs, `private, max-age=300` is a good choice. The presigned URLs expire in 1 hour (from Chapter 25), so a 5-minute client-side cache is safe. After 5 minutes, the client revalidates. If pages haven't changed, the server returns 304 and the client refreshes its URL cache.

### 304 Not Modified

The 304 response is the performance hero of the web. A full chapter pages response might be 50KB of JSON. Returning 304 with no body saves that bandwidth entirely. For a user re-reading a chapter or navigating back, this makes the experience instantaneous.

The 304 also saves server-side work. If you detect the ETag match early, you can skip serialization, presigned URL generation, and response building. The earlier you check, the more work you save.

One subtlety: 304 responses must not include a body, but they should include the same `ETag` and `Cache-Control` headers as the full 200 response. This ensures the client knows its cache is still valid and for how long.

## Your Task

### Step 1: Create the Prefetch Endpoint

Create `GET /chapters/{chapter_id}/prefetch` that returns lightweight data for the next 2 chapters:

1. Determine the next 2 chapters after the given chapter (by chapter_number in the same manga)
2. For each, return: chapter_id, chapter_number, chapter_title, total_pages, and a list of page thumbnail URLs only (not full variants)
3. This response should be small -- no blurhashes, no dimensions, just enough for the frontend to start preloading

The response shape:
```json
{
  "chapters": [
    {
      "chapter_id": 6,
      "chapter_number": 6,
      "title": "The Journey Begins",
      "total_pages": 24,
      "thumbnail_urls": ["https://...", "https://...", ...]
    },
    {
      "chapter_id": 7,
      "chapter_number": 7,
      "title": "First Battle",
      "total_pages": 30,
      "thumbnail_urls": ["https://...", "https://...", ...]
    }
  ]
}
```

### Step 2: Add ETag Support to the Chapter Pages Endpoint

Modify `GET /chapters/{chapter_id}/pages` (from Chapter 32) to:

1. After fetching page data (but before generating presigned URLs if possible), compute an ETag. Use a hash of the page IDs and their `updated_at` timestamps -- this changes only when pages are added, removed, or reprocessed.
2. Check the `If-None-Match` request header. If it matches the computed ETag, return 304 immediately (skip presigned URL generation and response building).
3. Include the `ETag` header in the 200 response, formatted as `"<hash>"` (double-quoted, per the HTTP spec).

### Step 3: Add Cache-Control Headers

Add `Cache-Control` headers to these endpoints:

- Chapter pages (`GET /chapters/{id}/pages`): `private, max-age=300` -- pages rarely change, but presigned URLs are user-specific
- Prefetch (`GET /chapters/{id}/prefetch`): `private, max-age=600` -- next chapters change even less frequently
- Manga detail (`GET /manga/{id}`): `private, max-age=60` -- could change more often (new reviews, updated ratings)
- Manga list (`GET /manga`): `private, max-age=30` -- new manga could be added relatively frequently

### Step 4: Create a Cache Header Utility

Rather than manually setting headers in every endpoint, create a utility in `app/utils/cache_headers.py` (or similar):

- `set_cache_headers(response, max_age, private=True, etag=None)`: sets Cache-Control and optional ETag on a response
- `check_etag(request, etag) -> bool`: compares If-None-Match header with the computed ETag

Consider creating a FastAPI dependency or response class that handles this automatically for endpoints that opt in.

### Step 5: Add ETag to the Prefetch Endpoint

The prefetch endpoint should also support ETags. If no new chapters have been added after the current one, the prefetch data has not changed. Compute the ETag from the next chapters' IDs and updated_at values.

### Step 6: Test Caching Behavior

Test these scenarios manually or with curl:

1. First request to chapter pages: 200 with ETag header
2. Second request with `If-None-Match: "<etag>"`: 304 with no body
3. Upload a new page to the chapter: next request gets 200 with a new ETag
4. Prefetch returns 200 on first call, 304 on repeated calls if chapters haven't changed

```bash
# First request
curl -v http://localhost:8000/chapters/1/pages

# Note the ETag header in the response, then:
curl -v -H 'If-None-Match: "abc123"' http://localhost:8000/chapters/1/pages
# Should return 304
```

## Expected Outcome
- `GET /chapters/{id}/prefetch` returns lightweight data for the next 2 chapters
- `GET /chapters/{id}/pages` includes ETag and Cache-Control headers
- Repeated requests with matching ETag return 304 with no body
- Adding or modifying a page changes the ETag, causing a 200 on the next request
- Cache-Control headers are set appropriately for each endpoint type
- The prefetch response is significantly smaller than the full pages response

## Hints
- ETags must be quoted strings in the header: `ETag: "abc123"`, not `ETag: abc123`. The `If-None-Match` header from the client will also include the quotes.
- Use `hashlib.md5` or `hashlib.sha256` for computing ETags. MD5 is fine here since it is not used for security, just content fingerprinting.
- The 304 response in FastAPI is just `return Response(status_code=304)`. Include the ETag header but do not include a body.
- For `Cache-Control: private`, remember that presigned URLs should not be cached by CDNs since they contain secrets in the query string.

## What I'll Look For In Review
- ETag computation is based on content that actually changes (page timestamps), not random values
- The 304 short-circuit happens as early as possible, skipping expensive work (presigned URL generation)
- Cache-Control headers match the volatility of each resource (pages cache longer than manga lists)
- The prefetch endpoint returns genuinely lightweight data, not just the full response with fewer fields
- ETags are properly quoted per the HTTP specification
