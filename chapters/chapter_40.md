# Chapter 40 — Tags & Community Metadata

## Concepts You'll Learn
- Tagging systems: many-to-many relationships with user contributions
- Tag normalization: lowercase, dedup, slug generation
- Moderation workflows: suggest, review, approve/reject
- Community-driven metadata and why moderation matters

## Concept Deep Dive

### Tagging Systems

Tags are the most flexible classification system. Unlike genres (a fixed list managed by admins), tags are open-ended labels that describe content in fine-grained ways: "time-travel," "strong-female-lead," "slow-burn," "isekai," "one-shot." They emerge from the community and capture nuances that a genre taxonomy cannot.

The data model is a classic **many-to-many** through an association table:

```
Tag: id, name, slug, status (pending/approved/rejected), created_by, created_at
manga_tags: manga_id, tag_id (association table)
```

Why a separate Tag model instead of just storing tag strings on each manga? Normalization. If one user tags "Time Travel" and another tags "time-travel" and a third tags "time travel", you need them all to resolve to the same tag. A Tag model with a normalized `slug` field handles this:

```python
def normalize_tag(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug

# "Time Travel" -> "time-travel"
# "time-travel" -> "time-travel"
# "time travel" -> "time-travel"
```

### Tag Normalization

Normalization ensures tag consistency. Without it, your database accumulates: "Isekai", "isekai", "ISEKAI", "isekai ", " isekai". With normalization, they all map to slug "isekai" and the display name "Isekai" (the first approved version).

The slug is the unique identifier used for deduplication and URLs. The display name is what users see. When a user suggests a tag, you:

1. Normalize the input to a slug
2. Check if a tag with that slug already exists
3. If yes, use the existing tag (maybe just add the manga-tag association)
4. If no, create a new tag with status "pending"

```python
async def suggest_tag(manga_id: int, tag_name: str, user_id: int):
    slug = normalize_tag(tag_name)
    
    existing = await tag_repo.get_by_slug(slug)
    if existing:
        if existing.status == "approved":
            await tag_repo.add_to_manga(manga_id, existing.id)
            return existing
        elif existing.status == "pending":
            return existing  # Already suggested, waiting for approval
        else:  # rejected
            raise TagRejectedException(slug)
    
    # New tag
    tag = await tag_repo.create(name=tag_name.strip(), slug=slug, status="pending", created_by=user_id)
    await tag_repo.add_to_manga(manga_id, tag.id)
    return tag
```

### Moderation Workflow

If anyone can add tags with no oversight, you get spam, duplicates, offensive content, and meaningless tags. A moderation workflow puts a human (moderator/admin) in the loop:

1. **User suggests**: creates a tag with status `pending`. The tag-manga association is created but the tag does not appear in public listings.
2. **Moderator reviews**: sees a queue of pending tags. For each, they can:
   - **Approve**: status becomes `approved`. The tag now appears in search facets and public listings.
   - **Reject**: status becomes `rejected`. The tag-manga association is removed. Future attempts to suggest the same slug are blocked (or shown a message).
3. **Auto-approve** (optional): trusted users (high reputation, moderators) could have their tags auto-approved. This is a progressive trust model.

The pending queue is just a filtered query: `SELECT * FROM tags WHERE status = 'pending' ORDER BY created_at`. Moderators process this periodically, like a content moderation dashboard.

### Community-Driven Metadata

Letting users contribute metadata (tags, corrections, descriptions) scales your content enrichment beyond what a small admin team can manage. Wikipedia, Stack Overflow, and OpenStreetMap are all built on community contributions with moderation.

For MangaShelf, community tags improve search and discovery. When enough users tag a manga with "time-travel," that tag becomes a reliable signal. You can use tag frequency as a confidence measure: a tag added by 10 users is more trustworthy than one added by 1 user.

Consider tracking how many users have suggested each tag for each manga:

```sql
-- Instead of just manga_tags(manga_id, tag_id), track user contributions
manga_tag_votes: manga_id, tag_id, user_id, created_at
```

A tag's relevance to a manga is proportional to its vote count. This is a simple crowd-sourcing mechanism. For this chapter, the simpler approach (moderator approval without voting) is fine, but the voting extension is worth understanding.

## Your Task

### Step 1: Create the Tag Model

Create `app/models/tag.py` with:

**Tag**:
- `id`: integer primary key
- `name`: string (max 50), not null -- the display name
- `slug`: string (max 50), not null, unique -- the normalized identifier
- `status`: enum (pending, approved, rejected), default pending
- `created_by`: FK to User, nullable (system tags might not have a creator)
- `created_at`: timestamp

