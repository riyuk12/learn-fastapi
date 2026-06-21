# Chapter 22 — Chapter & Page Models

## Concepts You'll Learn
- One-to-many relationships in SQLAlchemy
- Ordering fields and how to model sequential content
- Composite unique constraints for data integrity
- Data modeling for hierarchical content structures

## Concept Deep Dive

### One-to-Many Relationships

A manga has many chapters. A chapter has many pages. These are one-to-many relationships — one parent record has multiple child records. Unlike many-to-many (which needs a junction table), one-to-many is modeled with a foreign key on the child pointing to the parent.

```python
class Chapter(Base):
    __tablename__ = "chapter"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    manga_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manga.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(200))

    # Relationship back to parent
    manga: Mapped["Manga"] = relationship(back_populates="chapters")
```

And on the parent side:

```python
class Manga(Base):
    # ... existing columns ...
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="manga")
```

The foreign key (`manga_id`) is on the Chapter table because a chapter belongs to one manga. The relationship declarations let you navigate: `manga.chapters` gives you all chapters, and `chapter.manga` gives you the parent manga.

`ondelete="CASCADE"` on the foreign key means: when a manga is deleted from the database, PostgreSQL automatically deletes all its chapters. This is database-level cascading. You can also configure SQLAlchemy-level cascading, but database-level is more reliable (it works even for raw SQL or other applications accessing the database).

### Ordering Fields

Chapters in a manga have a specific order: Chapter 1, Chapter 2, Chapter 2.5 (special), Chapter 3, etc. Pages within a chapter have a specific order: page 1, page 2, page 3.

Using `DECIMAL` (or `NUMERIC`) for chapter numbers instead of `INTEGER` handles the common case of "half chapters" in manga. Chapter 13.5 is a thing in many series — a side story or bonus chapter inserted between Chapter 13 and Chapter 14.

```python
from sqlalchemy import Numeric

chapter_number: Mapped[Decimal] = mapped_column(
    Numeric(precision=6, scale=1),  # Up to 99999.9
    nullable=False,
)
```

`Numeric(precision=6, scale=1)` means 6 total digits with 1 after the decimal point. This allows values like `1.0`, `2.5`, `100.0`. For page numbers, a plain `INTEGER` is fine — you don't have "page 2.5."

When querying, always order by the ordering field:

```python
stmt = select(Chapter).where(Chapter.manga_id == manga_id).order_by(Chapter.chapter_number)
```

### Composite Unique Constraints

A unique constraint on a single column says "no two rows can have the same value in this column." A composite unique constraint says "no two rows can have the same combination of values across these columns."

For chapters: the combination of `(manga_id, chapter_number)` must be unique. Manga A can have Chapter 1, and Manga B can also have Chapter 1, but Manga A cannot have two Chapter 1s.

For pages: the combination of `(chapter_id, page_number)` must be unique. Each chapter has exactly one page 1, one page 2, etc.

```python
from sqlalchemy import UniqueConstraint

class Chapter(Base):
    __tablename__ = "chapter"
    # ... columns ...

    __table_args__ = (
        UniqueConstraint("manga_id", "chapter_number", name="uq_chapter_manga_number"),
    )

class Page(Base):
    __tablename__ = "page"
    # ... columns ...

    __table_args__ = (
        UniqueConstraint("chapter_id", "page_number", name="uq_page_chapter_number"),
    )
```

These constraints are enforced at the database level. If your application code has a bug and tries to insert a duplicate, PostgreSQL will reject it with an `IntegrityError`. This is your safety net — the database is the last line of defense for data integrity.

### Data Modeling for Hierarchical Content

MangaShelf's content hierarchy is: **Manga → Chapter → Page**. This is a three-level hierarchy, and each level has specific attributes:

**Manga**: metadata (title, description, genres, authors, cover image)
**Chapter**: ordering (chapter number), metadata (title, page count)
**Page**: ordering (page number), content (image URL), display hints (width, height, blurhash)

The `blurhash` field on Page deserves explanation. BlurHash is a compact representation of a placeholder for an image. When a reader is loading page images, the UI can show a blurred placeholder (generated from the blurhash string) instead of an empty space or spinner. This is a common UX pattern in image-heavy applications.

