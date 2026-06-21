# Chapter 48 — Nested Comments

## Concepts You'll Learn
- Tree structures in SQL: the adjacency list model
- Recursive CTEs: querying hierarchical data with WITH RECURSIVE
- Comment moderation and soft delete that preserves thread structure
- Building a comment tree from flat database rows

## Concept Deep Dive

### Tree Structures in SQL: Adjacency List

Comments can be nested: a reply to a reply to a reply. This forms a **tree** -- each comment has zero or one parent, and zero or many children. Storing trees in a relational database (which is fundamentally tabular, not hierarchical) requires a strategy. The simplest and most common is the **adjacency list model**: each row has a `parent_id` column pointing to its parent row.

```sql
CREATE TABLE comments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    manga_id INTEGER REFERENCES manga(id),
    chapter_id INTEGER REFERENCES chapters(id),  -- nullable (manga-level vs chapter-level)
    parent_id INTEGER REFERENCES comments(id),    -- nullable (top-level comment)
    body TEXT NOT NULL,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

A top-level comment has `parent_id = NULL`. A reply to comment #5 has `parent_id = 5`. A reply to that reply has `parent_id` pointing to the reply's ID. The tree can be arbitrarily deep.

```
Comment 1 (parent_id=NULL) - "Great chapter!"
  Comment 3 (parent_id=1) - "I agree!"
    Comment 5 (parent_id=3) - "Same here"
  Comment 4 (parent_id=1) - "The art was amazing"
Comment 2 (parent_id=NULL) - "When does the next chapter come out?"
```

The adjacency list model is simple to understand and write to (just set parent_id). The challenge is reading: how do you fetch an entire comment tree in one query?

### Recursive CTEs

A **Common Table Expression (CTE)** is a named temporary result set. A **recursive CTE** references itself, allowing you to traverse hierarchical data. This is how you fetch an entire comment tree in a single query:

```sql
WITH RECURSIVE comment_tree AS (
    -- Base case: top-level comments (no parent)
    SELECT id, parent_id, user_id, body, is_deleted, created_at, 0 AS depth
    FROM comments
    WHERE manga_id = :manga_id AND parent_id IS NULL
    
    UNION ALL
    
    -- Recursive case: children of already-found comments
    SELECT c.id, c.parent_id, c.user_id, c.body, c.is_deleted, c.created_at, ct.depth + 1
    FROM comments c
    INNER JOIN comment_tree ct ON c.parent_id = ct.id
)
SELECT * FROM comment_tree ORDER BY created_at;
```

The CTE works in two phases:
1. **Base case**: fetches all top-level comments (parent_id IS NULL)
2. **Recursive case**: joins the comments table against the CTE itself to find children of already-found comments
3. PostgreSQL repeats step 2 until no new rows are found

The `depth` column tracks nesting level (0 for top-level, 1 for first reply, 2 for reply-to-reply). This is useful for frontend indentation.

In SQLAlchemy, recursive CTEs are supported but verbose:

```python
from sqlalchemy import select, literal_column, union_all

# Base case
base = (
    select(
        Comment.id, Comment.parent_id, Comment.user_id,
        Comment.body, Comment.is_deleted, Comment.created_at,
        literal_column("0").label("depth"),
    )
    .where(Comment.manga_id == manga_id)
    .where(Comment.parent_id.is_(None))
).cte(name="comment_tree", recursive=True)

# Recursive step
comment_alias = aliased(Comment, name="c")
recursive = (
    select(
        comment_alias.id, comment_alias.parent_id, comment_alias.user_id,
        comment_alias.body, comment_alias.is_deleted, comment_alias.created_at,
        (base.c.depth + 1).label("depth"),
    )
    .join(base, comment_alias.parent_id == base.c.id)
)

cte = base.union_all(recursive)
stmt = select(cte).order_by(cte.c.created_at)
```

An alternative to the SQLAlchemy CTE approach: use raw SQL with `text()` for the recursive query. Recursive CTEs are one case where raw SQL is often clearer than the ORM equivalent. Use whatever is more readable and maintainable for you.

### Comment Moderation and Soft Delete

When a moderator deletes an offensive comment, you cannot hard-delete the row if it has replies. Deleting the parent would orphan the children (their parent_id would reference a nonexistent row) or cascade-delete them (destroying innocent replies).

**Soft delete** solves this: set `is_deleted = True` and replace the body with a placeholder. The comment row stays in the database, preserving the tree structure. The frontend shows "[deleted]" with the children still visible:

```
Comment 1 - "Great chapter!"
  [deleted]                          <-- comment 3, soft-deleted
    Comment 5 - "Same here"          <-- still visible, tree intact
  Comment 4 - "The art was amazing"
