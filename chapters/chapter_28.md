# Chapter 28 — Batch Upload & Task Status

## Concepts You'll Learn
- Batch operations and why they need different patterns than single-item CRUD
- Task state tracking with a dedicated model
- The polling pattern for async operations
- Idempotency: why repeated requests should produce the same result

## Concept Deep Dive

### Batch Operations

Uploading one manga page at a time is tedious for users who have 30 pages per chapter. Batch operations let users submit multiple items in a single request. But batch operations introduce complexity that single-item endpoints do not have: partial failures (page 17 of 30 is corrupt), progress tracking (how many are done?), and resource management (uploading 30 files simultaneously could exhaust memory).

The pattern for batch operations in an async architecture is: accept all items, validate them upfront, create a tracking group, enqueue individual tasks, and return the group ID. The client polls the group for progress. This is fundamentally different from a synchronous batch where you process everything and return a result -- that would block for minutes.

```python
# Bad: synchronous batch (blocks forever)
@router.post("/chapters/{id}/pages/batch")
async def upload_batch(files: list[UploadFile]):
    results = []
    for file in files:  # 30 files * 3 seconds each = 90 second request
        result = await process_page(file)
        results.append(result)
    return results

# Good: async batch (returns immediately)
@router.post("/chapters/{id}/pages/batch", status_code=202)
async def upload_batch(files: list[UploadFile]):
    task_group = create_task_group(total=len(files))
    for i, file in enumerate(files):
        s3_key = await storage.upload_file(...)
        page = await create_page(...)
        process_page_image.delay(page.id, s3_key, task_group.id)
    return {"task_group_id": task_group.id, "total": len(files)}
```

### Task State Tracking

In Chapter 27, you used Celery's built-in result backend to track task status. That works for individual tasks, but for groups of tasks and for persisting history beyond Redis's memory, you need a database-backed task model.

A Task model gives you: persistent history (what happened last Tuesday?), custom metadata (which page is this task for?), grouping (which tasks belong to this batch?), and queryable status. Redis result backends are ephemeral -- results expire, and you lose history when Redis restarts.

The typical task state machine is:

```
pending --> processing --> completed
                      \-> failed
```

A TaskGroup aggregates individual tasks: it knows the total count, and you derive `completed_count` by counting child tasks with `status = "completed"`. This avoids maintaining a counter that could go out of sync.

### The Polling Pattern

Since the batch returns immediately with a task group ID, the client needs a way to check progress. The simplest approach is **polling**: the client periodically hits `GET /tasks/{group_id}` to check status.

```json
// Response at t=0
{"task_group_id": "abc123", "total": 20, "completed": 0, "failed": 0, "status": "processing"}

// Response at t=5s
{"task_group_id": "abc123", "total": 20, "completed": 8, "failed": 0, "status": "processing"}

// Response at t=15s
{"task_group_id": "abc123", "total": 20, "completed": 20, "failed": 0, "status": "completed"}
```

Polling is simple and works everywhere (no WebSocket infrastructure needed). The downside is wasted requests when nothing has changed. A reasonable polling interval for batch uploads is 2-5 seconds. Later, you could add WebSocket or Server-Sent Events for real-time updates, but polling is the pragmatic starting point.

### Idempotency

What happens if the user accidentally clicks "Upload" twice? Or if the network hiccups and the client retries? Without idempotency, you get duplicate pages. Idempotency means that performing the same operation multiple times produces the same result as performing it once.

For batch uploads, you can implement idempotency via a client-generated **idempotency key** sent in a request header. The server stores this key with the task group. If a request comes in with a key that already exists, return the existing task group instead of creating a new one.

```python
@router.post("/chapters/{id}/pages/batch", status_code=202)
async def upload_batch(
    chapter_id: int,
    files: list[UploadFile],
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
):
    if idempotency_key:
        existing = await task_service.get_by_idempotency_key(idempotency_key)
        if existing:
            return existing  # Same response as the first request
    # ... proceed with batch creation
```

This is a pattern used by Stripe, AWS, and most production APIs that handle financial or destructive operations.

## Your Task

### Step 1: Create the Task and TaskGroup Models

Create `app/models/task.py` with two models:

