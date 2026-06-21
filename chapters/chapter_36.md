# Chapter 36 — Meilisearch Integration

## Concepts You'll Learn
- Why dedicated search engines exist alongside your database
- Indexing pipelines: getting data from your database into a search engine
- Keeping the search index in sync with the database
- Faceted search: filtering results by categories with counts

## Concept Deep Dive

### Why Dedicated Search Engines

In Chapter 35, you added full-text search to PostgreSQL. It works, but it has limitations. PostgreSQL's search is good for simple queries, but a dedicated search engine like Meilisearch offers: instant results (under 50ms even on large datasets), built-in typo tolerance without extensions, faceted filtering (filter by genre AND get genre counts), highlighted matching text, synonyms, stop words customization, and a relevance algorithm tuned for search, not for relational queries.

Think of it this way: PostgreSQL is a Swiss Army knife -- it does everything competently. Meilisearch is a chef's knife -- it does one thing exceptionally. For a production manga library where search is a core feature (users search dozens of times per session), the investment in a dedicated search engine pays for itself in user experience.

The trade-off: you now have two sources of data. Your database is the source of truth. The search engine is a **read replica** optimized for search queries. You must keep them in sync.

### Indexing Pipeline

An indexing pipeline moves data from your database into the search engine. It has three phases:

1. **Full reindex**: On startup (or manually), dump all manga from the database and push them to Meilisearch. This ensures the search index matches the database.

2. **Incremental sync**: When a manga is created, updated, or deleted, push the change to Meilisearch immediately. This keeps the index fresh between full reindexes.

3. **Reconciliation**: Periodically (daily?), compare the database and search index to catch any drift. This is your safety net for edge cases where the sync failed silently.

Meilisearch uses documents (JSON objects) identified by a primary key. Indexing is asynchronous -- you push documents and Meilisearch processes them in the background, returning a task ID. The document structure should be flat and include all fields you want to search or filter on:

```python
document = {
    "id": manga.id,
    "title": manga.title,
    "description": manga.description,
    "author": manga.author,
    "genres": ["Shonen", "Adventure"],  # Denormalized for faceting
    "status": manga.status,
    "year": manga.year,
    "avg_rating": manga.avg_rating,
    "cover_url": cover_url,
}
```

### Keeping the Search Index in Sync

The simplest sync strategy: hook into your existing manga create/update/delete operations in the service layer.

```python
class MangaService:
    async def create_manga(self, data):
        manga = await self.repo.create(data)
        await self.search_service.index_manga(manga)  # Sync to search
        return manga

    async def update_manga(self, manga_id, data):
        manga = await self.repo.update(manga_id, data)
        await self.search_service.index_manga(manga)  # Re-index
        return manga

    async def delete_manga(self, manga_id):
        await self.repo.delete(manga_id)
        await self.search_service.remove_from_index(manga_id)  # Remove
```

What if the search sync fails? The database transaction has already committed. You have two options: (1) catch the error and log it, accepting temporary inconsistency, or (2) enqueue the sync as a Celery task that retries on failure. Option 2 is more reliable and avoids slowing down the API response if Meilisearch is slow.

### Faceted Search

**Facets** are category counts alongside search results. When you search "dragon" and see "Shonen (12), Seinen (5), Fantasy (8)" in the sidebar, those are facets. They let users progressively narrow their search without starting over.

Meilisearch supports facets natively. You configure which fields are filterable and facetable:

```python
await client.index("manga").update_filterable_attributes(["genres", "status", "year"])
await client.index("manga").update_settings({
    "faceting": {"maxValuesPerFacet": 100}
})
```

Then in a search query:

```python
results = await client.index("manga").search("dragon", {
    "facets": ["genres", "status"],
    "filter": ["genres = Shonen"],
})
# results.facet_distribution = {"genres": {"Shonen": 12, "Seinen": 5}, "status": {"ongoing": 8, "completed": 9}}
```

The search returns results filtered to Shonen, plus facet counts for all genres matching the query. The user sees: 12 Shonen results, and if they remove the filter, there are also 5 Seinen results. This is extremely powerful for discovery.

## Your Task

### Step 1: Run Meilisearch via Docker

Start Meilisearch on port 7700:

```bash
docker run -d -p 7700:7700 -e MEILI_MASTER_KEY=your-master-key -v meili_data:/meili_data getmeili/meilisearch:latest
```

