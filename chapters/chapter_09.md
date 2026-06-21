# Chapter 9 — First Models: Manga & Genre

## Concepts You'll Learn
- SQLAlchemy ORM models and declarative mapping
- Column types: UUID, String, Enum, Text, DateTime
- Database indexes and why they matter
- The `DeclarativeBase` pattern in SQLAlchemy 2.0

## Concept Deep Dive

### SQLAlchemy ORM Models

An ORM (Object-Relational Mapper) lets you interact with database tables using Python classes instead of raw SQL. Each class maps to a table, each attribute maps to a column, and each instance maps to a row. Instead of writing `INSERT INTO manga (title, status) VALUES ('One Piece', 'ongoing')`, you write `manga = Manga(title="One Piece", status="ongoing")` and let the ORM generate the SQL.

In SQLAlchemy 2.0, you define models using `DeclarativeBase` and `Mapped` annotations:

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text
import uuid
from datetime import datetime

class Base(DeclarativeBase):
    pass

class Manga(Base):
    __tablename__ = "manga"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
```

The `Base` class is the foundation — every model inherits from it. SQLAlchemy inspects `Base` and its subclasses to understand your database schema. `__tablename__` explicitly sets the table name (without it, SQLAlchemy would auto-generate one from the class name).

`Mapped[str]` is a type annotation that tells both Python's type checker and SQLAlchemy what type this column holds. `mapped_column()` configures the column — its SQL type, whether it's nullable, default values, and more.

### Column Types

Choosing the right column type matters for storage efficiency, query performance, and data integrity:

- **UUID**: `mapped_column(UUID(as_uuid=True))` — for primary keys. UUIDs are globally unique, don't reveal row count (unlike auto-incrementing integers), and are safe for distributed systems. Import from `sqlalchemy.dialects.postgresql import UUID`.

- **String(n)**: fixed-max-length text. Use for fields like `title` (200 chars), `slug` (100 chars). PostgreSQL enforces the length limit.

- **Text**: unlimited-length text. Use for `description` and other long-form content. There's no performance difference between `Text` and `String` in PostgreSQL, but `String(n)` documents your intent.

- **Enum**: maps to a PostgreSQL enum type. Use for fields with a fixed set of values like `status`. You can use Python's `enum.Enum` directly:

```python
import enum

class MangaStatusEnum(str, enum.Enum):
    ONGOING = "ongoing"
    COMPLETED = "completed"
    HIATUS = "hiatus"
    CANCELLED = "cancelled"

status: Mapped[MangaStatusEnum] = mapped_column(
    SQLAlchemyEnum(MangaStatusEnum, name="manga_status", create_constraint=True),
    nullable=False,
)
```

- **DateTime**: for timestamps. Always store in UTC. Use `server_default=func.now()` for database-generated timestamps:

```python
from sqlalchemy import func

created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    nullable=False,
)
```

`server_default` means PostgreSQL generates the timestamp, not Python. This is important because in a distributed setup, different app servers might have slightly different clocks. The database server is the single source of truth for time.

### Database Indexes

An index is like the index at the back of a textbook. Without it, finding all manga with `status = 'ongoing'` requires scanning every row in the table (a "full table scan"). With an index on `status`, PostgreSQL can jump directly to the matching rows.

```python
from sqlalchemy import Index

class Manga(Base):
    __tablename__ = "manga"

    # Column-level index
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    # Table-level index (useful for composite indexes)
    __table_args__ = (
        Index("ix_manga_status", "status"),
    )
```

Rules of thumb for indexing:
- Always index columns you filter or sort by (`status`, `slug`, `created_at`)
- Always index foreign keys (SQLAlchemy doesn't do this automatically)
- Unique constraints automatically create an index
- Don't index everything — each index slows down writes and uses storage

### DeclarativeBase and Model Organization

In SQLAlchemy 2.0, `DeclarativeBase` replaces the older `declarative_base()` function. Define it once and share it across all your models:

```python
# app/db/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

Then every model file imports `Base`:

```python
# app/models/manga.py
from app.db.base import Base

class Manga(Base):
    ...
```

It's crucial that all models are imported before you run migrations or create tables. A common pattern is to have an `app/models/__init__.py` that imports all models, and then import that module in your Alembic configuration.

## Your Task

### Step 1: Create the Base class

Create `app/db/base.py` with a `DeclarativeBase` subclass called `Base`. Consider adding common columns (like `id`, `created_at`, `updated_at`) as a mixin or on the Base class itself — but this is optional.

### Step 2: Create the Manga model

Create `app/models/__init__.py` and `app/models/manga.py`. Define a `Manga` model with:

- `id`: UUID primary key, defaults to `uuid4`
- `title`: String(200), not nullable
- `slug`: String(100), unique, indexed — this will be a URL-friendly version of the title (e.g., "One Piece" -> "one-piece")
- `description`: Text, nullable
- `status`: Enum (ongoing, completed, hiatus, cancelled), not nullable, default "ongoing"
- `cover_image_url`: String(500), nullable
- `created_at`: DateTime with timezone, server default to `now()`
- `updated_at`: DateTime with timezone, server default to `now()`, updates on every modification

For `updated_at`, use `onupdate=func.now()` in addition to `server_default` so it auto-updates when the row changes.

### Step 3: Create the Genre model

Create `app/models/genre.py` with:

- `id`: UUID primary key
- `name`: String(50), not nullable, unique
- `slug`: String(50), not nullable, unique, indexed

### Step 4: Add indexes

Add appropriate indexes:
- `slug` columns should be unique + indexed (for lookups)
- `status` on Manga should be indexed (for filtering)
- `created_at` on Manga should be indexed (for sorting)

### Step 5: Import all models

In `app/models/__init__.py`, import the Manga and Genre models. This ensures they're registered with SQLAlchemy's metadata when the package is imported.

### Step 6: Verify (no tables yet)

At this point, you should be able to start the app without errors. The models are defined but no tables exist in the database yet — that's what Alembic will do in the next chapter.

To verify your models are correctly defined, you can add a temporary line in your lifespan that prints `Base.metadata.tables.keys()` — it should show your table names.

## Expected Outcome
- `app/models/manga.py` defines a `Manga` model mapped to a `"manga"` table
- `app/models/genre.py` defines a `Genre` model mapped to a `"genre"` table
- Both models use UUID primary keys with `uuid4` defaults
- `slug` columns are unique and indexed
- `created_at` and `updated_at` use server-side defaults
- `app/models/__init__.py` imports both models
- The app starts without errors (models defined, tables not yet created)

## Hints
- For the PostgreSQL UUID type, use `from sqlalchemy.dialects.postgresql import UUID` and `mapped_column(UUID(as_uuid=True), ...)`.
- For the enum, you need `from sqlalchemy import Enum as SQLAlchemyEnum` to avoid confusion with Python's `enum.Enum`.
- `server_default=func.now()` requires `from sqlalchemy import func`.
- The `onupdate` parameter on `mapped_column` triggers on SQLAlchemy-level updates, not raw SQL. For the most reliable auto-updating, you may need a database trigger later, but `onupdate=func.now()` works for ORM operations.

## What I'll Look For In Review
- Models use SQLAlchemy 2.0 style (`Mapped`, `mapped_column`, `DeclarativeBase`)
- UUID primary keys with `default=uuid.uuid4` (note: pass the function, not the result)
- Appropriate column types and lengths (String(200) for title, Text for description)
- Indexes on columns that will be frequently queried (slug, status, created_at)
- Clean separation: `Base` in `db/base.py`, models in `models/` directory
