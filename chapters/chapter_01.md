# Chapter 1 — Hello MangaShelf: Project Scaffold

## Concepts You'll Learn
- Virtual environments and why they matter
- Project directory structure for a FastAPI application
- Dependency management with `requirements.txt` (and a note on `pyproject.toml`)
- Initializing a Git repository and writing a proper `.gitignore`

## Concept Deep Dive

### Virtual Environments

Every Python project should live inside its own virtual environment. Think of it like giving each project its own private toolbox. Without a virtual environment, every Python project on your machine shares the same global pool of installed packages. Install Flask 2.0 for Project A, then upgrade to Flask 3.0 for Project B, and suddenly Project A is broken. Virtual environments eliminate this problem entirely.

When you run `python -m venv venv`, Python creates a directory (called `venv` by convention) containing a copy of the Python interpreter and an isolated `site-packages` folder. After you activate it with `source venv/bin/activate` (on macOS/Linux) or `venv\Scripts\activate` (on Windows), every `pip install` goes into that isolated folder. Your system Python stays untouched.

Here's the key mental model: a virtual environment is not a container, not a VM, and not Docker. It's simply a directory redirection trick. When activated, your shell's `PATH` is modified so that `python` and `pip` point to the copies inside `venv/` instead of the global ones. That's it. Simple, but profoundly useful.

### Project Directory Structure

A well-organized project structure is like a well-organized kitchen: you know exactly where to find the knives, the pots, and the spices. For FastAPI projects, a common pattern looks like this:

```
mangashelf/
├── app/
│   ├── __init__.py
│   └── main.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

The `app/` directory is a Python package (notice the `__init__.py`). This is where all your application code lives. The `main.py` file inside `app/` is the entry point — it creates the FastAPI application instance. Everything outside `app/` is project configuration: dependencies, environment templates, version control settings.

Why `app/main.py` instead of just `main.py` at the root? Because as your project grows, you'll add `app/api/`, `app/models/`, `app/services/`, and more. Starting with the `app/` package pattern from day one means you never have to restructure later. It also makes your import paths clean and consistent: `from app.main import app`, `from app.models.manga import Manga`.

### Dependency Management

`requirements.txt` is the simplest way to track what your project needs. Every package you install should be recorded here so that another developer (or your future self, or a deployment server) can recreate the exact same environment.

The naive approach is `pip freeze > requirements.txt`, which dumps every installed package with exact version pins. This works but creates bloated files with transitive dependencies you didn't ask for. A better approach for now: manually list only your direct dependencies with loose version constraints:

```
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
```

For more sophisticated projects, `pyproject.toml` is the modern standard. It replaces `setup.py`, `setup.cfg`, and `requirements.txt` in one file. We'll start with `requirements.txt` for simplicity, but know that `pyproject.toml` is where the ecosystem is heading.

### Git Init and .gitignore

Version control isn't optional — it's as fundamental as writing code. Your first commit should happen before you write any application logic. This gives you a clean baseline to compare against and rollback to.

A `.gitignore` file tells Git which files to pretend don't exist. For a Python project, you absolutely must ignore:

- `venv/` — your virtual environment (it's reproducible from `requirements.txt`)
- `__pycache__/` — compiled Python bytecode
- `.env` — your secrets and local configuration
- `*.pyc` — more bytecode files

Never commit your `.env` file. It will contain database passwords, API keys, and secrets. Instead, commit `.env.example` with placeholder values so other developers know which variables to set.

## Your Task

### Step 1: Create the project directory

Create a directory called `mangashelf/` wherever you keep your projects. This is your project root — everything lives inside here.

### Step 2: Initialize a virtual environment

Inside `mangashelf/`, create a virtual environment using Python's built-in `venv` module. Activate it. Confirm it's active by checking that `which python` points to the `venv/` directory.

### Step 3: Install dependencies

Install `fastapi` and `uvicorn[standard]` using pip. After installing, create a `requirements.txt` that lists these two dependencies. You can pin to specific versions or use `>=` constraints.

### Step 4: Create the app package

Create the `app/` directory with an `__init__.py` file (it can be empty) and a `main.py` file. In `main.py`:

- Import and create a `FastAPI` application instance. Give it a `title` of "MangaShelf" and a `version` of "0.1.0".
- Create a single GET endpoint at `/health` that returns `{"status": "ok"}`.

### Step 5: Create configuration files

- Create `.gitignore` with entries for `venv/`, `__pycache__/`, `.env`, `*.pyc`, `.idea/`, `.vscode/`, and any other editor/OS artifacts.
- Create `.env.example` with a single entry: `APP_NAME=MangaShelf`.

### Step 6: Initialize Git and make your first commit

Run `git init`, stage all files (double-check that `venv/` is NOT staged), and make your first commit with a message like "Initial project scaffold".

### Step 7: Run the server

Start the development server with:

```
uvicorn app.main:app --reload
```

The `app.main:app` syntax means "from the `app` package, import the `main` module, and use the `app` variable inside it." The `--reload` flag watches for file changes and auto-restarts — essential for development.

## Expected Outcome
- Running `uvicorn app.main:app --reload` starts the server on `http://127.0.0.1:8000`
- Visiting `http://127.0.0.1:8000/health` returns `{"status": "ok"}`
- Visiting `http://127.0.0.1:8000/docs` shows the Swagger UI with your health endpoint listed
- `git status` shows a clean working tree (no untracked files, nothing to commit)
- `venv/` does NOT appear in `git log` or `git status`

## Hints
- If `uvicorn` isn't found after installing, make sure your virtual environment is activated.
- The `__init__.py` file can be completely empty — its mere existence tells Python that `app/` is a package.
- FastAPI's automatic docs are at `/docs` (Swagger UI) and `/redoc` (ReDoc). You get both for free.

## What I'll Look For In Review
- Virtual environment is created and NOT committed to Git
- `requirements.txt` exists and lists the correct dependencies
- `app/` is a proper Python package (has `__init__.py`)
- The `/health` endpoint returns the exact JSON shape `{"status": "ok"}`
- `.gitignore` covers all the essentials (venv, pycache, .env, editor files)
