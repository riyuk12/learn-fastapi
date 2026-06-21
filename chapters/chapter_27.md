# Chapter 27 — Celery & Redis: Async Task Queue

## Concepts You'll Learn
- Why task queues exist and when to offload work from the request cycle
- Celery architecture: broker, worker, result backend
- Redis as a message broker
- The difference between the task lifecycle and the request lifecycle

## Concept Deep Dive

### Why Task Queues Exist

In Chapter 26, you built image processing that resizes, converts, and generates blurhashes for uploaded pages. Right now, all of that happens inside the HTTP request handler. If a user uploads a 5MB manga page, the request blocks for 2-5 seconds while Pillow crunches pixels and S3 uploads complete. The user stares at a spinner. The web server thread/coroutine is occupied. If 50 users upload simultaneously, your server stalls.

The rule of thumb: **if it takes longer than ~200ms and the user does not need the result immediately, do it in the background.** Image processing, sending emails, generating reports, syncing search indexes -- these are all background tasks. The HTTP request should acknowledge the work ("got it, processing") and return immediately. A separate worker process picks up the job and completes it asynchronously.

This is the same principle as dropping off dry cleaning. You hand over the clothes (submit the task), get a receipt with a ticket number (task ID), and come back later to pick up the result (poll for status). You do not stand at the counter watching them clean your shirts.

### Celery Architecture

Celery is Python's most mature distributed task queue. It has three components:

1. **Broker**: The message queue that holds tasks waiting to be executed. Think of it as the to-do list. Celery supports Redis, RabbitMQ, and SQS as brokers. You will use Redis.

2. **Worker**: A separate process that watches the broker, picks up tasks, and executes them. You can run multiple workers for parallelism. Workers are completely separate from your FastAPI app -- they are their own Python processes.

3. **Result Backend**: Where completed task results are stored. Also Redis in your case. This lets you query "is task X done?" and "what was the result?"

```
FastAPI App  --(sends task)-->  Redis Broker  --(delivers to)-->  Celery Worker
                                                                        |
                                                                  (stores result)
                                                                        |
                                                                  Redis Backend
```

Your FastAPI app never processes images itself. It sends a message to Redis saying "process this image." A Celery worker, running in its own process (or container), picks up the message and does the heavy lifting.

### Redis as Message Broker

You already know Redis is an in-memory data store. As a Celery broker, it acts as a queue: your app pushes task messages to a Redis list, and workers pop messages off the list. Redis is fast enough for most workloads (tens of thousands of tasks per second) and you are already going to use it for caching later (Chapters 41-43), so it avoids adding another infrastructure dependency.

The Celery configuration is straightforward:

```python
from celery import Celery

celery_app = Celery(
    "mangashelf",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
)
```

Note the use of different Redis databases (`/0` for broker, `/1` for results). Redis supports 16 databases (0-15) by default. Separating them keeps things organized.

### Task vs Request Lifecycle

This distinction is critical. The **request lifecycle** is: receive HTTP request, validate, process, respond. It should complete in milliseconds. The **task lifecycle** is: enqueue, wait in queue, start processing, complete (or fail and retry). It can take seconds, minutes, or hours.

When your endpoint receives a page upload, it should:
1. Save the original file to S3 (fast, a few hundred ms)
2. Enqueue a Celery task with the S3 key and metadata
3. Return HTTP 202 Accepted with a task ID

The `202 Accepted` status code is semantically perfect -- it means "I received your request and it is being processed, but I have not completed it yet." This is different from `201 Created`, which implies the resource is fully ready.

```python
@router.post("/chapters/{chapter_id}/pages", status_code=202)
async def upload_page(chapter_id: int, file: UploadFile):
    # Save original to S3
    s3_key = await storage.upload_file(key, file_bytes, content_type)
    # Create page record with status="processing"
    page = await page_service.create(chapter_id, s3_key)
    # Enqueue background processing
    task = process_page_image.delay(page.id, s3_key)
    return {"page_id": page.id, "task_id": task.id, "status": "processing"}
```