```

```python
async def soft_delete_comment(comment_id: int, moderator_id: int):
    comment = await repo.get_by_id(comment_id)
    comment.is_deleted = True
    comment.body = "[deleted]"  # Or keep original body for audit, but hide in API
    comment.deleted_by = moderator_id  # Track who deleted it
    await session.commit()
```

Users can delete their own comments (soft delete). Moderators can delete anyone's comments. Neither action destroys the thread.

A refinement: if a comment is soft-deleted AND all its children are also deleted, you can hide the entire subtree. This prevents "[deleted]" ghosts with no visible replies. Implementing this requires checking if any descendant is not deleted, which the recursive CTE can handle with a flag.

### Building a Comment Tree from Flat Rows

The recursive CTE returns flat rows with `depth` and `parent_id`. The frontend typically expects a nested tree structure. You can build this in Python:

```python
def build_comment_tree(flat_comments: list[dict]) -> list[dict]:
    """Convert flat list with parent_id into nested tree."""
    comment_map = {}
    roots = []
    
    for comment in flat_comments:
        comment["children"] = []
        comment_map[comment["id"]] = comment
    
    for comment in flat_comments:
        if comment["parent_id"] is None:
            roots.append(comment)
        else:
            parent = comment_map.get(comment["parent_id"])
            if parent:
                parent["children"].append(comment)
    
    return roots
```

This is O(n) -- one pass to build the map, one pass to link children to parents. The result is a nested structure ready for JSON serialization:

```json
[
  {
    "id": 1, "body": "Great chapter!", "children": [
      {"id": 3, "body": "[deleted]", "children": [
        {"id": 5, "body": "Same here", "children": []}
      ]},
      {"id": 4, "body": "The art was amazing", "children": []}
    ]
  },
  {
    "id": 2, "body": "When does the next chapter come out?", "children": []
  }
]
```

## Your Task

### Step 1: Create the Comment Model

Create `app/models/comment.py` with:

- `id`: integer primary key
- `user_id`: FK to User, not null
- `manga_id`: FK to Manga, not null
- `chapter_id`: FK to Chapter, nullable (null = manga-level comment, set = chapter-specific comment)
- `parent_id`: FK to self (Comment), nullable (null = top-level comment)
- `body`: text, not null, max 2000 characters
- `is_deleted`: boolean, default False
- `created_at`: timestamp
- `updated_at`: timestamp

Add indexes on `(manga_id, created_at)` for listing comments and `(parent_id)` for the recursive join. Add a check constraint that body is not empty (or at least 1 character).

Create the Alembic migration.

### Step 2: Create the Comment Repository

Create `app/repositories/comment.py`:

- `create(user_id, manga_id, chapter_id, parent_id, body) -> Comment`: creates a comment. If parent_id is provided, validate that the parent exists and belongs to the same manga.
- `get_by_id(comment_id) -> Comment | None`
- `get_tree(manga_id, chapter_id=None) -> list[dict]`: uses the recursive CTE to fetch all comments for a manga (or chapter) with depth info. Returns flat rows with depth.
- `soft_delete(comment_id) -> Comment`: sets is_deleted=True
- `update(comment_id, body) -> Comment`: update comment body
- `count_by_manga(manga_id) -> int`: total comment count

For the recursive CTE, you can use either SQLAlchemy's CTE builder or raw SQL via `text()`. Choose whichever is more readable.

### Step 3: Create the Comment Service

Create `app/services/comment.py`:

- `create_comment(user_id, manga_id, chapter_id, parent_id, body)`:
  1. Validate manga exists
  2. If chapter_id, validate chapter exists and belongs to the manga
  3. If parent_id, validate parent exists and belongs to the same manga
  4. Optionally limit nesting depth (e.g., max 5 levels deep)
  5. Create the comment

- `get_comment_tree(manga_id, chapter_id=None)`:
  1. Fetch flat rows via recursive CTE
  2. Build nested tree structure using the tree-building algorithm
  3. For soft-deleted comments, replace body with "[deleted]" and set user info to null
  4. Include user info (username) for non-deleted comments

- `delete_comment(comment_id, user_id, is_moderator=False)`:
  1. Fetch the comment
  2. If user_id matches the comment's user_id OR is_moderator is True, proceed
  3. Soft delete (do not hard delete)

- `update_comment(comment_id, user_id, body)`:
  1. Fetch the comment
  2. Verify ownership (only the author can edit)
  3. Verify not deleted
  4. Update the body

### Step 4: Create Comment Endpoints

- `POST /comments`: create a comment. Body: `{manga_id, chapter_id?, parent_id?, body}`. Returns 201.
- `GET /manga/{manga_id}/comments`: get the comment tree for a manga. Returns nested structure. Optional `chapter_id` query param to filter to chapter-level comments.
- `PATCH /comments/{id}`: update comment body. Body: `{body}`. Owner only.
- `DELETE /comments/{id}`: soft delete a comment. Owner or moderator.

### Step 5: Create Comment Schemas

In `app/schemas/comment.py`:

- `CommentCreate`: manga_id, chapter_id (optional), parent_id (optional), body (1-2000 chars)
- `CommentUpdate`: body (1-2000 chars)
- `CommentResponse`: id, user (username or null if deleted), manga_id, chapter_id, parent_id, body (or "[deleted]"), is_deleted, depth, created_at, children (list of CommentResponse)

The `CommentResponse` is recursive (children is a list of CommentResponse). In Pydantic v2, handle this with model_rebuild or ForwardRef:

```python
class CommentResponse(BaseModel):
    id: int
    user: UserBrief | None  # None if deleted
    body: str  # "[deleted]" if is_deleted
    is_deleted: bool
    depth: int
    created_at: datetime
    children: list["CommentResponse"] = []