**TaskGroup**:
- `id`: UUID primary key
- `type`: string (e.g., "page_batch_upload")
- `status`: enum -- `pending`, `processing`, `completed`, `failed`
- `total_count`: integer
- `metadata`: JSON column (store chapter_id, user_id, etc.)
- `idempotency_key`: optional string with unique index
- `created_at`, `updated_at`: timestamps

**Task**:
- `id`: UUID primary key
- `group_id`: FK to TaskGroup (nullable for standalone tasks)
- `celery_task_id`: string (the Celery task ID for correlation)
- `type`: string (e.g., "process_page_image")
- `status`: enum -- `pending`, `processing`, `completed`, `failed`
- `result`: JSON column (success result or error details)
- `created_at`, `updated_at`: timestamps

Create the Alembic migration.

### Step 2: Create Task Service

Create `app/services/task_service.py` with:

- `create_group(type, total_count, metadata, idempotency_key) -> TaskGroup`
- `create_task(group_id, celery_task_id, type) -> Task`
- `update_task_status(task_id, status, result) -> Task`
- `get_group_with_progress(group_id) -> dict`: returns the group plus counts by status (completed, failed, pending)
- `get_by_idempotency_key(key) -> TaskGroup | None`

For `get_group_with_progress`, query the Task table grouped by status where `group_id` matches. Return something like: `{"group": {...}, "completed": 12, "failed": 1, "processing": 3, "pending": 4}`.

### Step 3: Create Batch Upload Endpoint

Create `POST /chapters/{chapter_id}/pages/batch` that:

1. Accepts `files: list[UploadFile]` and an optional `Idempotency-Key` header
2. Checks the idempotency key -- if a group already exists for this key, return it
3. Validates all files upfront (type check, size check). Reject the entire batch if any file is invalid, since partial acceptance of a batch is confusing
4. Creates a TaskGroup with `total_count = len(files)`
5. For each file: upload original to S3, create Page record (with ordering based on filename or upload order), create Task record, dispatch Celery task
6. Return 202 Accepted with the TaskGroup ID

### Step 4: Update the Celery Task to Report Status

Modify `process_page_image` in `app/worker/tasks/image_tasks.py` to:

1. Accept an additional `task_id` argument (your Task model ID, not Celery's)
2. Update Task status to `processing` at the start
3. On success, update Task status to `completed` with result metadata (S3 keys, dimensions)
4. On failure, update Task status to `failed` with the error message
5. After updating each task, check if all tasks in the group are done. If so, update the TaskGroup status to `completed` (or `failed` if any task failed)

### Step 5: Create Task Status Endpoints

Create these endpoints:

- `GET /tasks/{group_id}`: returns the TaskGroup with progress counts and a list of individual task statuses
- `GET /tasks/{group_id}/tasks`: returns all individual tasks in the group (useful for seeing which specific pages failed)

### Step 6: Handle Partial Failures

If 3 out of 30 page processing tasks fail, the group status should be `completed` (not `failed`) but with a `failed_count` of 3. Only mark the group as `failed` if ALL tasks fail. Include the specific error for each failed task in the result JSON so the user knows which pages to re-upload.

## Expected Outcome
- `POST /chapters/{id}/pages/batch` with multiple files returns 202 with a task group ID
- `GET /tasks/{group_id}` shows progress: `"12/20 complete"`
- Each individual task status is queryable
- Re-sending the same request with the same Idempotency-Key returns the existing group
- If some pages fail processing, the group completes with a `failed_count > 0`
- The Celery worker processes all tasks from the batch

## Hints
- Use `uuid.uuid4()` for TaskGroup and Task IDs -- UUIDs are better than auto-increment integers for external-facing IDs since they are not guessable or sequential
- For the Celery task to update the database Task status, it needs the Task model ID passed as an argument (a UUID string, not an ORM object)
- Be careful with file ordering in the batch. You might sort by filename (`page_001.jpg`, `page_002.jpg`) or use the upload order index
- Idempotency keys should expire after a reasonable time (24 hours) -- you do not need to remember them forever

## What I'll Look For In Review
- The batch endpoint validates ALL files before starting any uploads (fail-fast for the whole batch)
- Task status tracking is in the database, not just Celery's Redis backend
- The polling endpoint returns both overall progress and individual task details
- Idempotency is implemented correctly: same key returns same response, no duplicate work
- The group status accurately reflects partial failures vs total failure
