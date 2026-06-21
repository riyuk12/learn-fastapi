# Chapter 13 — Service Layer & Business Logic

## Concepts You'll Learn
- The service layer pattern and why it exists between endpoints and repositories
- Business logic orchestration: validation, transformation, and coordination
- Transaction boundaries and when to commit
- Slug generation for URL-friendly identifiers

## Concept Deep Dive

### Why a Service Layer?

You now have endpoints (HTTP handling) and repositories (database access). But where does business logic live? Consider creating a manga: you need to generate a URL-friendly slug from the title, check that the slug isn't already taken, look up or create genres, link the manga to its genres, and then create the manga record. None of this is "database access" (repository territory) and none of it is "parse the HTTP request" (endpoint territory). It's business logic, and it belongs in the service layer.

The service layer sits between the endpoint and the repository:

```
Endpoint (HTTP) → Service (Business Logic) → Repository (Database)
```

Each layer depends only on the one below it. The endpoint calls the service; the service calls the repository. The endpoint never calls the repository directly. This means your business logic is reusable: a CLI command, a background job, or a different API version can all call the same service methods.

### Business Logic Orchestration

A service method orchestrates a complete business operation. Here's what creating a manga involves:

1. **Transform**: Generate a slug from the title (e.g., "One Piece" becomes "one-piece")
2. **Validate**: Check that no manga with this slug already exists
3. **Resolve dependencies**: For each genre name, find the existing genre or create a new one
4. **Create**: Call the repository to insert the manga
5. **Link**: Associate the manga with its genres

Each of these steps might involve one or more repository calls, but the orchestration logic — the order, the error handling, the decision-making — lives in the service.

```python
class MangaService:
    def __init__(self, manga_repo: MangaRepository, genre_repo: GenreRepository):
        self.manga_repo = manga_repo
        self.genre_repo = genre_repo

    async def create_manga(self, db: AsyncSession, data: MangaCreate) -> Manga:
        slug = self._generate_slug(data.title)

        existing = await self.manga_repo.get_by_slug(db, slug)
        if existing:
            raise AlreadyExistsException("Manga", "slug")

        genres = await self._resolve_genres(db, data.genres)

        manga = await self.manga_repo.create(db, {
            "title": data.title,
            "slug": slug,
            "description": data.description,
            "status": data.status,
        })
        manga.genres = genres

        await db.flush()
        return manga
```

### Transaction Boundaries

A transaction is a unit of work that either fully succeeds or fully fails. If creating the manga succeeds but linking genres fails, you don't want a manga record with no genres in the database. The entire operation should roll back.

In our architecture, the transaction boundary is managed by `get_db()` — the dependency you created in Chapter 8. It commits on success and rolls back on exception. This means all the work a service method does within a single request shares one transaction.

The key insight: don't commit inside the service or repository. Let the dependency handle it. Service methods call `flush()` to send SQL to the database (for getting generated IDs and defaults) but never call `commit()`. The commit happens once, at the end, in `get_db()`.

```python
# In get_db:
async with async_session_factory() as session:
    try:
        yield session
        await session.commit()    # One commit for everything
    except Exception:
        await session.rollback()  # Roll back everything
        raise
```

This is the "unit of work" pattern. All changes in a request are accumulated and committed atomically.

### Slug Generation

A slug is a URL-friendly version of a string. "Attack on Titan" becomes "attack-on-titan". Slugs are used in URLs (`/manga/attack-on-titan`) because they're human-readable and SEO-friendly compared to UUIDs.

Generating a good slug involves:
1. Converting to lowercase
2. Replacing spaces and special characters with hyphens
3. Removing non-alphanumeric characters (except hyphens)
4. Collapsing multiple hyphens into one
5. Stripping leading/trailing hyphens

```python
import re
import unicodedata

def generate_slug(text: str) -> str:
    # Normalize unicode characters
    text = unicodedata.normalize("NFKD", text)
    # Convert to lowercase
    text = text.lower()
    # Replace non-alphanumeric with hyphens
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")
```

Slug uniqueness is a business rule — two different manga can't have the same slug. If "One Piece" is taken, a service might append a number: "one-piece-2". This logic belongs in the service, not the repository (which just checks if a slug exists).

## Your Task

### Step 1: Create a genre repository

Create `app/repositories/genre.py` with `GenreRepository(BaseRepository[Genre])` that has a `get_by_slug(db, slug)` and `get_by_name(db, name)` method.

### Step 2: Create a slug utility

Create `app/utils/__init__.py` and `app/utils/slug.py` with a `generate_slug(text: str) -> str` function. It should handle Unicode, spaces, special characters, and produce clean URL-friendly slugs.

### Step 3: Create the manga service

Create `app/services/__init__.py` and `app/services/manga.py` with a `MangaService` class that accepts repository instances (or the database session, and creates repos internally). Implement:

- `create_manga(db, data: MangaCreate) -> Manga`:
  1. Generate slug from title
  2. Check slug uniqueness (raise `AlreadyExistsException` with a 409 status if taken)
  3. Resolve genres: for each genre string in the input, find existing genre by name or create a new one (generating its slug too)
  4. Create the manga via the repository
  5. Attach the resolved genres to the manga
  6. Flush and refresh, then return

- `get_manga(db, manga_id: UUID) -> Manga`:
  1. Fetch from repository
  2. Raise `NotFoundException` if not found
  3. Return

- `list_manga(db, filters, pagination) -> list[Manga]`:
  1. Apply filters using repository methods
  2. Return results

### Step 4: Refactor endpoints to use the service

Update `app/api/v1/endpoints/manga.py`:
- Endpoints should instantiate the `MangaService` (passing the db session)
- Endpoints call service methods, not repository methods directly
- Endpoints become very thin — just parse request, call service, return response

### Step 5: Update schemas

You may need to update your `MangaResponse` schema to include nested genre data (list of genre names or genre objects). Create a `GenreResponse` schema if needed.

### Step 6: Test the full flow

1. POST a manga with genres `["Action", "Adventure"]` — both genres should be created in the genre table
2. POST another manga with genres `["Action", "Fantasy"]` — "Action" should be reused (not duplicated), "Fantasy" should be created
3. POST a manga with the same title — should return 409 (duplicate slug)
4. GET the manga list — should show manga with their genres

## Expected Outcome
- Creating a manga auto-generates a slug from the title
- Genres are auto-resolved: created if new, reused if existing
- Duplicate slugs return 409 Conflict with your custom error format
- Endpoints are thin wrappers that delegate to the service
- The service coordinates multiple repository calls within a single transaction
- All genres in the genre table are unique (no duplicates)

## Hints
- To attach genres to a manga, you can simply assign a list of Genre objects to `manga.genres`. SQLAlchemy handles the junction table inserts.
- `db.flush()` is needed after creating the manga and before accessing `manga.id` (to get the database-generated UUID).
- When resolving genres, consider using a batch approach: fetch all existing genres matching the input names in one query, then create only the missing ones.
- For slug uniqueness, the simplest approach is try/handle. A more robust approach is to query first, and if the slug exists, append a number.

## What I'll Look For In Review
- Service layer exists and contains ALL business logic (slug generation, uniqueness checks, genre resolution)
- Endpoints are thin — no business logic in endpoint functions
- Slug generation handles edge cases (Unicode, special characters, consecutive hyphens)
- Genre resolution is efficient (doesn't create duplicates, handles mixed existing/new genres)
- `AlreadyExistsException` (409) is raised for duplicate slugs, not a generic 400 or 500
