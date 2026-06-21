# Chapter 5 — Error Handling & Custom Exceptions

## Concepts You'll Learn
- `HTTPException` and when to use it
- Custom exception classes for domain-specific errors
- Exception handlers for consistent error response formatting
- Preventing information leakage in production

## Concept Deep Dive

### HTTPException

FastAPI provides `HTTPException` for returning HTTP error responses. You've already used it for 404s, but it's worth understanding what it actually does.

```python
from fastapi import HTTPException

raise HTTPException(status_code=404, detail="Manga not found")
```

When you raise `HTTPException`, FastAPI catches it, stops executing your endpoint function, and returns the specified status code with a JSON body like `{"detail": "Manga not found"}`. This is FastAPI's built-in error mechanism, and for simple cases it works fine.

But there's a problem: as your application grows, `HTTPException` becomes limiting. The error response shape (`{"detail": "..."}`) is baked in. Every error looks the same — a 404 for a missing manga, a 404 for a missing user, a 409 for a duplicate slug, a 422 for a validation error — they all share the same flat structure. Your API clients have no reliable way to programmatically distinguish between different error types. They can check the status code, but multiple unrelated errors can share the same code.

### Custom Exception Classes

The solution is to define your own exception hierarchy. Create a base exception for your application, then derive specific exceptions from it:

```python
class MangaShelfException(Exception):
    def __init__(self, message: str, code: str, status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)

class NotFoundException(MangaShelfException):
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            message=f"{resource} with id '{resource_id}' not found",
            code="NOT_FOUND",
            status_code=404,
        )
```

Now your endpoints raise domain-specific exceptions:

```python
raise NotFoundException(resource="Manga", resource_id=str(manga_id))
```

This is more expressive than `HTTPException(status_code=404, detail="Manga not found")`. It carries structured information (which resource, which ID) that can be formatted into a consistent response.

### Exception Handlers

Custom exceptions alone aren't enough — FastAPI doesn't know what to do with them. You need to register exception handlers that catch these exceptions and convert them to proper HTTP responses.

```python
from fastapi import Request
from fastapi.responses import JSONResponse

async def mangashelf_exception_handler(request: Request, exc: MangaShelfException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        },
    )

# In main.py
app.add_exception_handler(MangaShelfException, mangashelf_exception_handler)
```

Because `NotFoundException` inherits from `MangaShelfException`, the handler catches all your custom exceptions. Every error response now follows the same structure: `{"error": {"code": "...", "message": "..."}}`. Your API clients can check `error.code` to handle specific cases programmatically.

You should also override the default handlers for `HTTPException` (for consistency), `RequestValidationError` (Pydantic validation failures, normally 422), and generic `Exception` (the catch-all for unexpected errors).

### Preventing Information Leakage

In development, you want as much detail as possible — stack traces, internal error messages, the works. In production, leaking these details is a security risk. A stack trace might reveal your file structure, library versions, or database schema to an attacker.

The pattern is simple: check your `DEBUG` setting in the exception handler:

```python
async def generic_exception_handler(request: Request, exc: Exception):
    if settings.DEBUG:
        detail = str(exc)
    else:
        detail = "An internal error occurred"

    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": detail}},
    )
```

This way, during development you see the actual error, but in production the client only sees a generic message. The actual error should still be logged server-side (you'll set up proper logging in Chapter 7).

## Your Task

### Step 1: Create the exceptions module

Create `app/core/__init__.py` and `app/core/exceptions.py`. Define:

- `MangaShelfException` — base exception with `message`, `code`, `status_code`, and optional `details` (a dict for extra context)
- `NotFoundException` — for missing resources (404), takes `resource` and `resource_id`
- `AlreadyExistsException` — for duplicate resources (409), takes `resource` and `field` (e.g., "slug")
- `ValidationException` — for business logic validation failures (422), takes a list of error details

### Step 2: Create exception handlers

Create `app/core/error_handlers.py` (or put them in the exceptions module). Define handlers for:

- `MangaShelfException` — returns the structured error response
- `RequestValidationError` (from `fastapi.exceptions`) — reformat Pydantic validation errors into your consistent error shape
- `HTTPException` — wrap FastAPI's built-in exceptions in your error format
- `Exception` — catch-all for unexpected errors, hide details in non-debug mode

All error responses should follow this shape:

```json
{
    "error": {
        "code": "NOT_FOUND",
        "message": "Manga with id '...' not found",
        "details": null
    }
}
```

### Step 3: Register handlers in main.py

In `app/main.py`, import and register all exception handlers using `app.add_exception_handler(...)`. Make sure to import the exception types from the correct modules (`starlette.exceptions.HTTPException` for the generic one, `fastapi.exceptions.RequestValidationError` for validation errors).

### Step 4: Refactor existing endpoints

Go back to your manga endpoints and replace any `HTTPException` raises with your new custom exceptions. The `GET /{manga_id}` 404 should now use `NotFoundException`.

### Step 5: Test error consistency

Verify that all of these return the same JSON shape:
- Request a nonexistent manga (404)
- POST with invalid body (422 validation)
- Any 404 path (`/api/v1/nonexistent`)
- Force a 500 error (temporarily add `raise Exception("test")` in an endpoint)

## Expected Outcome
- All error responses follow the `{"error": {"code": "...", "message": "...", "details": ...}}` shape
- `NotFoundException` returns 404 with code `"NOT_FOUND"`
- Pydantic validation errors return 422 with code `"VALIDATION_ERROR"` and details containing field-level errors
- A generic unhandled exception returns 500 with code `"INTERNAL_ERROR"` and hides the traceback
- No stack traces are visible in API responses (they should only appear in server logs)

## Hints
- You need to import `HTTPException` from `starlette.exceptions` (not `fastapi`) when registering the handler for it. FastAPI's `HTTPException` is a subclass, and the handler registration needs the base class.
- `RequestValidationError` has an `.errors()` method that returns a list of error dicts from Pydantic.
- When reformatting validation errors, extract the `loc` (location/field path), `msg` (message), and `type` (error type) from each error.
- The catch-all `Exception` handler is your safety net. In production, always log the full traceback server-side even if you hide it from the client.

## What I'll Look For In Review
- A clean exception hierarchy with a common base class in `app/core/exceptions.py`
- All four exception handlers registered (custom, validation, HTTP, generic)
- Consistent error response shape across all error types
- No sensitive information leaked in non-debug mode
- Existing endpoints refactored to use custom exceptions instead of raw `HTTPException`
