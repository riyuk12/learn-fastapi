# Chapter 29 — Background Jobs: Cleanup & Maintenance

## Concepts You'll Learn
- Celery Beat for periodic/scheduled tasks
- Cron-like scheduling in Python
- Orphan cleanup: detecting and removing data inconsistencies
- Database maintenance as an operational concern

## Concept Deep Dive

### Celery Beat for Periodic Tasks

So far, your Celery tasks fire on demand -- upload a page, process the image. But some tasks need to run on a schedule: clean up stale data every night, generate daily reports, expire old sessions. Celery Beat is a scheduler process that periodically sends tasks to the broker, just like cron sends commands to the shell.

Celery Beat runs as a separate process alongside your workers. It keeps a schedule in memory (or a database) and checks every second whether any tasks are due. When a task is due, Beat pushes it to the broker and the worker picks it up like any other task.

```python
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "cleanup-orphaned-images": {
        "task": "app.worker.tasks.maintenance.cleanup_orphaned_images",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
    },
    "cleanup-expired-tasks": {
        "task": "app.worker.tasks.maintenance.cleanup_expired_tasks",
        "schedule": crontab(hour=4, minute=0),  # Daily at 4 AM
    },
}
```

The `crontab()` helper supports the same syntax as Unix cron: `minute`, `hour`, `day_of_week`, `day_of_month`, `month_of_year`. You can also use `timedelta` for simple intervals like "every 30 minutes."

Important: only run **one** Beat instance. If you run two, every task fires twice. In a production Docker setup, Beat is a single-replica service.

### Cron-Like Scheduling

The cron syntax maps naturally to common maintenance windows:

```python
from celery.schedules import crontab
from datetime import timedelta

# Every day at midnight
crontab(hour=0, minute=0)

# Every Monday at 6 AM
crontab(hour=6, minute=0, day_of_week=1)

# Every 15 minutes
timedelta(minutes=15)

# First day of every month at 2 AM
crontab(hour=2, minute=0, day_of_month=1)
```

Schedule maintenance tasks during low-traffic periods. If your users are in IST, 3 AM IST is a good window. Cleanup tasks can be I/O heavy (scanning S3, querying the database), and you do not want them competing with user-facing traffic.

### Orphan Cleanup

Orphaned objects are data that exists in one system but has no corresponding reference in another. In MangaShelf, this happens naturally:

- A page upload to S3 succeeds, but the database insert fails. Now S3 has an image with no DB record.
- A manga is deleted from the database, but the S3 cleanup fails. Now S3 has images for a manga that does not exist.
- A Celery task creates temporary files in S3 during processing but crashes before cleaning them up.

Orphan cleanup compares the two sources of truth (S3 and the database) and removes objects that exist in one but not the other. This is called **reconciliation** in data engineering.

```python
async def find_orphaned_s3_objects():
    """Find S3 objects with no matching DB record."""
    # List all keys in S3 under "pages/" prefix
    s3_keys = await storage.list_objects(prefix="pages/")
    # Get all page S3 keys from the database
    db_keys = await page_repo.get_all_s3_keys()
    # Orphans are in S3 but not in DB
    orphans = set(s3_keys) - set(db_keys)
    return orphans
```

Always run orphan cleanup in **dry-run mode first**. Log what would be deleted, review the list, then enable actual deletion. Accidentally deleting legitimate files is worse than having a few orphans.

### Database Maintenance

Beyond S3 cleanup, databases need periodic maintenance too:

- **Expired task records**: Task records from months ago serve no purpose and slow down queries. Delete tasks older than 7 days (or archive them first).
- **Expired sessions/tokens**: Revoked or expired refresh tokens sitting in the database should be purged.
- **Soft-deleted records**: If you use soft deletes (an `is_deleted` flag), periodically hard-delete records that have been soft-deleted for more than 30 days.

These are not sexy features, but production systems that skip maintenance accumulate technical debt that manifests as slow queries, bloated storage, and confusing data inconsistencies.

## Your Task

### Step 1: Configure Celery Beat

Update `app/worker/celery_app.py` to include a `beat_schedule`. Define two scheduled tasks:

1. `cleanup_orphaned_images` -- runs daily at 3 AM UTC
2. `cleanup_expired_tasks` -- runs daily at 4 AM UTC

