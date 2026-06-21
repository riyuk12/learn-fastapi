# Chapter 68 — Admin Panel API

## Concepts You'll Learn
- Admin-specific endpoints and authorization patterns
- Bulk operations for content management
- System health aggregation from multiple sources
- Content moderation tools

## Concept Deep Dive

### Admin-Specific Endpoints

Admin endpoints are fundamentally different from user-facing endpoints. User endpoints are optimized for the single-user perspective: "my library," "my notifications," "manga I can see." Admin endpoints are optimized for the system-wide perspective: "all users," "all content," "system health."

The key architectural decision is **where** to put admin endpoints. Some teams build a completely separate admin service. Others add admin routes to the existing API behind authorization checks. For MangaShelf, adding admin routes to the existing API is practical — you already have the database models, services, and auth system in place.

The authorization pattern is straightforward: create a dependency that checks for admin role.

```python
async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
```

Apply this dependency to the admin router, and every endpoint under it automatically requires admin access. This is cleaner than checking roles inside each endpoint handler.

Group all admin endpoints under the `/admin` prefix. This makes it easy to apply rate limiting, logging, and access controls at the routing level. In production, you might even restrict the `/admin` path at the Nginx level (only accessible from internal network).

### Bulk Operations

Admins frequently need to act on multiple items at once: approve 50 pending tags, delete 10 reported manga, ban several accounts. Individual REST endpoints (PATCH one item at a time) are too slow for this workflow.

Bulk endpoints accept a list of IDs and perform the operation on all of them in a single request. The design decisions are:
- **Atomicity**: Should the bulk operation be all-or-nothing (transaction) or partial (best-effort)? For most admin operations, partial success with a report of failures is more practical.
- **Response format**: Return the result for each item, not just a simple 200. The admin needs to know which items succeeded and which failed.

```python
class BulkOperationResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    errors: list[dict]  # [{"id": "...", "error": "..."}]
```

For safety, bulk operations should have a maximum batch size (e.g., 100 items per request). Without a limit, a single request could try to delete thousands of records and time out or overwhelm the database.

### System Health Aggregation

The admin dashboard endpoint aggregates health metrics from multiple sources into a single response. This is not the same as the `/health` endpoint (which checks if services are alive) — it is a richer picture of system state:

- **User metrics**: Total users, active in last 24h, new registrations today
- **Content metrics**: Total manga, total chapters, total pages, storage used
- **System metrics**: Active sessions, pending Celery tasks, error count from recent logs

Each data point comes from a different source: user count from PostgreSQL, storage from MinIO, active sessions from Redis, error count from your logs or Prometheus. The dashboard endpoint queries all of these and returns a unified JSON response.

The challenge is latency. If one source is slow (MinIO API call takes 2 seconds), the entire dashboard response is slow. Use `asyncio.gather()` to query all sources concurrently, and set timeouts on each query so a slow dependency does not block the entire response.

```python
user_count, manga_count, storage_info = await asyncio.gather(
    get_user_count(),
    get_manga_count(),
    get_storage_usage(),
    return_exceptions=True  # don't fail if one source errors
)
```

### Content Moderation

Moderation is about maintaining content quality and community safety. In MangaShelf, users might report inappropriate content, spam reviews, or offensive tags. The admin needs tools to review reports and take action.

A moderation workflow typically has three stages: **report** (user flags content), **review** (admin examines the report and the content), **resolve** (admin takes action — dismiss the report, remove the content, or ban the user). Each report has a status: pending, reviewed, resolved.

The moderation API does not need to be complex. The critical thing is that it captures the admin's decision (and who made it) for accountability. Every moderation action should be logged: which admin resolved which report, what action they took, and when.

## Your Task

### Step 1: Create Admin Router with Authorization

Create `app/api/v1/endpoints/admin.py` with a router that applies the `require_admin` dependency to all endpoints:

```python
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
```

### Step 2: Build the Dashboard Endpoint