The worker picks up the task, generates variants and blurhash, updates the database record, and the page is ready. The client can poll for the task status or simply check the page record later.

## Your Task

### Step 1: Run Redis via Docker

Start a Redis container on port 6379. This is simpler than MinIO -- Redis needs no special configuration for basic usage.

### Step 2: Add Celery Dependencies

Add `celery[redis]` to your requirements. The `[redis]` extra installs the Redis transport. Also add `redis` (the Python client) since you will use it in later chapters too.

### Step 3: Create the Celery App

Create `app/worker/celery_app.py`. This file defines the Celery application instance and its configuration. It should:

- Read broker and backend URLs from your app config (reference `app/core/config.py`)
- Set JSON serialization for tasks and results
- Enable `task_track_started` so you can see when a task moves from "pending" to "started"
- Configure task routes if you want to separate image tasks onto specific queues (optional but good practice)
- Auto-discover tasks from `app/worker/tasks/`

### Step 4: Create the Image Processing Task

Create `app/worker/tasks/image_tasks.py` with a `process_page_image` task:

1. Accept `page_id` and `s3_key_original` as arguments
2. Download the original image from S3 using boto3 (note: Celery workers are synchronous by default, so use regular boto3, not aioboto3)
3. Use `ImageProcessor` from Chapter 26 to generate: medium (800px), thumbnail (200px), blurhash, and dimensions
4. Upload the two variants to S3
5. Update the Page record in the database with the new S3 keys, dimensions, and blurhash
6. Handle errors: if processing fails, update the page status to "failed" with an error message

Important: the Celery worker runs in a separate process. It needs its own database session and S3 client -- it cannot share the FastAPI app's connections. Create a simple sync database session factory for the worker.

### Step 5: Add a Processing Status to Pages

Add a `processing_status` column to the Page model with values: `pending`, `processing`, `completed`, `failed`. The upload endpoint sets it to `pending`. The task sets it to `processing` when it starts, `completed` when done, `failed` on error. Create the Alembic migration.

### Step 6: Refactor the Page Upload Endpoint

Modify the page upload endpoint to:

1. Validate the uploaded file (type, size)
2. Upload the original to S3
3. Create the Page record with `processing_status="pending"` and only the `s3_key_original`
4. Call `process_page_image.delay(page_id, s3_key)` to enqueue the task
5. Return 202 Accepted with the page ID and Celery task ID

### Step 7: Test the Full Flow

Start the Celery worker in a terminal alongside your FastAPI app:

```bash
celery -A app.worker.celery_app worker --loglevel=info
```

Upload a page image. Watch the worker terminal -- you should see it pick up the task, process the image, and complete. Check MinIO for the three variants. Check the database for the updated Page record.

## Expected Outcome
- Redis is running in Docker
- The Celery worker starts without errors and connects to Redis
- Uploading a page returns HTTP 202 immediately (under 1 second)
- The worker logs show the task being picked up and processed
- After processing, the Page record has all three S3 keys, dimensions, blurhash, and `processing_status="completed"`
- All three image variants appear in MinIO
- If you stop the worker and upload, the task queues up. Starting the worker processes the backlog.

## Hints
- The Celery worker is a separate Python process. Make sure it can import your app modules. Run it from the project root directory.
- For the worker's database access, create a simple synchronous SQLAlchemy session since Celery tasks are sync by default. You can put this in `app/worker/db.py`.
- If tasks are not being picked up, check that the broker URL in your Celery config matches the running Redis instance.
- Use `task.delay(arg1, arg2)` as shorthand for `task.apply_async(args=[arg1, arg2])`. Both enqueue the task.

## What I'll Look For In Review
- The Celery app configuration is clean and reads from the central config, not hardcoded values
- The worker has its own database session management, separate from FastAPI's async sessions
- The upload endpoint returns 202, not 200 or 201, reflecting that processing is incomplete
- Error handling in the task updates the page status to "failed" rather than silently crashing
- The task arguments are serializable (primitive types like int and str, not ORM objects or file handles)
