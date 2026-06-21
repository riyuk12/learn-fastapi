# Chapter 11 — Many-to-Many: Manga-Genre & Author Model

## Concepts You'll Learn
- Association (junction) tables for many-to-many relationships
- SQLAlchemy `relationship()` with `secondary` and `back_populates`
- The Author model with a role-based association
- Eager vs lazy loading introduction

## Concept Deep Dive

### Many-to-Many Relationships

A manga can have multiple genres (action, adventure, fantasy). A genre applies to multiple manga. This is a many-to-many relationship, and relational databases handle it with a junction table (also called an association table or bridge table).

The junction table has no model class of its own — it's just a table with two foreign key columns, each pointing to one side of the relationship:

```python
from sqlalchemy import Table, Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

manga_genre = Table(
    "manga_genre",
    Base.metadata,
    Column("manga_id", UUID(as_uuid=True), ForeignKey("manga.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", UUID(as_uuid=True), ForeignKey("genre.id", ondelete="CASCADE"), primary_key=True),
)
```

This table says: "manga X is associated with genre Y." The composite primary key (both columns together) prevents duplicate associations. The `ondelete="CASCADE"` means if a manga is deleted, its entries in `manga_genre` are automatically removed.

Why a separate table? Because you can't store a list in a relational column. (PostgreSQL has array types, but they can't enforce foreign key constraints or be efficiently queried for joins.) The junction table is the relational way to say "these two things are related."

### relationship() with secondary and back_populates

SQLAlchemy's `relationship()` lets you navigate between related objects in Python without writing JOIN queries manually. For many-to-many, you use the `secondary` parameter to specify the junction table:

```python
class Manga(Base):
    __tablename__ = "manga"
    # ... columns ...
    genres: Mapped[list["Genre"]] = relationship(
        secondary=manga_genre,
        back_populates="mangas",
    )

class Genre(Base):
    __tablename__ = "genre"
    # ... columns ...
    mangas: Mapped[list["Manga"]] = relationship(
        secondary=manga_genre,
        back_populates="genres",
    )
```

Now you can write `manga.genres` to get all genres for a manga, and `genre.mangas` to get all manga in a genre. SQLAlchemy generates the JOIN queries behind the scenes. `back_populates` keeps both sides in sync: if you add a genre to `manga.genres`, the manga also appears in `genre.mangas`.

### Association Tables with Extra Data

Sometimes the junction table needs more than just two foreign keys. For the manga-author relationship, you want to record the author's role: are they the writer, the artist, or both? This is an "association object" pattern — the junction table has its own columns beyond the foreign keys.

For simple extra columns, you can still use `Table`:

```python
manga_author = Table(
    "manga_author",
    Base.metadata,
    Column("manga_id", UUID(as_uuid=True), ForeignKey("manga.id", ondelete="CASCADE"), primary_key=True),
    Column("author_id", UUID(as_uuid=True), ForeignKey("author.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(20), nullable=False, default="author"),
)
```

However, if you need to query or manipulate the association data (e.g., "find all artists for this manga"), you might want a full model class for the association instead. For now, the `Table` approach works. You can access the extra data through explicit queries when needed.

### Eager vs Lazy Loading

By default, SQLAlchemy uses "lazy loading" for relationships. When you access `manga.genres`, it fires a new SQL query to fetch the genres. This is convenient but dangerous: if you have 20 manga and access `.genres` on each, you get 20 extra queries (the infamous N+1 problem).

The alternative is "eager loading," which fetches related data in the same query (or a coordinated second query). You'll explore this in depth in Chapter 14, but it's important to understand the concept now because it influences how you design your models and queries.

For now, know that relationships default to lazy, and you'll explicitly ask for eager loading when you need it.

## Your Task

### Step 1: Create the Author model

Create `app/models/author.py` with:

- `id`: UUID primary key
- `name`: String(200), not nullable
- `slug`: String(200), unique, indexed
- `bio`: Text, nullable
- `created_at`: DateTime with server default

### Step 2: Create the manga_genre association table

In `app/models/manga.py` (or a separate `app/models/associations.py`), define the `manga_genre` junction table with `manga_id` and `genre_id` foreign keys. Use `ondelete="CASCADE"` on both foreign keys.

### Step 3: Create the manga_author association table

Define the `manga_author` junction table with:
- `manga_id`: FK to manga.id
- `author_id`: FK to author.id
- `role`: String column with values like "author", "artist", or "both"

Make the primary key composite: `(manga_id, author_id)`.

### Step 4: Add relationships to models

- On `Manga`: add `genres` relationship (many-to-many via `manga_genre`) and `authors` relationship (many-to-many via `manga_author`)
- On `Genre`: add `mangas` relationship (back-populates manga's `genres`)
- On `Author`: add `mangas` relationship (back-populates manga's `authors`)

Use `back_populates` on both sides of each relationship.

### Step 5: Update model imports

In `app/models/__init__.py`, import the Author model and any association tables so Alembic can see them.

### Step 6: Generate and run migration

```bash
alembic revision --autogenerate -m "add author model and association tables"
alembic upgrade head
```

Review the migration before running it. It should create the `author` table, the `manga_genre` table, and the `manga_author` table.

### Step 7: Create a seed script

Create `scripts/seed.py` — a standalone Python script that:

1. Imports your async engine/session
2. Creates 5 genres: Action, Adventure, Fantasy, Comedy, Drama
3. Creates 3 authors with names and slugs
4. Commits them to the database

This script should be runnable with `python scripts/seed.py` from the project root. You'll need to handle the async event loop (use `asyncio.run()`) and import your database setup.

### Step 8: Verify relationships

After seeding, write a temporary test in your lifespan or a script that:
- Fetches a genre and prints `genre.name`
- This proves the ORM models work with the database

## Expected Outcome
- Author model exists in `app/models/author.py`
- `manga_genre` and `manga_author` association tables are defined
- Relationships work bidirectionally: `manga.genres` and `genre.mangas`
- Migration creates all new tables and association tables
- Running `scripts/seed.py` populates the database with 5 genres and 3 authors
- Querying the database shows the seeded data

## Hints
- Remember: both sides of a `relationship()` need `back_populates` pointing to the other side's attribute name.
- For the association tables, use `Table(...)` (the SQLAlchemy core construct), not a `class` that inherits from `Base`. These don't need to be ORM models.
- In the seed script, you'll need to set up the path so Python can find your `app` package: `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`.
- When creating the seed script, use `async_session_factory()` from your `db/session.py` and `session.add_all([...])` to batch insert.

## What I'll Look For In Review
- Association tables use composite primary keys (both FKs together)
- `ondelete="CASCADE"` on foreign keys in association tables
- `relationship()` uses `secondary` for many-to-many and `back_populates` on both sides
- `manga_author` has a `role` column to distinguish author/artist/both
- Seed script is runnable and idempotent (running it twice doesn't crash or duplicate data)
