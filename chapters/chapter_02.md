# Chapter 2 — Routing & App Structure

## Concepts You'll Learn
- APIRouter and how to create modular route files
- The `app/` package pattern and how files connect
- `include_router` and prefix/tag composition
- API versioning structure (`/api/v1/...`)

## Concept Deep Dive

### APIRouter

In Chapter 1, you defined your `/health` endpoint directly on the `FastAPI` app instance. That works, but imagine having 50 endpoints all in `main.py` — it would become unreadable fast. This is where `APIRouter` comes in.

`APIRouter` is essentially a mini-application that can define its own routes, which you later "mount" onto the main `FastAPI` instance. Think of it like writing chapters of a book separately and then binding them together. Each router file focuses on one resource (manga, users, auth) and defines all the endpoints related to that resource.

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def list_manga():
    return [{"title": "One Piece"}]
```

Notice that the route decorator is on `router`, not on `app`. This router doesn't know or care about the main application — it just defines its routes relative to itself. The main app will later decide where to mount it.

### Modular Route Files and the `app/` Package Pattern

A well-structured FastAPI project separates concerns into directories:

```
app/
├── __init__.py
├── main.py                  # Creates the FastAPI instance, wires everything
├── api/
│   ├── __init__.py
│   └── v1/
│       ├── __init__.py
│       ├── router.py        # Aggregates all v1 endpoint routers
│       └── endpoints/
│           ├── __init__.py
│           └── manga.py     # All manga-related endpoints
```

Each `endpoints/` file defines a router for one resource. The `v1/router.py` file imports all those resource routers and bundles them into one v1 router. Finally, `main.py` includes that v1 router on the app. This creates a clean chain: `main.py` -> `v1/router.py` -> `endpoints/manga.py`.

Why so many `__init__.py` files? Every directory that Python should treat as a package needs one. Without them, your `from app.api.v1.endpoints.manga import router` imports will fail with `ModuleNotFoundError`.

### include_router

The `include_router()` method is the glue that connects routers to the app (or to other routers). It takes a router and optionally applies a prefix, tags, and dependencies to all routes within it.

```python
# In v1/router.py
from app.api.v1.endpoints import manga

api_router = APIRouter()
api_router.include_router(manga.router, prefix="/manga", tags=["manga"])
```

```python
# In main.py
from app.api.v1.router import api_router

app.include_router(api_router, prefix="/api/v1")
```

With this setup, the `list_manga()` function decorated with `@router.get("/")` in `manga.py` becomes accessible at `/api/v1/manga/`. The prefixes compose: `/api/v1` (from main) + `/manga` (from v1 router) + `/` (from the endpoint) = `/api/v1/manga/`.

Tags control how endpoints are grouped in the Swagger UI. Every endpoint included with `tags=["manga"]` appears under a "manga" section in `/docs`.

### API Versioning Structure

Why `/api/v1/`? Because APIs evolve. Someday you might need to change the shape of your manga response in a way that breaks existing clients. When that happens, you create `/api/v2/` with the new shape while `/api/v1/` continues to work. Clients migrate at their own pace.

This is called URL-based versioning, and it's the most straightforward approach. Other strategies include header-based versioning (`Accept: application/vnd.mangashelf.v2+json`) and query parameter versioning (`?version=2`), but URL-based is the most common and the easiest to implement, test, and document.

By structuring your directories as `api/v1/`, `api/v2/`, etc., you make versioning a first-class part of your architecture rather than an afterthought you bolt on later.

## Your Task

### Step 1: Create the directory structure

Inside your `app/` directory, create the following new directories and files:

- `app/api/__init__.py`
- `app/api/v1/__init__.py`
- `app/api/v1/router.py`
- `app/api/v1/endpoints/__init__.py`
- `app/api/v1/endpoints/manga.py`

Every `__init__.py` can be empty for now.

### Step 2: Define the manga router

In `app/api/v1/endpoints/manga.py`, create an `APIRouter` instance. Define a `GET /` endpoint on this router that returns a hardcoded list of 3 manga dictionaries. Each dictionary should have at least `id` (an integer), `title` (a string), and `status` (either "ongoing" or "completed").

### Step 3: Create the v1 aggregator router

In `app/api/v1/router.py`, create another `APIRouter` instance. Import the manga router from `app.api.v1.endpoints.manga` and include it with a prefix of `/manga` and a tag of `"manga"`.

### Step 4: Wire into main.py

In `app/main.py`, import the v1 router from `app.api.v1.router` and include it on the app with a prefix of `/api/v1`. Keep the `/health` endpoint directly on the app — it's a top-level operational endpoint, not a versioned API resource.

### Step 5: Verify

Start the server and confirm your new endpoint works. Also check that the Swagger UI groups your manga endpoint under the "manga" tag.

## Expected Outcome
- `GET /api/v1/manga` returns a JSON array of 3 manga objects
- `GET /health` still works at the root level (no prefix)
- Swagger UI at `/docs` shows endpoints grouped under a "manga" tag
- The project structure has clean separation: `main.py` knows about routers, not individual endpoints

## Hints
- If you get `ModuleNotFoundError`, you're probably missing an `__init__.py` somewhere in the directory chain.
- Remember that `include_router` prefixes compose. If the v1 router has prefix `/api/v1` and the manga router has prefix `/manga`, the final path is `/api/v1/manga`.
- The hardcoded manga data can just be a Python list defined at the top of `manga.py`. You'll replace it with a real database later.
- Make sure you're running uvicorn from the project root (the directory containing `app/`), not from inside `app/`.

## What I'll Look For In Review
- Clean directory structure with all necessary `__init__.py` files
- Manga endpoints are defined in their own file, not in `main.py`
- `include_router` is used correctly with appropriate prefixes and tags
- The `/health` endpoint remains at the root level, not under `/api/v1`
- The hardcoded response is valid JSON (proper list of dicts with consistent keys)
