# Chapter 39 — Collections

## Concepts You'll Learn
- User-generated content: letting users create and curate lists
- Visibility controls: public vs private resources
- Ordered items with a position field
- Reordering strategies that avoid renumbering every item

## Concept Deep Dive

### User-Generated Content

Collections are the first feature where users create content beyond simple metadata (like a rating). A collection is a curated list: "Best Manga of 2025," "Dark Fantasy Must-Reads," "My Top 10 Isekai." This is the same concept as Spotify playlists, Goodreads shelves, or Steam curated lists.

The data model has two parts: the **collection** (metadata about the list) and **collection items** (the manga in the list, with ordering). This is a classic header-detail or parent-child pattern:

```
Collection: id, user_id, title, description, is_public, created_at
CollectionItem: id, collection_id, manga_id, position, note, added_at
```

Each item can have a **note** -- "Why I included this" or "Start with volume 3." This makes collections more than just a list; they become curated recommendations.

### Visibility Controls

Collections can be **public** (anyone can view) or **private** (only the owner). This is a common access control pattern for user-generated content.

The rules:
- Owner can always CRUD their own collections and items
- Any authenticated user can view public collections
- No one except the owner can view private collections
- Only the owner can change visibility

In the query layer, this means different filters depending on the viewer:

```python
async def get_collection(collection_id: int, viewer_id: int = None):
    collection = await repo.get_by_id(collection_id)
    if not collection:
        raise NotFoundException()
    
    if collection.user_id == viewer_id:
        return collection  # Owner sees everything
    
    if not collection.is_public:
        raise NotFoundException()  # 404, not 403 (don't leak existence)
    
    return collection
```

For listing, public collections can be browsed by anyone (`GET /collections/public`), while `GET /collections` shows only the current user's collections.

### Ordered Items with Position Field

Items in a collection have a specific order. The user carefully curates "My Top 10" with their #1 pick first. This ordering is stored as a `position` integer on each CollectionItem.

The simplest scheme: positions are 1, 2, 3, 4, 5. Inserting at position 3 requires shifting positions 3, 4, 5 up to 4, 5, 6. Deleting position 3 requires shifting 4, 5 down to 3, 4. This works but generates many UPDATE statements.

A better approach for inserts: use gaps. Start positions at 1000, 2000, 3000. Inserting between 1000 and 2000 uses position 1500. Between 1000 and 1500 uses 1250. You rarely need to renumber. Only when gaps run out do you rebalance:

```python
async def add_item_at_position(collection_id, manga_id, position):
    """Add item at a specific position, shifting others if needed."""
    # Get current items at or after this position
    items_to_shift = await repo.get_items_from_position(collection_id, position)
    
    # Shift them up by 1
    for item in items_to_shift:
        item.position += 1
    
    # Insert the new item
    new_item = CollectionItem(
        collection_id=collection_id,
        manga_id=manga_id,
        position=position,
    )
    session.add(new_item)
```

For most use cases (collections under 100 items), the simple consecutive integer approach is fine. Premature optimization of ordering is a trap -- get it working, then optimize if users create collections with thousands of items.

### Reordering Strategies

Reordering is the hardest part of ordered lists. The user drags item 5 to position 2. What happens in the database?

**Strategy 1: Update all positions**
Set position for the moved item, then update all affected items. Simple, correct, but generates many queries.

**Strategy 2: Swap positions**
Only works for adjacent moves (move up one / move down one).

**Strategy 3: Accept a full ordered list**
The client sends the complete item order: `[id3, id1, id5, id2, id4]`. The server updates all positions in one batch. This is the most flexible and handles any reorder (single move, multi-select drag, etc.):

```python
@router.put("/collections/{id}/reorder")
async def reorder_collection(collection_id: int, body: ReorderRequest):
    # body.item_ids = [3, 1, 5, 2, 4] -- the desired order
    for position, item_id in enumerate(body.item_ids, start=1):
        await repo.update_position(collection_id, item_id, position)
```

This is O(n) updates, but n is typically small (10-50 items). For collections under 200 items, this is negligible. It is also the most common approach used by Trello, Notion, and similar apps.

## Your Task

### Step 1: Create the Collection and CollectionItem Models

Create `app/models/collection.py` with:

**Collection**:
- `id`: integer or UUID primary key
- `user_id`: FK to User, not null
- `title`: string (max 200), not null
- `description`: text, nullable
- `is_public`: boolean, default False
- `created_at`, `updated_at`: timestamps

**CollectionItem**:
- `id`: integer or UUID primary key
- `collection_id`: FK to Collection, not null (with CASCADE delete)
- `manga_id`: FK to Manga, not null
- `position`: integer, not null
- `note`: text, nullable (max 500 chars)
- `added_at`: timestamp