Add `CELERY_BEAT_SCHEDULE_FILENAME` to your config to control where Beat stores its schedule database file (defaults to `celerybeat-schedule` in the working directory).

### Step 2: Create Maintenance Tasks

Create `app/worker/tasks/maintenance.py` with these tasks:

**cleanup_orphaned_images**:
1. List all S3 objects under the `pages/` and `covers/` prefixes
2. Query the database for all S3 keys stored in Page and Manga models
3. Compute the difference (S3 keys not in the database)
4. For safety, implement a threshold: if more than 100 orphans are found, log a warning and stop (something might be wrong). Otherwise, delete the orphans from S3.
5. Log how many orphans were found and deleted
6. Return a summary: `{"orphans_found": 15, "orphans_deleted": 15}`

**cleanup_expired_tasks**:
1. Query for Task and TaskGroup records where `created_at < now - 7 days` and `status` is `completed` or `failed`
2. Delete them in batches (do not issue a single DELETE for 100K rows -- delete 1000 at a time in a loop)
3. Return a summary: `{"tasks_deleted": 342, "groups_deleted": 18}`

### Step 3: Add a Dry-Run Mode

Both tasks should accept an optional `dry_run` parameter (default `True` for safety). In dry-run mode, the task finds and counts orphans/expired records but does not delete anything. Log what would be deleted.

When called from the schedule, pass `dry_run=False`. When triggered manually (next step), let the admin choose.

### Step 4: Create Admin Maintenance Endpoints

Create these admin-only endpoints (require admin role from your RBAC system):

- `POST /admin/maintenance/cleanup-images`: triggers `cleanup_orphaned_images` immediately. Accept a `dry_run` query parameter (default True). Returns the Celery task ID.
- `POST /admin/maintenance/cleanup-tasks`: triggers `cleanup_expired_tasks` immediately. Same pattern.
- `GET /admin/maintenance/stats`: returns current counts -- total S3 objects, total DB references, orphan estimate, expired task count. This is a read-only diagnostic, no deletions.

### Step 5: Add S3 List Objects to StorageService

Your `StorageService` from Chapter 25 needs a new method: `list_objects(prefix: str) -> list[str]`. This uses the S3 `list_objects_v2` API to list all keys under a prefix. Handle pagination -- S3 returns max 1000 keys per request, so you need to loop using the `ContinuationToken`.

For the worker (synchronous), create a sync version or use boto3 directly in the maintenance task.

### Step 6: Test the Full Flow

1. Start Celery Beat: `celery -A app.worker.celery_app beat --loglevel=info`
2. Start a worker: `celery -A app.worker.celery_app worker --loglevel=info`
3. Manually upload a file to S3 via MinIO console (an orphan)
4. Call `POST /admin/maintenance/cleanup-images?dry_run=false`
5. Verify the orphan was detected and deleted

Also test the safety threshold -- upload 150 fake objects to S3 and verify the task refuses to delete them (threshold exceeded).

## Expected Outcome
- Celery Beat is running and triggers cleanup tasks on schedule
- `POST /admin/maintenance/cleanup-images?dry_run=true` reports orphans without deleting
- `POST /admin/maintenance/cleanup-images?dry_run=false` finds and deletes orphaned S3 objects
- `POST /admin/maintenance/cleanup-tasks` removes expired task records
- The safety threshold prevents mass deletion if something looks wrong
- `GET /admin/maintenance/stats` returns current system health metrics
- Non-admin users cannot access these endpoints

## Hints
- Start Celery Beat with: `celery -A app.worker.celery_app beat --loglevel=info` (run this alongside the worker, not instead of it)
- The `list_objects_v2` S3 API paginates with `IsTruncated` and `NextContinuationToken`. Loop until `IsTruncated` is False.
- For batch deleting in the database, use `DELETE FROM tasks WHERE id IN (SELECT id FROM tasks WHERE ... LIMIT 1000)` in a loop
- Be careful with timezone-aware vs naive datetimes when computing "older than 7 days"

## What I'll Look For In Review
- The Beat schedule is configured in the Celery app config, not scattered across files
- Dry-run mode is the default, preventing accidental data loss
- The orphan cleanup has a safety threshold to prevent catastrophic mass deletion
- Batch deletes use chunking rather than a single unbounded DELETE
- Admin endpoints are properly protected with RBAC
