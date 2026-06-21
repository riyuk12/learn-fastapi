# Chapter 12 — Repository Pattern: Manga CRUD

## Concepts You'll Learn
- The Repository (DAO) pattern and why it exists
- Separating database access from business logic
- Async session usage with SQLAlchemy 2.0's `select()` API
- Building a generic base repository

## Concept Deep Dive

### The Repository Pattern

The repository pattern creates an abstraction layer between your business logic and your database. Instead of writing SQL queries directly in your endpoint functions, you call methods like `manga_repo.get_by_id(id)` or `manga_repo.create(data)`. The repository is the only code that knows how to talk to the database.

Why bother with this indirection? Three reasons:

1. **Testability**: You can mock the repository in tests without needing a database.
2. **Single Responsibility**: Endpoints handle HTTP concerns (parsing requests, forming responses). Repositories handle data access. Each layer has one job.
3. **Reusability**: The same `get_by_id()` method can be called from an endpoint, a background task, or a CLI command. Without the repository, you'd duplicate query logic everywhere.

Think of it like a library (the building, not the software kind). You don't go into the stacks and search the shelves yourself. You ask the librarian (repository) to find a book by title, by author, or by genre. The librarian knows the organizational system; you just know what you want.

### Separating Database Access from Business Logic

Consider this endpoint without the repository pattern:

```python
@router.post("/")
async def create_manga(manga: MangaCreate, db: AsyncSession = Depends(get_db)):
    slug = generate_slug(manga.title)
    existing = await db.execute(select(Manga).where(Manga.slug == slug))
    if existing.scalar_one_or_none():
        raise AlreadyExistsException("Manga", "slug")
    db_manga = Manga(**manga.model_dump(), slug=slug)
    db.add(db_manga)
    await db.flush()
    return db_manga
```

This endpoint is doing HTTP handling, business logic (slug generation, uniqueness check), AND database operations — all tangled together. With the repository pattern:

```python
@router.post("/")
async def create_manga(manga: MangaCreate, db: AsyncSession = Depends(get_db)):
    service = MangaService(MangaRepository(db))
    return await service.create_manga(manga)
```

The endpoint is a thin wrapper. The service handles business logic. The repository handles database operations. Each layer can be modified, tested, and reasoned about independently.

### Async Session Usage and select()

SQLAlchemy 2.0 uses the `select()` construct for queries instead of the older `session.query()` pattern. The async session works with `await`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> Manga | None:
    result = await db.execute(select(Manga).where(Manga.id == id))
    return result.scalar_one_or_none()

async def get_multi(self, db: AsyncSession, skip: int = 0, limit: int = 20) -> list[Manga]:
    result = await db.execute(
        select(Manga).offset(skip).limit(limit).order_by(Manga.created_at.desc())
    )
    return list(result.scalars().all())
```

Key methods on the result:
- `scalar_one_or_none()` — returns one object or `None` (errors if multiple rows match)
- `scalar_one()` — returns one object (errors if zero or multiple)
- `scalars().all()` — returns a list of all matching objects
- `scalars().first()` — returns the first match or `None`

For creating objects:
```python
async def create(self, db: AsyncSession, obj_data: dict) -> Manga:
    db_obj = Manga(**obj_data)
    db.add(db_obj)
    await db.flush()  # Sends the INSERT to the DB, assigns the ID
    await db.refresh(db_obj)  # Reloads from DB (gets server defaults like created_at)
    return db_obj
```

`flush()` sends the SQL but doesn't commit. `refresh()` reloads the object from the database to pick up server-side defaults. The actual commit happens in the `get_db` dependency's context manager.

### Building a Generic Base Repository

Most repositories share the same basic operations: get by ID, list with pagination, create, update, delete. A generic base repository avoids duplicating this code:

```python
from typing import TypeVar, Generic, Type

ModelType = TypeVar("ModelType")

class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, db: AsyncSession, id: uuid.UUID) -> ModelType | None:
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, obj_data: dict) -> ModelType:
        db_obj = self.model(**obj_data)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj
```

Then `MangaRepository(BaseRepository[Manga])` inherits all the basic operations and adds manga-specific ones like `get_by_slug()` and `filter_by_genre()`.

## Your Task

### Step 1: Create the base repository

Create `app/repositories/__init__.py` and `app/repositories/base.py`. Define a `BaseRepository` generic class with these async methods:

- `get(db, id)` — get one record by UUID primary key
- `get_multi(db, skip, limit)` — get a paginated list
- `create(db, obj_data: dict)` — create a new record
- `update(db, db_obj, update_data: dict)` — update an existing record
- `delete(db, db_obj)` — delete a record

The class should be generic over the model type, accepting the model class in `__init__`.

### Step 2: Create the manga repository

Create `app/repositories/manga.py` with `MangaRepository` that extends `BaseRepository[Manga]`. Add manga-specific methods:

- `get_by_slug(db, slug)` — find a manga by its slug
- `filter_by_status(db, status, skip, limit)` — filter by status enum
- `filter_by_genre(db, genre_slug, skip, limit)` — filter by genre (requires a join through the association table)

### Step 3: Refactor the manga list endpoint

Update `GET /api/v1/manga` to:
1. Accept the `AsyncSession` via `Depends(get_db)`
2. Create a `MangaRepository` instance
3. Call the appropriate repository methods based on query parameters
4. Return the results

Remove the in-memory fake data. Everything comes from PostgreSQL now.

### Step 4: Refactor the manga detail endpoint

Update `GET /api/v1/manga/{manga_id}` to use the repository's `get()` method. If not found, raise your `NotFoundException`.

### Step 5: Add a real create endpoint

Update `POST /api/v1/manga` to:
1. Convert the `MangaCreate` Pydantic model to a dict
2. Call `manga_repo.create(db, data)`
3. Return the created manga as `MangaResponse`

For now, don't worry about slug generation or genre linking — that's the service layer's job in Chapter 13. Just create the manga with the basic fields.

### Step 6: Verify with real data

Use the Swagger UI or curl to:
- POST a new manga
- GET the list (should include your newly created manga)
- GET by ID
- Verify the data persists across server restarts

## Expected Outcome
- `BaseRepository` provides generic CRUD operations usable by any model
- `MangaRepository` extends it with manga-specific queries
- All manga endpoints use the repository instead of in-memory data
- `POST /api/v1/manga` persists to PostgreSQL (data survives server restart)
- `GET /api/v1/manga` reads from PostgreSQL
- `GET /api/v1/manga/{id}` returns a real database record or 404

## Hints
- Remember to `await db.flush()` after `db.add()` to send the INSERT to the database and get the generated ID.
- `await db.refresh(db_obj)` reloads the object from the database, picking up server-side defaults like `created_at`.
- For the `filter_by_genre` method, you'll need to join through the `manga_genre` association table: `select(Manga).join(manga_genre).join(Genre).where(Genre.slug == genre_slug)`.
- If your Pydantic response model has `from_attributes=True` (ConfigDict), it can serialize SQLAlchemy model instances directly.

## What I'll Look For In Review
- `BaseRepository` is truly generic — it works with any model, not just Manga
- `MangaRepository` inherits from `BaseRepository` and adds specific methods
- Endpoints are thin: they receive the request, call the repository, and return the response
- No raw SQL or `db.execute()` in endpoint functions — all database access goes through repositories
- Proper error handling: nonexistent IDs raise `NotFoundException`