CommentResponse.model_rebuild()  # Resolves the forward reference
```

### Step 6: Handle Edge Cases

- **Deleting a comment with children**: soft delete only. Children remain visible.
- **Deleting a comment with no children**: you could hard-delete since there is nothing to preserve. But for simplicity, soft-delete everything uniformly.
- **Deeply nested threads**: optionally limit reply depth to 5 levels. If someone tries to reply to a depth-5 comment, return an error.
- **Editing a deleted comment**: not allowed. Return 410 Gone or 400.
- **Empty comment tree**: return an empty list, not an error.

### Step 7: Test the Comment Tree

Create this test scenario:
1. User A posts comment 1 (top-level)
2. User B replies to comment 1 (comment 2, depth 1)
3. User A replies to comment 2 (comment 3, depth 2)
4. User C posts comment 4 (top-level)
5. Moderator deletes comment 2

Verify `GET /manga/{id}/comments` returns:
```json
[
  {
    "id": 1, "body": "...", "depth": 0, "children": [
      {"id": 2, "body": "[deleted]", "user": null, "depth": 1, "children": [
        {"id": 3, "body": "...", "depth": 2, "children": []}
      ]}
    ]
  },
  {"id": 4, "body": "...", "depth": 0, "children": []}
]
```

## Expected Outcome
- Top-level and nested comments can be created
- `GET /manga/{id}/comments` returns a properly nested tree structure
- Soft-deleted comments show "[deleted]" but their children remain visible
- Only the comment author can edit their comment
- Moderators can delete any comment; regular users can only delete their own
- The recursive CTE fetches the entire tree in a single database query
- Reply depth is optionally limited to prevent infinitely deep threads

## Hints
- For the recursive CTE in raw SQL, use `session.execute(text(sql), params)`. Raw SQL is often clearer than SQLAlchemy's CTE builder for recursive queries.
- The tree-building algorithm needs the comments sorted by created_at to maintain chronological order within each level of replies
- Pydantic's recursive model (`children: list["CommentResponse"]`) requires `model_rebuild()` after the class definition
- When soft-deleting, consider whether to keep the original body for admin audit logs (store it but do not return it in the API) or truly replace it

## What I'll Look For In Review
- The recursive CTE fetches the entire comment tree in one query (not N+1 queries per level)
- Soft delete preserves thread structure: deleted comment's children are still visible
- Ownership checks prevent users from editing or deleting other users' comments
- The tree-building algorithm correctly nests children under parents
- The API returns "[deleted]" with null user info for soft-deleted comments, not the original content
