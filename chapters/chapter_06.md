# Chapter 6 — Configuration & Environment Variables

## Concepts You'll Learn
- Using `pydantic-settings` for typed configuration
- `.env` files and how they integrate with settings
- The settings singleton pattern and `get_settings` dependency
- The 12-factor app principle for configuration

## Concept Deep Dive

### The 12-Factor App Config Principle

The Twelve-Factor App is a set of best practices for building software-as-a-service applications. Factor III says: **store config in the environment**. Configuration here means anything that varies between deployments — database URLs, API keys, debug flags, allowed origins.

Why environment variables instead of config files checked into Git? Because environment-specific values (your local DB password vs the production DB password) should never be in your codebase. A single codebase should run in development, staging, and production without modification — only the environment variables change.

The practical implication: your application should read `DATABASE_URL`, `SECRET_KEY`, `DEBUG`, etc. from environment variables. Locally, you use a `.env` file for convenience. In production, you set these variables in your deployment platform (Docker, Kubernetes, Heroku, etc.).

### pydantic-settings

`pydantic-settings` is a companion library to Pydantic specifically designed for application configuration. It gives you a typed, validated settings class that reads from environment variables and `.env` files.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    APP_NAME: str = "MangaShelf"
    DEBUG: bool = False
    DATABASE_URL: str
    SECRET_KEY: str
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
```

Several things are happening here. `BaseSettings` knows how to read from environment variables. `model_config` tells it to also check a `.env` file. Each field is typed — `DEBUG: bool` means the string `"true"` in your `.env` gets automatically converted to Python's `True`. Fields with defaults (`DEBUG: bool = False`) are optional in the environment; fields without defaults (`DATABASE_URL: str`) are required and the app won't start without them.

This is a massive improvement over raw `os.getenv()`. With `os.getenv("DEBUG")`, you get a string. You have to manually convert it to a bool, handle `None`, and there's no validation. With `pydantic-settings`, you declare the type once and get validation, type coercion, and documentation for free.

### The .env File

A `.env` file is a simple key-value text file:

```
APP_NAME=MangaShelf
DEBUG=true
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/mangashelf
SECRET_KEY=your-secret-key-here-change-in-production
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```

This file should NEVER be committed to Git. It contains secrets. Instead, you commit `.env.example` with placeholder values, so other developers know which variables to set.

For list types like `CORS_ORIGINS`, pydantic-settings can parse JSON strings from environment variables. So `CORS_ORIGINS=["http://localhost:3000"]` in your `.env` file becomes a Python list `["http://localhost:3000"]`.

### Settings Singleton Pattern

You typically want one `Settings` instance for the entire application. Creating a new one on every request would re-read and re-parse the `.env` file unnecessarily. The standard pattern uses `functools.lru_cache`:

```python
from functools import lru_cache

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`@lru_cache` ensures that `get_settings()` creates the `Settings` object once and returns the cached instance on subsequent calls. This function also works perfectly as a FastAPI dependency:

```python
from fastapi import Depends

@router.get("/debug")
async def debug_info(settings: Settings = Depends(get_settings)):
    return {"app_name": settings.APP_NAME, "debug": settings.DEBUG}
```

Using `Depends(get_settings)` instead of calling `get_settings()` directly has an important benefit: it's testable. In tests, you can override the dependency to inject different settings without modifying environment variables.

### CORS Middleware

Cross-Origin Resource Sharing (CORS) is a browser security mechanism. If your frontend runs on `http://localhost:3000` and your API runs on `http://localhost:8000`, the browser blocks the frontend from calling the API unless the API explicitly allows it via CORS headers.

FastAPI provides `CORSMiddleware` to handle this:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

By driving `allow_origins` from your settings, you can have permissive CORS in development and restrictive CORS in production — same code, different environment variables.

## Your Task

### Step 1: Install pydantic-settings

Install `pydantic-settings` and update your `requirements.txt`.

### Step 2: Create the settings module

Create `app/core/config.py` with a `Settings` class that has these fields:

- `APP_NAME`: str, default "MangaShelf"
- `APP_VERSION`: str, default "0.1.0"
- `DEBUG`: bool, default `False`
- `DATABASE_URL`: str, default a local PostgreSQL URL (you'll use it in Phase 2)
- `SECRET_KEY`: str (required, no default — the app should fail to start without it)
- `CORS_ORIGINS`: list of strings, default `["http://localhost:3000"]`
- `ACCESS_TOKEN_EXPIRE_MINUTES`: int, default 30
- `REFRESH_TOKEN_EXPIRE_DAYS`: int, default 7

Configure the class to read from a `.env` file.

### Step 3: Create get_settings

In the same file, create a `get_settings()` function with `@lru_cache` that returns a `Settings` instance.

### Step 4: Create .env and .env.example

Create a `.env` file (gitignored) with actual values for local development. Create `.env.example` (committed) with placeholder values that document what's needed:

```
APP_NAME=MangaShelf
DEBUG=true
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/mangashelf
SECRET_KEY=change-me-in-production
CORS_ORIGINS=["http://localhost:3000"]
```

### Step 5: Add CORS middleware

In `app/main.py`, import your settings and add `CORSMiddleware` with origins driven by the settings.

### Step 6: Use settings in your app

- Pass `settings.APP_NAME` and `settings.APP_VERSION` to the `FastAPI()` constructor's `title` and `version` parameters.
- Update your error handlers from Chapter 5 to check `settings.DEBUG` when deciding whether to show error details.

### Step 7: Verify

- Start the app — it should work with your `.env` values.
- Remove `SECRET_KEY` from `.env` — the app should fail to start with a validation error.
- Change `DEBUG` to `false` and verify that error details are hidden.

## Expected Outcome
- The app reads configuration from `.env` and environment variables
- Missing required settings (like `SECRET_KEY`) prevent the app from starting
- `DEBUG=true` shows detailed error messages; `DEBUG=false` hides them
- CORS headers are present in responses (check with browser dev tools or curl)
- `.env` is in `.gitignore`; `.env.example` is committed

## Hints
- If the app fails to find `.env`, make sure you're running `uvicorn` from the project root directory (the one containing `.env`).
- For `CORS_ORIGINS`, use a JSON-formatted string in `.env`: `CORS_ORIGINS=["http://localhost:3000"]`.
- You can test CORS headers with: `curl -H "Origin: http://localhost:3000" -I http://localhost:8000/health` and look for `access-control-allow-origin` in the response headers.
- If `SECRET_KEY` has no default, Pydantic will raise `ValidationError` at startup when it's missing — that's the desired behavior.

## What I'll Look For In Review
- Settings class uses `pydantic_settings.BaseSettings`, not raw `os.getenv()`
- `SECRET_KEY` is required (no default) — the app cannot start without it
- `get_settings` uses `@lru_cache` for singleton behavior
- CORS middleware is configured with origins from settings, not hardcoded
- `.env` is gitignored; `.env.example` exists with placeholder values
