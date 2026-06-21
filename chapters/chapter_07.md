# Chapter 7 — Middleware, Lifespan, and Request Logging

## Concepts You'll Learn
- ASGI middleware and how the request/response pipeline works
- Lifespan events (startup/shutdown) for app lifecycle management
- Request ID injection for tracing
- Structured logging with Python's `logging` module

## Concept Deep Dive

### ASGI Middleware

Middleware is code that runs on every request and every response, wrapping around your endpoint logic. Think of it like airport security: every passenger (request) goes through it on the way in, and every passenger (response) goes through it on the way out. Middleware can inspect, modify, or even reject requests before they reach your endpoint.

In FastAPI, middleware follows the ASGI pattern. You get a `call_next` function that passes the request to the next middleware (or eventually to your endpoint), and returns the response:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # BEFORE the endpoint runs
        start_time = time.time()

        response = await call_next(request)

        # AFTER the endpoint runs
        duration = time.time() - start_time
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")

        return response
```

The order in which you add middleware matters. Middleware is applied in reverse order — the last middleware you add is the first to handle the request (outermost layer). Think of it like wrapping a gift in layers of paper: you wrap from inside out, but when unwrapping (processing), you go from outside in.

An important note: `BaseHTTPMiddleware` is convenient but has known limitations with streaming responses and can add overhead. For production-grade middleware, you can write a pure ASGI middleware class, but `BaseHTTPMiddleware` is perfectly fine for learning and most use cases.

### Lifespan Events

Your application needs to do certain things exactly once: connect to the database on startup, close the connection pool on shutdown, warm up caches, etc. FastAPI uses a "lifespan" context manager for this:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: runs before the app accepts requests
    logger.info("MangaShelf starting up...")
    # Initialize resources here

    yield  # App runs and handles requests

    # Shutdown: runs when the app is stopping
    logger.info("MangaShelf shutting down...")
    # Clean up resources here
```

The `yield` is the dividing line. Everything before it is startup logic; everything after is shutdown logic. You pass this lifespan to the `FastAPI` constructor: `app = FastAPI(lifespan=lifespan)`.

This replaces the older `@app.on_event("startup")` and `@app.on_event("shutdown")` decorators, which are now deprecated. The lifespan approach is better because it naturally handles resource cleanup (if startup creates something, the code after `yield` cleans it up) and makes the startup/shutdown relationship explicit.

### Request ID Injection

When something goes wrong in production and you're looking through thousands of log lines, how do you find all the logs related to one specific request? Request IDs solve this. Every request gets a unique identifier, and every log line for that request includes it.

The flow is:
1. Middleware checks if the incoming request has an `X-Request-ID` header (maybe set by a load balancer).
2. If not, generate a new UUID.
3. Attach it to the request state so endpoint code can access it.
4. Include it in the response headers so the client can reference it in bug reports.
5. Include it in every log line produced during that request.

```python
import uuid

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response
```

Now when a user reports "I got an error," they can give you the request ID from the response header. You search your logs for that ID and instantly find every log line for their request.

### Structured Logging

Python's built-in `logging` module is powerful but defaults to unstructured text. A log line like `INFO: Processed request` is human-readable but hard to parse programmatically. Structured logging formats each log entry with consistent fields:

```
2024-01-15T10:30:45.123Z | INFO | request_id=abc-123 | method=GET | path=/api/v1/manga | status=200 | duration=0.045s
```

You configure this by setting up a custom formatter:

```python
import logging

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        # Build a structured log string from the record
        ...
```

Or, more practically, configure a format string that includes the fields you care about:

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
```

For production, you'd often use JSON-formatted logs (so log aggregation tools like ELK or Datadog can parse them), but for development, a clean pipe-delimited format is easier to read.

## Your Task

### Step 1: Set up structured logging

Create `app/core/logging.py` with a function `setup_logging()` that configures Python's logging module. It should:
- Set the root logger level based on `DEBUG` setting (DEBUG level in debug mode, INFO otherwise)
- Use a structured format with timestamp, level, logger name, and message
- Suppress noisy loggers (uvicorn's access log, SQLAlchemy's engine logger) to WARNING level

Call `setup_logging()` in your lifespan startup.

### Step 2: Create the request logging middleware

Create `app/middleware/__init__.py` and `app/middleware/logging.py`. Build a middleware that logs every request with:
- HTTP method
- URL path
- Response status code
- Duration in milliseconds

Use Python's `time.time()` or `time.perf_counter()` to measure duration. Log at INFO level for successful requests (2xx, 3xx) and WARNING level for errors (4xx, 5xx).

### Step 3: Create the request ID middleware

Create `app/middleware/request_id.py` with middleware that:
- Reads `X-Request-ID` from the incoming request headers
- If not present, generates a UUID4
- Stores it on `request.state.request_id`
- Adds `X-Request-ID` to the response headers

### Step 4: Create the lifespan

In `app/main.py` (or a separate `app/core/lifespan.py` if you prefer), create an `asynccontextmanager` lifespan function that:
- On startup: calls `setup_logging()`, logs "MangaShelf v{version} starting up", logs the settings values (but NOT the secret key — never log secrets)
- On shutdown: logs "MangaShelf shutting down"

Pass this lifespan to the `FastAPI()` constructor.

### Step 5: Wire middleware into the app

In `app/main.py`, add both middleware to the app. Remember middleware order matters — add the request ID middleware first (so it's the outermost layer and the logging middleware can include the request ID).

### Step 6: Include request ID in log lines

Update your logging middleware to include the request ID from `request.state.request_id` in the log output. This ties every logged line to a specific request.

## Expected Outcome
- Every HTTP request produces a structured log line: `GET /api/v1/manga 200 45ms [req_id=abc-123]`
- Every response includes an `X-Request-ID` header
- If you send a request with `X-Request-ID: my-custom-id`, that same ID appears in the response and logs
- Startup logs show "MangaShelf starting up" with app name and version
- Shutdown (Ctrl+C) logs show "MangaShelf shutting down"
- Error responses (404, 422) log at WARNING level, not INFO

## Hints
- `time.perf_counter()` is more precise than `time.time()` for measuring short durations.
- To access `request.state.request_id` in the logging middleware, the request ID middleware must run first (wrap the request before the logging middleware sees it).
- The lifespan function receives the `app` instance as a parameter even if you don't use it.
- If you want the request ID available in the logging middleware, add the request ID middleware after the logging middleware (remember: last added = outermost = runs first).

## What I'll Look For In Review
- Logging middleware records method, path, status code, and duration for every request
- Request ID middleware generates or preserves `X-Request-ID` and adds it to responses
- Lifespan correctly handles startup and shutdown with meaningful log messages
- No secrets (SECRET_KEY, DATABASE_URL passwords) appear in startup logs
- Middleware is added to the app in the correct order