Create `GET /admin/dashboard` that returns an aggregated system overview:
- **Users**: total count, active in last 24h (based on last login or activity), new registrations today
- **Content**: total manga count, total chapter count, total page count
- **Storage**: MinIO bucket usage (call MinIO API to get storage stats)
- **System**: active Redis connections or session count, pending Celery tasks (query Redis for Celery queue length), error count from the last hour (if available from your metrics)

Use `asyncio.gather()` to query all sources concurrently. Handle individual failures gracefully (if MinIO is unreachable, return `"storage": "unavailable"` instead of failing the whole endpoint).

### Step 3: Build User Management Endpoints

- `GET /admin/users` — List all users with search (by username or email), filter (by role, by status), and cursor-based pagination
- `GET /admin/users/{id}` — Detailed user profile: registration date, role, library size, review count, last activity
- `PATCH /admin/users/{id}` — Update user: change role (user/moderator/admin), ban/unban (add an `is_banned` field to your User model if not present). Banning should invalidate active sessions.
- `DELETE /admin/users/{id}` — Soft-delete a user (mark as deleted, do not actually remove data)

### Step 4: Build Content Moderation Endpoints

Create a `Report` model (if you have not already) with:
- `id`, `reporter_id` (FK to users), `target_type` (manga/review/comment), `target_id`, `reason` (text), `status` (pending/reviewed/resolved), `resolved_by` (FK to users, nullable), `resolution_note` (text, nullable), `created_at`, `resolved_at`

Create endpoints:
- `POST /reports` — User-facing: submit a report (available to any authenticated user, not just admins)
- `GET /admin/reports` — List reports with filters: status (pending/resolved), target_type
- `GET /admin/reports/{id}` — Report detail with the reported content included
- `PATCH /admin/reports/{id}/resolve` — Resolve a report: provide action taken (dismiss, remove_content, warn_user, ban_user) and a note

### Step 5: Build Bulk Operation Endpoints

- `POST /admin/tags/approve-all` — Approve all pending community tags (from Chapter 44)
- `DELETE /admin/manga/bulk` — Delete multiple manga by IDs (accepts a list of IDs in the request body, soft-delete)
- `POST /admin/users/bulk-ban` — Ban multiple users by IDs

Each bulk endpoint should return a `BulkOperationResult` with counts of successes and failures plus error details for any failures.

### Step 6: Add Admin Activity Logging

Create a simple `AdminAuditLog` model or table that records every admin action:
- `admin_id`, `action` (e.g., "user.banned", "report.resolved"), `target_type`, `target_id`, `details` (JSON), `created_at`

Log every admin endpoint call. This creates an accountability trail — you can answer "who banned this user and why?" months later.

### Step 7: Add Admin Endpoints to the Router

Register the admin router in your API v1 router. Verify that:
- Non-admin users get 403 on all admin endpoints
- Admin users can access everything
- The dashboard returns real data from all sources

## Expected Outcome
- `/admin/dashboard` returns a comprehensive system overview with real data
- User management endpoints allow search, pagination, role changes, and banning
- Content moderation workflow: users report, admins review, admins resolve
- Bulk operations handle multiple items efficiently with detailed result reporting
- Admin actions are logged in an audit trail
- All admin endpoints require admin role (403 for non-admins)

## Hints
- For the dashboard endpoint, set a timeout on each `asyncio.gather` coroutine using `asyncio.wait_for(coroutine, timeout=5.0)`. This prevents one slow service from making the entire dashboard unusable.
- For banning users, you need to invalidate their tokens. If you are using JWT, you cannot truly revoke a token — but you can add the user's ban status to a Redis blacklist that your auth middleware checks on every request.
- The `Report` model is user-created (anyone can report) but admin-managed (only admins can resolve). Make sure the `POST /reports` endpoint is on the regular user router, not the admin router.
- For bulk operations, use a database transaction for each item (not one giant transaction for all items). This way, a failure on item 5 does not roll back items 1-4.

## What I'll Look For In Review
- Admin authorization is applied at the router level (not repeated in each handler)
- Dashboard aggregates data concurrently with proper error handling for each source
- Bulk operations return detailed results (not just success/failure)
- Admin actions are audit-logged with the acting admin's ID
- User banning actually prevents the banned user from accessing the API