```python
class Page(Base):
    __tablename__ = "page"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapter.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    blurhash: Mapped[str | None] = mapped_column(String(100), nullable=True)
```

Width and height are stored to help the frontend lay out the page before the image loads (preventing layout shift — a jarring UX where content jumps around as images load).

## Your Task

### Step 1: Create the Chapter model

Create `app/models/chapter.py` with:

- `id`: UUID primary key
- `manga_id`: UUID foreign key to `manga.id` with `ondelete="CASCADE"`
- `chapter_number`: Decimal/Numeric (precision 6, scale 1), not nullable
- `title`: String(200), nullable (not all chapters have titles)
- `page_count`: Integer, default 0 (will be updated as pages are added)
- `created_at`: DateTime with timezone, server default

Add a `UniqueConstraint` on `(manga_id, chapter_number)`.

Add relationships:
- `manga`: relationship back to Manga
- `pages`: relationship to Page (one-to-many)

### Step 2: Create the Page model

Create `app/models/page.py` with:

- `id`: UUID primary key
- `chapter_id`: UUID foreign key to `chapter.id` with `ondelete="CASCADE"`
- `page_number`: Integer, not nullable
- `image_url`: String(500), not nullable
- `width`: Integer, nullable
- `height`: Integer, nullable
- `blurhash`: String(100), nullable

Add a `UniqueConstraint` on `(chapter_id, page_number)`.

Add a relationship back to Chapter.

### Step 3: Add chapters relationship to Manga

In `app/models/manga.py`, add a `chapters` relationship: `Mapped[list["Chapter"]]` with `back_populates="manga"`. Consider adding `cascade="all, delete-orphan"` on the SQLAlchemy relationship (in addition to the database-level `ondelete="CASCADE"`) for consistent behavior when deleting via ORM.

### Step 4: Add pages relationship to Chapter

On the Chapter model, add a `pages` relationship to Page with `back_populates="chapter"` and `cascade="all, delete-orphan"`.

### Step 5: Add indexes

Add indexes for common query patterns:
- `manga_id` on Chapter (for "get all chapters of this manga")
- `chapter_id` on Page (for "get all pages of this chapter")
- `chapter_number` on Chapter (for ordering)
- `page_number` on Page (for ordering)

Foreign key columns should generally be indexed. PostgreSQL does NOT automatically index foreign keys (unlike some other databases).

### Step 6: Update model imports and generate migration

Update `app/models/__init__.py` to import Chapter and Page. Generate and apply the migration:

```bash
alembic revision --autogenerate -m "create chapter and page tables"
alembic upgrade head
```

### Step 7: Verify constraints

After applying the migration, verify the constraints work by attempting to violate them (you can do this in a temporary script or directly in psql):

1. Create two chapters with the same `manga_id` and `chapter_number` — should fail
2. Create two pages with the same `chapter_id` and `page_number` — should fail
3. Delete a manga — its chapters (and their pages) should be cascade-deleted

## Expected Outcome
- Chapter model with foreign key to Manga and composite unique constraint
- Page model with foreign key to Chapter and composite unique constraint
- `ondelete="CASCADE"` on both foreign keys — deleting a manga removes chapters and pages
- Indexes on foreign keys and ordering columns
- Migration creates both tables with all constraints
- Attempting duplicate chapter numbers per manga raises IntegrityError

## Hints
- `Numeric(precision=6, scale=1)` maps to Python's `Decimal` type. Import from `decimal`: `from decimal import Decimal`.
- For the `Mapped` type annotation with Decimal: `Mapped[Decimal]` works directly.
- SQLAlchemy's `cascade="all, delete-orphan"` on a relationship means: when the parent is deleted through the ORM, children are deleted too (ORM-level cascade). `ondelete="CASCADE"` on the ForeignKey means: when the parent is deleted at the database level, children are deleted too (DB-level cascade). Having both is belt-and-suspenders.
- Name your constraints explicitly (the `name` parameter in `UniqueConstraint`). Alembic handles named constraints better during downgrades.

## What I'll Look For In Review
- Composite unique constraints on (manga_id, chapter_number) and (chapter_id, page_number)
- Foreign keys have `ondelete="CASCADE"`
- Foreign key columns are indexed
- `chapter_number` uses Decimal/Numeric (not Integer) to support half-chapters
- Relationships use `back_populates` on both sides
