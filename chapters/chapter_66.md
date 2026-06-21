# Chapter 66 — Sentry Error Tracking

## Concepts You'll Learn
- Error tracking vs logging (complementary, not redundant)
- Sentry SDK integration with FastAPI
- Breadcrumbs for context and release tracking
- Performance monitoring with traces

## Concept Deep Dive

### Error Tracking vs Logging

You might wonder: "I already have structured logging from Chapter 63. Why do I need Sentry?" Logging and error tracking solve different problems and complement each other.

**Logging** records everything: request flows, business events, debug data, warnings, and errors. Logs are high-volume, relatively unstructured even in JSON format, and require you to search through them to find problems. They answer "what happened during this request?"

**Error tracking** focuses exclusively on exceptions and failures. Sentry captures the full stack trace, groups identical errors (so you see "this error happened 47 times in the last hour" rather than 47 separate log entries), shows which release introduced the error, tracks whether errors are new or recurring, and provides rich context (the exact request that triggered it, the user who experienced it, system state at the time).

Think of it this way: logging is a chronological record (like a journal), while error tracking is an issue tracker (like a bug report with full diagnostics attached). You need both. Logs tell you the story of what your system did. Sentry tells you when something went wrong and helps you fix it.

### Sentry SDK Integration

The `sentry-sdk` package integrates deeply with FastAPI (via its ASGI integration). When configured, it automatically captures unhandled exceptions from request handlers, Celery tasks, and database operations.

```python
import sentry_sdk

sentry_sdk.init(
    dsn="https://examplePublicKey@o0.ingest.sentry.io/0",
    environment="production",
    release="mangashelf@1.2.3",
    traces_sample_rate=0.1,  # 10% of requests get performance traces
    send_default_pii=False,  # don't send personally identifiable information
)
```

The **DSN** (Data Source Name) is a URL that identifies your Sentry project. It is a project-level credential, not a user secret — it is safe to include in client-side code (though keeping it in environment variables is still best practice).

The **environment** tag distinguishes errors from development, staging, and production. Without it, your Sentry dashboard mixes test errors with real production issues.

The **release** tag ties errors to a specific code version. When you deploy a new release and errors appear, Sentry can tell you "this error was introduced in release 1.2.3." This is extraordinarily useful for quickly identifying which deployment broke something.

### Breadcrumbs

Sentry breadcrumbs are a trail of events leading up to an error. They are like a black box recorder on an airplane — when something crashes, you can see what happened in the minutes before. The SDK automatically captures breadcrumbs for HTTP requests, database queries, log messages, and user actions.

You can also add custom breadcrumbs:

```python
sentry_sdk.add_breadcrumb(
    category="manga",
    message=f"Fetched manga {manga_id}",
    level="info",
    data={"manga_id": str(manga_id), "page_count": page_count},
)
```

When an error occurs, Sentry shows the most recent breadcrumbs in chronological order. This gives you context that a stack trace alone cannot: "The user fetched manga X, then opened chapter 5, then tried to upload pages — and the upload failed with a TypeError." Without breadcrumbs, you only see the TypeError.

Breadcrumbs are capped (typically 100 most recent) and are lightweight (they do not create separate Sentry events). Use them liberally for any action that helps reconstruct the sequence of events.

### Performance Monitoring

Sentry's performance monitoring captures **transactions** (end-to-end traces of operations) and **spans** (sub-operations within a transaction). This is complementary to Prometheus metrics from Chapter 64 — Prometheus tells you "P99 latency is 2 seconds," but Sentry tells you "this specific slow request spent 1.8 seconds in the database and here is the SQL."

The `traces_sample_rate` controls what percentage of requests are traced. Set it to 1.0 in development (trace everything) and 0.1 in production (trace 10%, enough for statistical insight without overwhelming Sentry with data).

The FastAPI integration automatically creates transactions for each request. Database queries, HTTP calls to external services, and Celery task executions are captured as spans within the transaction. You can add custom spans:

```python
with sentry_sdk.start_span(op="image.process", description="Resize cover image"):
    processed = resize_image(image, target_size)
```

