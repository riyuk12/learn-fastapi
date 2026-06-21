# Chapter 50 — Notification System

## Concepts You'll Learn
- Notification types and templates
- Read/unread state management
- Notification preferences per user
- Fan-out to followers on events

## Concept Deep Dive

### Notification Types and Templates

Notifications are structured messages triggered by system events. Unlike activities (Chapter 49), which are about *what someone did*, notifications are about *what matters to you*. A notification says "something happened that you should know about."

Each notification type maps to a specific event and has a template for rendering human-readable text. For example, a `new_chapter` notification might render as "Chapter 42 of 'One Piece' was just released" while a `comment_reply` renders as "Alice replied to your comment on 'Naruto' Chapter 10."

```python
class NotificationType(str, enum.Enum):
    NEW_CHAPTER = "new_chapter"
    COMMENT_REPLY = "comment_reply"
    REVIEW_UPVOTE = "review_upvote"
    FOLLOW = "follow"
    SYSTEM = "system"
```

The `data` JSON column is critical. It stores everything needed for the client to handle the notification: a deep link URL, the IDs of related entities, display names, and thumbnail URLs. This makes notifications self-contained — the frontend can render and navigate from a notification without making additional API calls. Think of `data` as the notification's payload, and `title`/`body` as the human-readable summary.

### Read/Unread State Management

Every notification has an `is_read` boolean, defaulting to `false`. This seems simple, but the UX implications require careful API design. Users expect three capabilities: seeing their unread count (for a badge), marking individual notifications as read, and marking all notifications as read in bulk.

The unread count needs to be cheap to compute because it is polled frequently (or pushed via SSE, which you will build in Chapter 51). A simple `SELECT COUNT(*) FROM notifications WHERE user_id = :id AND is_read = false` works, but if you want to optimize, you can maintain a denormalized `unread_count` on the user model — increment on notification creation, decrement on read, zero on mark-all-read. The trade-off is the same denormalization complexity you dealt with in Chapter 47.

For "mark as read," you have two patterns. **Explicit mark**: the user clicks a notification and you call `PATCH /notifications/{id}/read`. **Implicit mark**: opening the notification list marks everything visible as read. MangaShelf should support both — explicit per-notification and a bulk `POST /notifications/mark-all-read`.

### Notification Preferences

Not every user wants every notification type. A power reader might want `new_chapter` alerts but find `review_upvote` notifications annoying. Preferences give users control.

Model this as a JSON column on the user model (or a separate `notification_preferences` table). The schema is a mapping of notification type to boolean:

```python
# Stored as JSON on user or in a preferences table
{
    "new_chapter": true,
    "comment_reply": true,
    "review_upvote": false,
    "follow": true,
    "system": true  # system notifications should generally not be opt-outable
}
```

When the NotificationService is about to create a notification, it checks the recipient's preferences first. If the user has disabled that type, the notification is simply not created. System notifications bypass preferences — you always want users to see security alerts or terms-of-service changes.

### Fan-Out to Followers

The most interesting notification scenario is fan-out: when something happens (e.g., a new chapter is uploaded for manga X), every user who follows that manga should get a notification. This is a write-time fan-out problem.

When a new chapter is created, the NotificationService queries for all followers of that manga, then bulk-inserts a notification for each follower (respecting their preferences). For small fan-out (hundreds of followers), this can happen synchronously. For large fan-out (thousands), you should offload to a Celery task.

```python
# Pseudocode for fan-out
async def notify_new_chapter(manga_id: UUID, chapter_number: int):
    followers = await follow_repo.get_followers("manga", manga_id)
    notifications = []
    for follower in followers:
        if follower.preferences.get("new_chapter", True):
            notifications.append(Notification(
                user_id=follower.id,
                type=NotificationType.NEW_CHAPTER,
                title=f"New chapter available",
                body=f"Chapter {chapter_number} of {manga.title}",
                data={"manga_id": str(manga_id), "chapter_id": str(chapter.id)}
            ))
    await notification_repo.bulk_create(notifications)
```

