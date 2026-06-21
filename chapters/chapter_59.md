# Chapter 59 — Docker Compose: The Full Stack

## Concepts You'll Learn
- Multi-container orchestration with Docker Compose
- Service dependencies and health checks
- Named volumes for persistent data
- Docker networks for service isolation

## Concept Deep Dive

### Multi-Container Orchestration

MangaShelf now has many moving parts: the FastAPI application, a Celery worker, Celery beat scheduler, PostgreSQL, Redis, MinIO, and Meilisearch. Running each one manually with `docker run` and managing their networking, environment variables, and startup order would be painful. Docker Compose lets you define all services in a single YAML file and bring everything up with one command.

```yaml
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://user:pass@db:5432/mangashelf
      REDIS_URL: redis://redis:6379/0
```

Each service gets a hostname equal to its service name. The `api` service can reach PostgreSQL at `db:5432` and Redis at `redis:6379`. Docker Compose creates a default network where all services can communicate by name. This replaces `localhost` — inside the Docker network, services reference each other by service name.

The `build` key tells Compose to build the image from a Dockerfile. Alternatively, `image` pulls a pre-built image from a registry. For infrastructure services (PostgreSQL, Redis), you use official images. For your application, you build from your Dockerfile.

### Service Dependencies and Health Checks

Services have startup dependencies. The API cannot connect to PostgreSQL if PostgreSQL has not started yet. Docker Compose's `depends_on` controls startup order, but basic `depends_on` only waits for the container to start, not for the service inside to be ready. A PostgreSQL container might start in 1 second, but the database inside takes 5 seconds to accept connections.

**Health checks** solve this. A health check is a command Docker runs periodically to verify a service is actually ready:

```yaml
services:
  db:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mangashelf"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
```

With `condition: service_healthy`, Compose waits until the health check passes before starting dependent services. `pg_isready` is a PostgreSQL utility that checks if the database is accepting connections. For Redis, `redis-cli ping` serves the same purpose.

### Named Volumes

Containers are ephemeral — when you remove a container, its data disappears. For databases and object storage, you need persistent data. Docker volumes exist outside the container lifecycle.

```yaml
services:
  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

The `volumes` section at the bottom declares named volumes. Docker manages where they live on disk. When you `docker compose down`, the containers are removed, but the volumes persist. Your data survives. When you `docker compose up` again, the new containers mount the same volumes and find the existing data.

For development, you also want to mount your source code into the container so that changes are reflected without rebuilding the image. This uses a **bind mount** (a host path mapped into the container):

```yaml
services:
  api:
    volumes:
      - ./backend:/app  # bind mount for hot reload
      - /app/.venv      # anonymous volume to prevent overwriting the container's venv
```

The anonymous volume on `/app/.venv` is a trick: it prevents the bind mount from overwriting the venv inside the container. Without it, the host's directory (which has no venv) would mask the container's installed packages.

### Docker Networks

By default, Compose creates a single network for all services. For better isolation, you can define custom networks:

```yaml
services:
  api:
    networks:
      - backend
      - frontend-net
  db:
    networks:
      - backend  # only accessible from backend network

networks:
  backend:
  frontend-net:
```

This means the database is only reachable from services on the `backend` network. A compromised frontend container cannot directly access the database. For MangaShelf, a single default network is fine for development, but understanding network isolation matters for production.

## Your Task

### Step 1: Create `docker-compose.yml`

Create `docker-compose.yml` at the project root with these services:

**api** — Your FastAPI application:
- Build from `backend/Dockerfile`
- Map port 8000
- Environment variables: DATABASE_URL, REDIS_URL, MINIO_URL, MEILISEARCH_URL, SECRET_KEY, etc.
- Depends on: db, redis, minio, meilisearch (with health check conditions)

**worker** — Celery worker:
- Build from the same Dockerfile (or Dockerfile.worker)
- Override CMD to run celery worker
- Same environment variables as api
- Depends on: db, redis

**beat** — Celery beat scheduler:
- Same build as worker
- Override CMD to run celery beat
- Depends on: redis

**db** — PostgreSQL:
- Image: `postgres:16`
- Environment: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
- Named volume for data persistence
- Health check: `pg_isready`

**redis** — Redis:
- Image: `redis:7-alpine`
- Health check: `redis-cli ping`
- Named volume for data persistence (optional, Redis is cache)

**minio** — MinIO object storage:
- Image: `minio/minio`
- CMD: `server /data --console-address ":9001"`
- Map ports: 9000 (API) and 9001 (console)
- Environment: MINIO_ROOT_USER, MINIO_ROOT_PASSWORD
- Named volume for data persistence

**meilisearch** — Search engine:
- Image: `getmeili/meilisearch:latest`
- Map port 7700
- Environment: MEILI_MASTER_KEY
- Named volume for data persistence

### Step 2: Define Volumes

Declare named volumes at the bottom of the compose file:
- `pgdata` — PostgreSQL data
- `minio-data` — MinIO storage
- `meili-data` — Meilisearch data

### Step 3: Add Health Checks

Add health checks to all infrastructure services:
- `db`: `pg_isready -U <user>`
- `redis`: `redis-cli ping` (expect PONG)
- `minio`: `curl -f http://localhost:9000/minio/health/live` or a similar health endpoint
- `meilisearch`: `curl -f http://localhost:7700/health`

Configure `depends_on` with `condition: service_healthy` for the api and worker services.

### Step 4: Create Development Override

Create `docker-compose.override.yml` for development-specific settings:
- Mount source code into the api container for hot reload: `./backend:/app`
- Override api CMD to include `--reload` flag for uvicorn
- Expose additional debug ports if needed
- Set development-specific environment variables (DEBUG=true, LOG_LEVEL=debug)

The override file is automatically merged with the base file when you run `docker compose up`.

### Step 5: Test the Full Stack

```bash
docker compose up --build
```

Verify:
- All services start and become healthy
- The API responds at http://localhost:8000/docs
- MinIO console is accessible at http://localhost:9001
- PostgreSQL is accessible from the api container (check by hitting an endpoint that queries the database)

### Step 6: Test Data Persistence

```bash
docker compose down      # stop and remove containers
docker compose up -d     # start again in detached mode
```

Verify that database data, MinIO files, and Meilisearch indexes survive the restart. The named volumes should preserve everything.

### Step 7: Run Migrations

Add a migration step. You have a few options:
- Create a `migrate` service that runs `alembic upgrade head` and exits
- Add a migration script to the api service's entrypoint
- Run it manually: `docker compose exec api alembic upgrade head`

Choose one approach and document why.

## Expected Outcome
- `docker compose up` starts all 7 services (api, worker, beat, db, redis, minio, meilisearch)
- Health checks ensure services start in the correct order
- Data persists across `docker compose down` and `docker compose up`
- Development override enables hot reload without rebuilding the image
- All services can communicate by service name
- Alembic migrations can be run against the Dockerized database

## Hints
- For environment variables, you can use an `.env` file and reference it with `env_file: .env` in the compose file. This keeps secrets out of the YAML.
- The `docker compose override` file does not need to repeat everything from the base file — only the things you want to change or add.
- If the api fails to start because the database migration has not run, add a startup script (entrypoint) that runs `alembic upgrade head` before starting uvicorn.
- Use `docker compose logs -f api` to tail logs from a specific service for debugging.

## What I'll Look For In Review
- All services are defined with correct images, ports, and environment
- Health checks are configured for infrastructure services
- `depends_on` uses `condition: service_healthy` (not just basic depends_on)
- Named volumes are used for all persistent data
- Development override provides hot reload and is cleanly separated from the base config