This shows up in Sentry's performance waterfall as a discrete step, making it easy to identify which part of a request is slow.

## Your Task

### Step 1: Create a Sentry Project

Create a free account at sentry.io. Create a new project, selecting "FastAPI" as the platform. Sentry gives you a DSN — save this for configuration.

### Step 2: Install and Configure Sentry SDK

Install `sentry-sdk[fastapi]`. Create `app/core/sentry.py` with an initialization function:
- Read the DSN from environment variables (SENTRY_DSN)
- Set `environment` from your app settings (dev/staging/prod)
- Set `release` to a version string — ideally derived from git (e.g., `git describe --tags` or the latest commit SHA)
- Set `traces_sample_rate` based on environment (1.0 for dev, 0.1 for prod)
- Set `send_default_pii=False` (do not send user emails/IPs to Sentry by default)

Call this initialization function in your `app/main.py` lifespan or at module import time (Sentry needs to initialize early to capture all errors).

### Step 3: Add User Context

Create a middleware or modify your existing auth middleware to set Sentry user context after authentication:

```python
sentry_sdk.set_user({
    "id": str(user.id),
    "username": user.username,
    "role": user.role,
})
```

This attaches the user to any error that occurs during their request. Do not include the email (PII) unless your privacy policy allows it.

### Step 4: Add Custom Breadcrumbs

Add breadcrumbs in key service operations:
- When a manga is fetched (category: "manga")
- When a search is performed (category: "search", include the query)
- When a file is uploaded (category: "upload", include file size)
- When a Celery task is enqueued (category: "task", include task name)

### Step 5: Configure Celery Integration

The Sentry SDK has a Celery integration that automatically captures task failures. Ensure it is active:

```python
sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    integrations=[
        # The FastAPI and Celery integrations are auto-discovered
        # but you can be explicit
    ],
)
```

Verify that Celery task errors appear in Sentry with the correct task name and arguments.

### Step 6: Test Error Tracking

Create a temporary test endpoint that deliberately raises an exception:

```python
@router.get("/debug/sentry-test")
async def test_sentry():
    raise ValueError("This is a test error for Sentry")
```

Hit this endpoint and verify the error appears in your Sentry dashboard with:
- Full stack trace
- Request data (URL, method, headers)
- User context (if authenticated)
- Breadcrumbs from preceding operations
- Environment and release tags

Remove this endpoint after testing (or guard it behind admin-only access).

### Step 7: Configure Sentry for Production

Add SENTRY_DSN to your environment templates:
- `dev.env`: Set the DSN (useful for testing the integration)
- `prod.env`: Set the DSN with production traces_sample_rate
- Both: Optionally add SENTRY_TRACES_SAMPLE_RATE as a configurable variable

Update your Settings class to include Sentry configuration:
- `SENTRY_DSN: str | None = None` (None means Sentry is disabled — useful for local dev without Sentry)
- Only call `sentry_sdk.init()` if DSN is set

## Expected Outcome
- Unhandled exceptions in endpoints appear in Sentry with full context
- Celery task failures appear in Sentry
- Errors are grouped (duplicate errors are counted, not listed separately)
- User context is attached to authenticated request errors
- Breadcrumbs show the sequence of events leading to an error
- Release tracking ties errors to specific deployments
- Performance traces show request waterfalls with database queries

## Hints
- Sentry's `before_send` callback lets you filter or modify events before they are sent. You can use this to scrub sensitive data or drop certain error types.
- If you see too many "expected" errors (like 404 Not Found), use `before_send` to filter them. Not every HTTP error is a bug worth tracking.
- The release version is most useful when it matches your git state. In CI/CD (Chapter 62), set it to the git SHA: `release=f"mangashelf@{git_sha}"`.
- Sentry has a free tier that is generous enough for development and small production deployments.

## What I'll Look For In Review
- Sentry initializes conditionally (only when DSN is configured)
- User context is set without leaking PII
- Custom breadcrumbs are added in key code paths
- Release is set to a meaningful version identifier
- Error filtering prevents noise (404s, validation errors) from cluttering the dashboard