The critical thing is to batch the insert. Do not insert one row at a time in a loop — use `session.add_all()` or a bulk insert to keep it efficient.

## Your Task

### Step 1: Create the Notification Model

Create `app/models/notification.py` with:
- `id` (UUID primary key)
- `user_id` (UUID FK to users, not nullable, indexed)
- `type` (Enum: new_chapter, comment_reply, review_upvote, follow, system)
- `title` (String, not nullable)
- `body` (String, nullable)
- `is_read` (Boolean, default False)
- `data` (JSON, nullable — stores deep link info, entity IDs, etc.)
- `created_at` (timestamp with timezone, server default now)

Add a composite index on `(user_id, is_read, created_at DESC)` — this powers the "unread notifications, newest first" query.

### Step 2: Create Notification Preferences

Add a `notification_preferences` JSON column to your User model (or create a separate `NotificationPreference` model — your choice). Define defaults where all types are enabled. Create an endpoint to update preferences: `PUT /users/me/notification-preferences`.

### Step 3: Generate Migration

Run Alembic to create the migration for the notification table and any user model changes.

### Step 4: Create Notification Repository

Create `app/repositories/notification_repository.py` with:
- `create(notification)` — single insert
- `bulk_create(notifications)` — batch insert for fan-out
- `get_by_user(user_id, is_read_filter, limit, cursor)` — paginated list
- `get_unread_count(user_id)` — count for badge
- `mark_as_read(notification_id, user_id)` — mark one read (verify ownership)
- `mark_all_as_read(user_id)` — bulk update

### Step 5: Create NotificationService

Create `app/services/notification_service.py` with:
- `notify_user(user_id, type, title, body, data)` — creates one notification, checks preferences first
- `notify_new_chapter(manga_id, chapter)` — fan-out to manga followers
- `notify_comment_reply(parent_comment)` — notify the parent comment's author
- `notify_follow(followed_user_id, follower)` — notify someone they got a new follower
- `get_notifications(user_id, is_read, limit, cursor)` — paginated fetch
- `get_unread_count(user_id)` — for badge display

### Step 6: Create Notification Endpoints

In `app/api/v1/endpoints/notifications.py`:
- `GET /notifications` — list current user's notifications, with optional `?is_read=false` filter, cursor-paginated
- `GET /notifications/unread-count` — returns `{"count": 5}`
- `PATCH /notifications/{id}/read` — mark one as read
- `POST /notifications/mark-all-read` — mark all as read
- `PUT /users/me/notification-preferences` — update which types the user wants

### Step 7: Wire Notifications into Existing Events

Integrate NotificationService calls into:
- Chapter creation (in your manga/chapter service): trigger `notify_new_chapter`
- Comment replies (in your comment service from Chapter 48): trigger `notify_comment_reply`
- Follow creation (from Chapter 49): trigger `notify_follow`

Use try/except so notification failures never break the primary operation.

## Expected Outcome
- Notifications are auto-created when relevant events occur (new chapter, reply, follow)
- `GET /notifications` returns paginated notifications for the current user
- Unread count endpoint works for badge display
- Mark-as-read works for individual and bulk
- User preferences control which notification types are received
- Fan-out creates notifications for all followers of a manga when a new chapter drops

## Hints
- For bulk inserts, SQLAlchemy's `session.add_all()` works, but for very large batches consider `session.execute(insert(Notification).values(list_of_dicts))` for better performance.
- The unread count query should use the composite index. Make sure the index column order matches your WHERE clause.
- When checking preferences, default to "enabled" if a user has not set any preferences yet.
- Fan-out for new chapters could be slow for popular manga. Consider making it a Celery task if the follower count is above a threshold (e.g., 100).

## What I'll Look For In Review
- Notification model with proper indexes for the unread query pattern
- Preferences are checked before creating notifications
- Fan-out uses bulk insert, not individual inserts in a loop
- Notification failures do not break the triggering operation
- Endpoints include proper authorization (users can only see/modify their own notifications)
