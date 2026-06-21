# Chapter 8 — PostgreSQL Setup & SQLAlchemy Async Engine

## Concepts You'll Learn
- PostgreSQL setup (local installation or Docker)
- Connection strings and what each part means
- SQLAlchemy 2.0 async engine and session factory
- The `get_db` dependency pattern for database sessions

## Concept Deep Dive

### PostgreSQL

Up until now, you've been using an in-memory Python list as your "database." That works for prototyping, but it has fatal flaws: data disappears when the server restarts, there's no concurrency control, no querying language, no indexing, and no durability. It's time to introduce a real database.

PostgreSQL (often called "Postgres") is an open-source relational database that's been in active development since 1986. It's the go-to choice for most Python web applications because it's rock-solid, feature-rich (JSON columns, full-text search, array types, etc.), and has excellent async driver support.

You have two options for running PostgreSQL locally:

**Option A: Docker (recommended).** If you have Docker installed, this is the fastest path:

```bash
docker run --name mangashelf-db \
  -e POSTGRES_USER=mangashelf \
  -e POSTGRES_PASSWORD=mangashelf \
  -e POSTGRES_DB=mangashelf \
  -p 5432:5432 \
  -d postgres:16
```

This creates a container running PostgreSQL 16 with a database called `mangashelf`, accessible on port 5432. The data lives inside the container — add a volume if you want persistence across container restarts.

**Option B: Native installation.** On macOS, `brew install postgresql@16` and `brew services start postgresql@16`. On Ubuntu, `sudo apt install postgresql`. Then create a database with `createdb mangashelf`.

Either way, you end up with a PostgreSQL server running on `localhost:5432` with a database named `mangashelf`.

### Connection Strings

A database URL (also called a connection string) encodes everything needed to connect:

```
postgresql+asyncpg://mangashelf:mangashelf@localhost:5432/mangashelf
```

Breaking it down:
- `postgresql` — the database type
- `+asyncpg` — the async driver to use (asyncpg is the fastest async PostgreSQL driver for Python)
- `mangashelf:mangashelf` — username:password
- `@localhost:5432` — host:port
- `/mangashelf` — database name

The `+asyncpg` part is critical. Without it, SQLAlchemy uses the synchronous `psycopg2` driver, which would block your async FastAPI application. `asyncpg` is a pure-Python async driver built specifically for PostgreSQL and asyncio.

### SQLAlchemy 2.0 Async Engine

SQLAlchemy is Python's most popular ORM (Object-Relational Mapper) and database toolkit. Version 2.0 brought a completely new async-native API. The async engine is the foundational object — it manages the connection pool and talks to PostgreSQL.

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(
    "postgresql+asyncpg://mangashelf:mangashelf@localhost:5432/mangashelf",
    echo=False,  # Set True to log all SQL queries
    pool_size=5,
    max_overflow=10,
)
```

The engine doesn't open connections immediately. It creates a connection pool — a set of reusable database connections. `pool_size=5` means it keeps 5 connections ready. `max_overflow=10` means it can create up to 10 additional connections under load (15 total). This pooling is essential for performance: opening a new TCP connection to PostgreSQL for every request would be extremely slow.

The session factory creates sessions — the object you actually use to run queries:

```python
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

`expire_on_commit=False` is important for async. Without it, accessing attributes on ORM objects after a commit would trigger a lazy load, which requires a synchronous database call — and that would fail in an async context.

### The get_db Dependency

FastAPI's dependency injection system is perfect for managing database sessions. You create a dependency that yields a session, and the framework ensures it's properly closed after each request:

```python
from typing import AsyncGenerator

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

This pattern uses `async with` to ensure the session is closed when done, and wraps everything in a try/except that commits on success and rolls back on failure. Your endpoints then receive a session via dependency injection:

```python
@router.get("/manga")
async def list_manga(db: AsyncSession = Depends(get_db)):
    # Use db to query the database
    ...
```

Each request gets its own session, its own transaction, and automatic cleanup. No manual connection management needed.

## Your Task

### Step 1: Set up PostgreSQL

Choose either Docker or native installation and get PostgreSQL running. Create a database called `mangashelf`. Verify you can connect to it (using `psql`, a GUI tool like pgAdmin, or the `docker exec` trick):

```bash
# Docker
docker exec -it mangashelf-db psql -U mangashelf -d mangashelf -c "SELECT 1;"

# Native
psql -d mangashelf -c "SELECT 1;"
```

### Step 2: Install Python dependencies

Install `sqlalchemy[asyncio]` and `asyncpg`. Update `requirements.txt`.

### Step 3: Update settings

In `app/core/config.py`, ensure `DATABASE_URL` is properly configured. Update your `.env` with the correct connection string for your local PostgreSQL setup.

### Step 4: Create the database session module

Create `app/db/__init__.py` and `app/db/session.py`. In `session.py`:

- Create an async engine using `create_async_engine` with your settings' `DATABASE_URL`
- Create an `async_sessionmaker` bound to that engine
- Create a `get_db` async generator dependency that yields sessions with commit/rollback handling

Consider creating a function (e.g., `init_db(url: str)`) that initializes the engine and session factory, rather than creating them at module import time. This makes testing easier and lets you configure the engine from the lifespan event.

### Step 5: Test the connection in lifespan

Update your lifespan event in `app/main.py` to test the database connection on startup. A simple approach: acquire a session, run `SELECT 1`, and log success. If it fails, log the error. On shutdown, dispose of the engine to close all connections cleanly.

```python
# Conceptual example — adapt to your structure
async with engine.begin() as conn:
    await conn.execute(text("SELECT 1"))
logger.info("Database connection verified")
```

### Step 6: Verify

Start the app. You should see a log line confirming the database connection. If PostgreSQL isn't running, the app should log an error (but can still start — you have no endpoints using the DB yet).

## Expected Outcome
- PostgreSQL is running and accessible (Docker or native)
- `app/db/session.py` exports an async engine, session factory, and `get_db` dependency
- The app connects to PostgreSQL on startup and logs "Database connection verified" (or similar)
- Stopping the app disposes of the engine cleanly
- `requirements.txt` includes `sqlalchemy[asyncio]` and `asyncpg`

## Hints
- If you get `ModuleNotFoundError: No module named 'asyncpg'`, you forgot to install it. The `sqlalchemy[asyncio]` extra doesn't include `asyncpg` — you need both.
- The `text()` function from `sqlalchemy` is needed to run raw SQL strings: `from sqlalchemy import text`.
- If the connection fails, double-check: is PostgreSQL running? Is the port correct? Are the username/password right? Can you connect with `psql` using the same credentials?
- `expire_on_commit=False` on the session factory prevents lazy-loading issues in async code. Always set it.

## What I'll Look For In Review
- Async engine created with `create_async_engine` (not the sync version)
- Session factory uses `async_sessionmaker` with `expire_on_commit=False`
- `get_db` is an async generator with proper commit/rollback handling
- Database connection is verified during startup (lifespan event)
- Engine is properly disposed during shutdown