Add a unique constraint on `(collection_id, manga_id)` -- no duplicate manga in one collection. Add an index on `(collection_id, position)` for ordered retrieval.

Create the Alembic migration.

### Step 2: Create the Collection Repository

Create `app/repositories/collection.py` with:

- `create(user_id, title, description, is_public) -> Collection`
- `get_by_id(collection_id) -> Collection | None`
- `list_by_user(user_id, limit, offset) -> list[Collection]`: user's own collections
- `list_public(limit, offset) -> list[Collection]`: all public collections
- `update(collection_id, **fields) -> Collection`
- `delete(collection_id) -> None`: cascade deletes items
- `add_item(collection_id, manga_id, note, position) -> CollectionItem`: add manga to collection
- `remove_item(collection_id, manga_id) -> None`
- `get_items(collection_id) -> list[CollectionItem]`: ordered by position, with manga details
- `reorder(collection_id, item_ids: list[int]) -> None`: update all positions
- `get_next_position(collection_id) -> int`: returns max(position) + 1 for appending

### Step 3: Create the Collection Service

Create `app/services/collection.py`:

- `create_collection(user_id, title, description, is_public)`: validate input, create
- `get_collection(collection_id, viewer_id)`: apply visibility rules (owner sees all, others see only public)
- `update_collection(collection_id, user_id, **updates)`: verify ownership before updating
- `delete_collection(collection_id, user_id)`: verify ownership
- `add_manga(collection_id, user_id, manga_id, note)`: verify ownership, check manga exists, auto-assign next position
- `remove_manga(collection_id, user_id, manga_id)`: verify ownership, remove item, optionally rebalance positions
- `reorder(collection_id, user_id, ordered_item_ids)`: verify ownership, validate all IDs belong to the collection, update positions

### Step 4: Create Collection Endpoints

- `POST /collections`: create a collection. Body: `{title, description?, is_public?}`. Returns 201.
- `GET /collections`: list the current user's collections.
- `GET /collections/public`: browse public collections from all users. Support pagination.
- `GET /collections/{id}`: view a collection with its items. Applies visibility rules.
- `PATCH /collections/{id}`: update title, description, or visibility. Owner only.
- `DELETE /collections/{id}`: delete collection and all items. Owner only. Returns 204.
- `POST /collections/{id}/items`: add a manga. Body: `{manga_id, note?}`. Returns 201.
- `DELETE /collections/{id}/items/{manga_id}`: remove a manga from the collection.
- `PUT /collections/{id}/reorder`: reorder items. Body: `{item_ids: [3, 1, 5, 2, 4]}`.

### Step 5: Create Schemas

In `app/schemas/collection.py`:

- `CollectionCreate`: title, description (optional), is_public (default False)
- `CollectionUpdate`: title (optional), description (optional), is_public (optional)
- `CollectionItemAdd`: manga_id, note (optional)
- `ReorderRequest`: item_ids (list of integers)
- `CollectionResponse`: all collection fields plus `item_count` and owner username
- `CollectionDetailResponse`: extends CollectionResponse with a list of items (each with manga details)
- `CollectionItemResponse`: position, manga details (id, title, cover_url), note, added_at

### Step 6: Test Visibility and Ordering

Test these scenarios:
- Create a private collection, verify another user gets 404 on `GET /collections/{id}`
- Make it public, verify another user can now view it
- Add 5 manga, verify they have positions 1-5
- Reorder to [3, 1, 5, 2, 4], verify the new order in GET response
- Try adding the same manga twice, verify 409 error
- Delete item at position 3, verify remaining items are still ordered

## Expected Outcome
- Users can create collections with title, description, and visibility
- Adding manga to a collection assigns the next position automatically
- `GET /collections/{id}` returns items in position order with manga details
- Public collections are browsable by all users; private ones are 404 for non-owners
- Reordering updates all positions correctly
- Deleting a collection cascades to its items
- No duplicate manga within a single collection

## Hints
- For CASCADE delete, set `ondelete="CASCADE"` on the ForeignKey and configure the SQLAlchemy relationship with `cascade="all, delete-orphan"`
- When adding an item without a specified position, use `SELECT COALESCE(MAX(position), 0) + 1 FROM collection_items WHERE collection_id = :id`
- For the reorder endpoint, validate that the provided item_ids list contains exactly the same IDs as the collection's current items (no missing, no extras)
- Use `enumerate(item_ids, start=1)` to assign positions from the ordered list

## What I'll Look For In Review
- Visibility rules are enforced correctly: private collections return 404 for non-owners
- Ownership is verified before any mutation (update, delete, add item, reorder)
- The reorder endpoint validates the item_ids list completely before updating
- Collection items are always returned sorted by position
- The cascade delete works correctly (deleting a collection removes all its items)
