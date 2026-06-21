# Chapter 63 — Structured Logging with Correlation

## Concepts You'll Learn
- Why structured logging (JSON) over plain text
- The structlog library for Python
- Correlation IDs for request tracing across services
- Log levels and when to use each

## Concept Deep Dive

### Why Structured Logging

Back in Chapter 7, you set up Python's standard `logging` module, which produces plain-text log lines like:

```
2024-01-15 10:23:45 INFO Processing manga upload for user abc123
```

This is readable by humans but terrible for machines. When you have thousands of log lines per minute across multiple services, you need to search, filter, and aggregate logs. Searching for "all requests from user abc123 that took over 500ms" in plain text requires complex regex. With structured (JSON) logging, it is a simple field-based query:

```json
{"timestamp": "2024-01-15T10:23:45Z", "level": "info", "event": "manga.upload.started", "user_id": "abc123", "manga_id": "def456", "service": "api"}
```

Log aggregation systems (ELK Stack, Grafana Loki, CloudWatch) parse JSON natively. You can filter by any field, build dashboards from log data, and set up alerts on specific event patterns. Structured logging turns your logs from write-only output into queryable data.

The key shift is thinking of each log entry as a data event with typed fields, not a prose sentence. Instead of `logger.info(f"User {user_id} uploaded {count} pages")`, you write `logger.info("pages.uploaded", user_id=user_id, count=count)`. The event name is a dot-separated identifier, and the context is key-value pairs.

### The structlog Library

`structlog` is a Python library that makes structured logging ergonomic. It wraps standard logging (or can work standalone) and provides a pipeline of processors that transform log events before output.

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

log = structlog.get_logger()
log.info("manga.created", manga_id="abc123", title="One Piece")
# Output: {"event": "manga.created", "manga_id": "abc123", "title": "One Piece", "level": "info", "timestamp": "2024-01-15T10:23:45Z"}
```

The processor pipeline is powerful. Each processor transforms the event dictionary. Common processors add timestamps, log levels, caller information, or format the output. You can write custom processors to add application-specific context (like the service name or deployment environment).

`structlog` also supports **context variables** (via `contextvars`). You can bind context once at the beginning of a request, and every log call within that request automatically includes that context. This is the foundation for correlation IDs.

### Correlation IDs

In a microservice or multi-component system, a single user action (like uploading a manga chapter) might touch the API, a Celery worker, and MinIO. Logs from each component are interleaved with logs from other requests. How do you find all logs related to a single request?

A **correlation ID** (also called request ID or trace ID) is a unique identifier assigned at the start of a request and propagated through every component that handles it. Every log entry includes the correlation ID, so you can filter all logs for a single request across services.

```python
# In middleware: assign a request ID
import uuid
from structlog.contextvars import bind_contextvars, clear_contextvars

async def logging_middleware(request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    clear_contextvars()
    bind_contextvars(request_id=request_id, user_id=None)

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
```

The critical part is propagation. When the API enqueues a Celery task, the request ID must travel with the task:

```python
# When creating a Celery task, pass the request_id in headers
task.apply_async(args=[...], headers={"request_id": request_id})

# In the Celery worker, extract it
@celery_app.task(bind=True)
def process_upload(self, *args):
    request_id = self.request.get("request_id", "no-request-id")
    bind_contextvars(request_id=request_id)
    log.info("upload.processing_started")
```

Now, searching for `request_id=abc-123` in your log aggregation system returns every log from the API endpoint, the Celery task, and any other component that touched this request.

### Log Levels

Choosing the right log level is an underappreciated skill. Each level communicates different urgency:

- **DEBUG**: Fine-grained diagnostic information. SQL queries, cache hits/misses, internal state. Noisy — only enable in development or when investigating issues.
- **INFO**: Normal operations worth recording. Request started/completed, user logged in, manga created. This is your primary production level.
- **WARNING**: Something unexpected but recoverable. A retry happened, a cache miss fell through to the database, a deprecated endpoint was called.
- **ERROR**: Something failed and needs attention. An unhandled exception, a failed external service call, a data integrity issue.
- **CRITICAL**: The system cannot continue. Database connection pool exhausted, out of disk space, unrecoverable state.

The rule of thumb: if you would page someone at 3am, it is ERROR or CRITICAL. If you would investigate during business hours, it is WARNING. If you want to understand normal behavior, it is INFO. If you are debugging a specific issue, it is DEBUG.

## Your Task

### Step 1: Install and Configure structlog

Install `structlog`. Create `app/core/logging.py` that configures structlog with:
- JSON output renderer (for production) with fallback to console renderer (for development, based on DEBUG setting)
- Timestamp processor (ISO format)
- Log level processor
- Context variables processor (for request_id, user_id)
- Service name processor (adds `"service": "api"` or `"service": "worker"` to every event)

### Step 2: Create Logging Middleware

Replace your existing logging middleware from Chapter 7 with a new version that:
- Generates or reads `X-Request-ID` from the incoming request header
- Binds `request_id` to structlog context variables (so all logs in this request include it)
- Binds `user_id` after authentication (if available)
- Logs request start and completion with: method, path, status code, duration in milliseconds
- Returns the `X-Request-ID` in the response header

### Step 3: Replace Existing Log Calls

Go through your service layer and replace `logging.getLogger()` calls with `structlog.get_logger()`. Update log messages to use structured format:

Before:
```python
logger.info(f"Created manga '{title}' with ID {manga_id}")
```

After:
```python
log.info("manga.created", manga_id=str(manga_id), title=title)
```

Update at least: manga service, auth service, upload service, notification service, and any service with significant logging.

### Step 4: Propagate Correlation to Celery

Modify your Celery task creation to pass the `request_id` via task headers. Create a Celery base task class or signal handler that extracts the `request_id` from task headers and binds it to structlog context variables at the start of each task.

### Step 5: Add Contextual Logging in Key Flows

Add structured log events in critical paths:
- Auth: `auth.login.success`, `auth.login.failed`, `auth.token.refreshed`
- Manga: `manga.created`, `manga.updated`, `chapter.created`, `pages.uploaded`
- Reading: `reading.progress.saved`, `reading.session.completed`
- Notifications: `notification.created`, `notification.fan_out.completed` (with `recipient_count`)

Each event should include relevant IDs and metadata, not prose descriptions.

### Step 6: Configure Log Levels per Environment

In your settings:
- Development: LOG_LEVEL=debug, console (colorized) output
- Production: LOG_LEVEL=info, JSON output
- Make the renderer choice based on the DEBUG setting

## Expected Outcome
- All logs are structured JSON in production mode
- Every log entry includes: timestamp, level, event name, request_id
- Authenticated request logs include user_id
- A single request is traceable from API through Celery by filtering on request_id
- Development mode shows human-readable colored output
- Log events use dot-separated naming convention (service.resource.action)

## Hints
- `structlog.contextvars.bind_contextvars()` makes context available to all structlog loggers in the current async task. Call `clear_contextvars()` at the start of each request to prevent context leaking between requests.
- For Celery, the `task_prerun` signal is a good place to bind context variables. The `task_postrun` signal is where you clear them.
- If you use `structlog.stdlib.BoundLogger` as your wrapper, structlog integrates with Python's standard logging (capturing logs from third-party libraries too).
- For development, `structlog.dev.ConsoleRenderer()` produces colored, human-readable output. Use it when DEBUG is true.

## What I'll Look For In Review
- structlog is properly configured with the right processor chain
- Correlation IDs are generated per request and propagated to Celery tasks
- Log events use structured key-value format, not f-string prose
- Different output formats for development (console) vs production (JSON)
- Request start/end logs include method, path, status code, and duration