Add `MEILISEARCH_URL` and `MEILISEARCH_API_KEY` to your `app/core/config.py`.

### Step 2: Install the Meilisearch Python SDK

Add `meilisearch-python-sdk` (the async SDK) to your requirements. This is the official async-compatible client.

### Step 3: Create the Search Service

Create `app/services/search.py` with a `SearchService` class:

- `__init__`: creates a Meilisearch async client from config
- `setup_index()`: creates the "manga" index if it does not exist, configures searchable attributes (title, description, author), filterable attributes (genres, status, year), sortable attributes (avg_rating, year, title)
- `index_manga(manga: Manga) -> None`: converts a Manga ORM object to a search document and adds/updates it in the index
- `index_many(manga_list: list[Manga]) -> None`: batch-indexes multiple manga (more efficient for full reindex)
- `remove_from_index(manga_id: int) -> None`: deletes a document from the index
- `search(query: str, filters: dict = None, facets: list[str] = None, limit: int = 20, offset: int = 0) -> SearchResult`: searches with optional filters and facets

### Step 4: Full Reindex on Startup

In your application's lifespan/startup handler, call a function that:

1. Queries all manga from the database (with their genres loaded)
2. Batch-indexes them into Meilisearch via `index_many()`
3. Logs the count: "Indexed 1,234 manga into Meilisearch"

For large datasets, batch in groups of 500 to avoid memory issues.

### Step 5: Hook Sync into Manga CRUD

Modify your `MangaService` to call the search service on create, update, and delete. Consider making this non-blocking: if the search sync fails, log the error but do not fail the API request. Optionally, dispatch a Celery task for retry.

### Step 6: Create the Advanced Search Endpoint

Create `GET /search/advanced` with:

- `q`: search query (optional -- if omitted, returns all results, useful for browse/filter mode)
- `genres`: comma-separated list of genres to filter by
- `status`: filter by manga status (ongoing, completed, etc.)
- `year_min`, `year_max`: year range filter
- `sort`: sort option (relevance, rating, year, title)
- `limit`, `offset`: pagination
- `facets`: boolean, if true include facet counts in response

Response shape:
```json
{
  "query": "dragon",
  "results": [
    {"id": 1, "title": "Dragon Ball", "highlight": {"title": "<em>Dragon</em> Ball"}, ...}
  ],
  "total": 42,
  "facets": {
    "genres": {"Shonen": 12, "Seinen": 5, "Fantasy": 8},
    "status": {"ongoing": 20, "completed": 22}
  },
  "processing_time_ms": 3
}
```

### Step 7: Keep the PostgreSQL Search as Fallback

Do not remove the PostgreSQL search from Chapter 35. If Meilisearch is down, your `GET /search` endpoint can fall back to PostgreSQL. The advanced search endpoint is Meilisearch-only since PostgreSQL cannot do facets efficiently.

## Expected Outcome
- Meilisearch is running and accessible at `http://localhost:7700`
- All existing manga are indexed on app startup
- `GET /search/advanced?q=dragon` returns results in under 50ms
- Typos are tolerated: "drgon" finds "Dragon Ball"
- Faceted counts are returned: `{"genres": {"Shonen": 12, "Seinen": 5}}`
- Creating, updating, or deleting a manga updates the search index
- Highlighted matches are included in the response
- If Meilisearch is down, basic search still works via PostgreSQL

## Hints
- Meilisearch's Python async SDK uses `meilisearch_python_sdk.AsyncClient`. Check the SDK documentation for the exact API.
- When building the search document, denormalize genres into a list of strings (`["Shonen", "Adventure"]`) rather than IDs. Meilisearch needs human-readable values for facets.
- The `highlight` field in search results shows which parts of the text matched. Meilisearch wraps matches in `<em>` tags by default.
- For the startup reindex, use `add_documents_in_batches` if available in the SDK, or chunk your documents manually.

## What I'll Look For In Review
- Search service is cleanly separated from the manga service -- it is a collaborator, not embedded
- The index configuration (searchable, filterable, sortable attributes) is set up explicitly, not left to defaults
- Sync happens on create/update/delete, not just on startup
- The search endpoint returns Meilisearch metadata (processing time, facets, highlights)
- PostgreSQL search remains as a fallback if Meilisearch is unavailable