**manga_tags** (association table):
- `manga_id`: FK to Manga
- `tag_id`: FK to Tag
- Primary key on (manga_id, tag_id)

Create the Alembic migration.

### Step 2: Create Tag Normalization Utility

Create a utility function (in `app/utils/tags.py` or within the tag service):

- `normalize_tag(name: str) -> str`: converts to lowercase, replaces spaces and special characters with hyphens, collapses multiple hyphens, strips leading/trailing hyphens
- Validate: minimum 2 characters, maximum 50, no purely numeric tags

### Step 3: Create the Tag Repository

Create `app/repositories/tag.py`:

- `create(name, slug, status, created_by) -> Tag`
- `get_by_slug(slug) -> Tag | None`
- `get_by_id(tag_id) -> Tag`
- `list_pending(limit, offset) -> list[Tag]`: moderation queue
- `list_approved(limit, offset) -> list[Tag]`: all approved tags
- `update_status(tag_id, status) -> Tag`
- `get_popular(limit=20) -> list[dict]`: tags with usage count, ordered by count descending
- `add_to_manga(manga_id, tag_id) -> None`: create association
- `remove_from_manga(manga_id, tag_id) -> None`
- `get_manga_tags(manga_id) -> list[Tag]`: all approved tags for a manga

### Step 4: Create the Tag Service

Create `app/services/tag.py`:

- `suggest_tag(manga_id, tag_name, user_id)`: normalize, check existing, create if new with pending status, create manga association
- `approve_tag(tag_id, moderator_id)`: set status to approved
- `reject_tag(tag_id, moderator_id)`: set status to rejected, remove all manga associations for this tag
- `get_popular_tags(limit)`: return most-used approved tags
- `get_manga_tags(manga_id)`: return approved tags for a manga

### Step 5: Create Tag Endpoints

**User endpoints:**
- `POST /manga/{manga_id}/tags`: suggest a tag for a manga. Body: `{name: "time-travel"}`. Returns the tag (with pending status if new, approved if existing).
- `GET /manga/{manga_id}/tags`: list all approved tags for a manga.
- `GET /tags/popular`: list the most popular tags by usage count.

**Admin/moderator endpoints:**
- `GET /admin/tags/pending`: list pending tags (moderation queue). Requires moderator role.
- `PATCH /admin/tags/{tag_id}`: approve or reject a tag. Body: `{status: "approved"}` or `{status: "rejected"}`. Requires moderator role.

### Step 6: Sync Tags to Meilisearch

If you built the Meilisearch integration in Chapter 36, update the search indexing to include approved tags. When a tag is approved, re-index all manga that have that tag. Add "tags" as a filterable attribute in Meilisearch so users can filter search results by tag.

Update the manga search document to include: `"tags": ["time-travel", "isekai", "strong-female-lead"]`.

### Step 7: Create Schemas

In `app/schemas/tag.py`:

- `TagSuggest`: name (string, 2-50 chars)
- `TagResponse`: id, name, slug, status, created_at
- `TagWithCount`: extends TagResponse with usage_count
- `MangaTagsResponse`: list of TagResponse
- `TagModeration`: status (approved or rejected)

## Expected Outcome
- Users can suggest tags for manga: `POST /manga/1/tags` with `{"name": "Time Travel"}`
- Duplicate suggestions (same slug) reuse the existing tag
- `GET /manga/1/tags` returns only approved tags
- Moderators see pending tags at `GET /admin/tags/pending`
- `PATCH /admin/tags/5` with `{"status": "approved"}` approves the tag
- Rejecting a tag removes its manga associations
- `GET /tags/popular` returns the most-used tags with counts
- If Meilisearch is set up, approved tags appear as facets in search

## Hints
- Use Python's `re` module for slug normalization: `re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')`
- For popular tags, use: `SELECT t.*, COUNT(mt.manga_id) as count FROM tags t JOIN manga_tags mt ON t.id = mt.tag_id WHERE t.status = 'approved' GROUP BY t.id ORDER BY count DESC`
- When rejecting a tag, delete from the `manga_tags` association table, not from the tags table (keep the rejected tag to prevent re-suggestion)
- Handle the race condition where two users suggest the same tag simultaneously -- the second one should see the pending tag, not create a duplicate

## What I'll Look For In Review
- Tag slugs are properly normalized and unique (no duplicates with different casing)
- Only approved tags appear in public-facing endpoints (manga tags, popular tags, search facets)
- The moderation workflow has clear state transitions: pending -> approved or pending -> rejected
- Rejecting a tag cleans up its manga associations
- The suggest endpoint handles existing tags correctly (approved: add association, pending: return it, rejected: inform the user)
