# Chapter 58 — Dockerizing the Backend

## Concepts You'll Learn
- Dockerfile anatomy (FROM, RUN, COPY, CMD)
- Multi-stage builds (builder vs runtime)
- Image size optimization
- Running as non-root user for security

## Concept Deep Dive

### Dockerfile Anatomy

A Dockerfile is a recipe for building a container image. Each instruction creates a **layer**, and layers are cached — if a layer has not changed, Docker reuses the cached version. Understanding this layer caching is essential for writing efficient Dockerfiles.

The key instructions:
- `FROM` — sets the base image. Every Dockerfile starts with this.
- `RUN` — executes a command during build. Each RUN creates a new layer.
- `COPY` — copies files from your machine into the image.
- `WORKDIR` — sets the working directory for subsequent instructions.
- `ENV` — sets environment variables.
- `EXPOSE` — documents which port the container listens on (does not actually publish it).
- `CMD` — the default command to run when the container starts.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Layer order matters for caching.** Notice that `requirements.txt` is copied and dependencies installed before the application code is copied. This means if you change your Python code but not your dependencies, Docker reuses the cached dependency installation layer. If you copied everything first, every code change would invalidate the dependency cache and reinstall everything.

### Multi-Stage Builds

A single-stage Dockerfile for Python includes pip, compilers, header files, and build tools — all needed to install dependencies but unnecessary at runtime. Multi-stage builds solve this by using one stage to build and another to run.

```dockerfile
# Stage 1: Builder
FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY ./app ./app
COPY alembic.ini .
COPY alembic/ ./alembic/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The builder stage installs everything into a virtual environment at `/opt/venv`. The runtime stage starts fresh from the same base image, copies only the venv (the installed packages) and the application code. Build artifacts, pip caches, and compilation tools are left behind in the builder stage.

This can reduce image size significantly — sometimes by hundreds of megabytes. The final image only contains what is needed to run the application.

### Image Size Optimization

Every megabyte in your image matters. Larger images mean slower pulls (deployments take longer), more storage costs, and a larger attack surface. Here are the techniques:

**Use slim base images.** `python:3.12-slim` is ~150MB vs `python:3.12` at ~900MB. The slim variant removes documentation, extra locales, and development tools you do not need at runtime.

**Use `--no-cache-dir` with pip.** By default, pip caches downloaded packages. Inside a container, this cache is wasted space: `pip install --no-cache-dir -r requirements.txt`.

**Combine RUN instructions** where logical. Each RUN creates a layer, and layers have overhead. But do not combine unrelated commands — this hurts cache efficiency.

**Use `.dockerignore`.** Like `.gitignore`, this prevents unnecessary files from being sent to the Docker build context. Exclude `.venv`, `__pycache__`, `.git`, `tests/`, `node_modules/`, and any local environment files.

### Running as Non-Root

By default, processes in Docker containers run as root. If an attacker exploits a vulnerability in your application, they get root access inside the container — and potentially on the host if the container is misconfigured. Running as a non-root user limits the blast radius.

```dockerfile
# Create a non-root user
RUN addgroup --system app && adduser --system --ingroup app app

# Switch to that user
USER app
```

After the `USER` instruction, all subsequent instructions and the container's CMD run as the `app` user. This user cannot modify system files, install packages, or access sensitive directories. Your application code and the venv should be readable by this user, but not writable (defense in depth).

One gotcha: if your application needs to write to disk (log files, temporary uploads), make sure the target directories are writable by the non-root user. Create these directories in the Dockerfile before switching users and set ownership with `chown`.

## Your Task

### Step 1: Create `.dockerignore`

Create `backend/.dockerignore` (or at the project root, depending on your Docker build context) excluding:
- `.venv/` and `venv/`
- `__pycache__/` and `*.pyc`
- `.git/`
- `tests/`
- `.env` and `.env.*` (secrets should never be baked into images)
- `*.md` (documentation)
- `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`
- `node_modules/` (if present)

### Step 2: Create the Backend Dockerfile

Create `backend/Dockerfile` (or `Dockerfile` at the appropriate level for your project structure) with a multi-stage build:

**Builder stage:**
- Base: `python:3.12-slim`
- Install system dependencies needed for building (libpq-dev, gcc — needed for psycopg2)
- Create a venv at `/opt/venv`
- Copy `requirements.txt` (or `pyproject.toml` if using one)
- Install Python dependencies into the venv with `--no-cache-dir`

**Runtime stage:**
- Base: `python:3.12-slim`
- Install only runtime system dependencies (libpq5 for PostgreSQL client library — no compiler)
- Copy the venv from the builder stage
- Copy application code (app/, alembic/, alembic.ini)
- Create a non-root user and switch to it
- Set PATH to include the venv
- Expose port 8000
- CMD to run uvicorn

### Step 3: Create the Worker Dockerfile

Create `backend/Dockerfile.worker` (or a separate Dockerfile for Celery):
- Can share the same builder stage (use the same base and dependencies)
- The runtime stage is identical except the CMD runs Celery worker instead of uvicorn
- `CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]`

Alternatively, use a single Dockerfile and override the CMD at runtime (in docker-compose). This is more DRY. Choose the approach you prefer and understand the trade-off.

### Step 4: Build and Test the Image

Build the image and verify:

```bash
docker build -t mangashelf-api -f backend/Dockerfile .
docker images mangashelf-api  # check size — target <200MB
```

Run the container to verify it starts (it will fail to connect to the database, which is expected — we will fix this with Docker Compose in Chapter 59):

```bash
docker run --rm -p 8000:8000 mangashelf-api
```

### Step 5: Verify Image Security

Check that the container runs as non-root:

```bash
docker run --rm mangashelf-api whoami
# Should output "app", not "root"
```

Verify that no secrets are baked into the image:

```bash
docker run --rm mangashelf-api env
# Should NOT contain SECRET_KEY, DATABASE_URL, etc.
```

### Step 6: Optimize and Iterate

Check the image size with `docker images`. If it is over 200MB, investigate:
- Are unnecessary files being copied? Check `.dockerignore`.
- Are build tools present in the runtime stage? They should only be in the builder.
- Use `docker history mangashelf-api` to see layer sizes and identify bloat.

## Expected Outcome
- `docker build` produces an image under 200MB
- The container runs as a non-root user
- No secrets or development files are baked into the image
- The application starts correctly inside the container (uvicorn binds to 0.0.0.0:8000)
- The worker Dockerfile produces a working Celery container
- Layer caching works — changing app code does not reinstall dependencies

## Hints
- If you use `psycopg2-binary` instead of `psycopg2`, you do not need the C compiler in the builder stage. But `psycopg2-binary` is not recommended for production. Your choice.
- The `COPY --from=builder` instruction is what makes multi-stage work. Everything in the builder stage is discarded except what you explicitly copy.
- To test layer caching, build twice. The second build should be instant if nothing changed. Then change a Python file and build again — only the COPY layer and later should rebuild.
- If your project uses `pyproject.toml` with Poetry or pip, adjust the install commands accordingly. The multi-stage pattern is the same regardless of the package manager.

## What I'll Look For In Review
- Multi-stage build with a clean separation between builder and runtime
- `.dockerignore` excludes development artifacts and secrets
- Non-root user is created and used
- Layer order is optimized for caching (dependencies before code)
- Final image is under 200MB
