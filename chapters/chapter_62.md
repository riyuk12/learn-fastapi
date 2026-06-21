# Chapter 62 — CI/CD with GitHub Actions

## Concepts You'll Learn
- CI pipeline stages (lint, test, build, deploy)
- GitHub Actions workflow syntax
- Docker image registry (GHCR)
- Deployment triggers and the Makefile pattern

## Concept Deep Dive

### CI Pipeline Stages

Continuous Integration (CI) is the practice of automatically verifying every code change. When you push code or open a pull request, an automated pipeline runs checks to catch problems before they reach the main branch. The typical stages, in order:

1. **Lint** — Static analysis catches code style issues and potential bugs. For Python: `ruff` for linting, `mypy` for type checking. These are the fastest checks and catch the most common issues.

2. **Test** — Your test suite verifies that the code behaves correctly. Run `pytest` with your database and Redis running (in CI, these run as services). This is the most important stage.

3. **Build** — Compile, package, or build Docker images. This verifies that the code can be deployed. Building the Docker image catches Dockerfile errors, missing dependencies, and import failures.

4. **Deploy** — Push the tested, built artifact to production. This stage only runs on the main branch, never on pull requests. It might push a Docker image to a registry, SSH to a server and pull the new image, or trigger a Kubernetes rollout.

```
PR opened → [lint] → [test] → [build] → ✅ ready for review
Merge to main → [lint] → [test] → [build] → [push to registry] → [deploy]
```

Each stage acts as a gate. If linting fails, tests do not run (no point testing code that does not follow standards). If tests fail, the image is not built. This fail-fast approach saves time and compute resources.

### GitHub Actions Workflow Syntax

GitHub Actions workflows are YAML files in `.github/workflows/`. Each workflow is triggered by events (push, pull request, schedule) and consists of jobs. Each job runs on a virtual machine (runner) and contains a sequence of steps.

```yaml
name: CI
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff mypy
      - run: ruff check .
      - run: mypy app/

  test:
    runs-on: ubuntu-latest
    needs: lint  # only runs if lint passes
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: testpass
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: pytest
```

Key concepts:
- `on` defines triggers. You can trigger on push, pull_request, schedule, manual dispatch, or other events.
- `jobs` defines the work. Jobs run in parallel by default; use `needs` for dependencies.
- `services` spins up Docker containers alongside your job (perfect for databases in tests).
- `steps` are sequential commands within a job. `uses` runs a pre-built action; `run` executes a shell command.
- `secrets` are encrypted values stored in GitHub repository settings, accessed via `${{ secrets.NAME }}`.

### Docker Image Registry (GHCR)

When your CI pipeline builds a Docker image, it needs somewhere to push it. **GitHub Container Registry (GHCR)** is a Docker-compatible registry hosted alongside your GitHub repository. Images are tied to your GitHub account or organization.

```yaml
- name: Login to GHCR
  uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}

- name: Build and push
  uses: docker/build-push-action@v5
  with:
    push: true
    tags: ghcr.io/${{ github.repository }}/api:latest
```

The `GITHUB_TOKEN` is automatically provided by GitHub Actions — you do not need to create it. Images are available at `ghcr.io/<owner>/<repo>/<image>:<tag>`.

Tagging strategy matters. Common approaches:
- `latest` — always the most recent build from main (mutable tag)
- Git SHA: `ghcr.io/user/mangashelf/api:abc1234` — immutable, traceable to exact commit
- Semantic version: `ghcr.io/user/mangashelf/api:1.2.3` — for releases

Use both: tag every image with the git SHA (for traceability) and `latest` (for convenience).

### The Makefile Pattern

A `Makefile` provides memorable shortcuts for common commands. Instead of remembering `docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build`, you type `make prod-up`. This is especially valuable for CI pipelines and for new developers onboarding to the project.

```makefile
.PHONY: lint test build up down

lint:
	ruff check .
	mypy app/

test:
	pytest -v

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down
```

The `.PHONY` declaration tells Make these targets are commands, not files. Without it, Make would look for a file named `lint` and skip the command if it exists.

## Your Task

### Step 1: Create the CI Workflow

Create `.github/workflows/ci.yml` that runs on pull requests to `main` and pushes to `main`:

**Lint job:**
- Check out code
- Set up Python 3.12
- Install linting dependencies (ruff, mypy)
- Run `ruff check .` (linting)
- Run `ruff format --check .` (format verification)
- Run `mypy app/` (type checking)

**Test job:**
- Depends on lint (runs only if lint passes)
- Start services: PostgreSQL 16, Redis 7
- Check out code
- Set up Python 3.12
- Install all dependencies
- Run Alembic migrations against the test database
- Run `pytest` with coverage reporting
- Upload coverage report as an artifact (optional)

**Build job:**
- Depends on test
- Only runs on push to main (not on PRs)
- Build the Docker image
- Login to GHCR
- Push the image tagged with the git SHA and `latest`

### Step 2: Create the Deploy Workflow

Create `.github/workflows/deploy.yml`:
- Triggered after the CI workflow succeeds on main (use `workflow_run` trigger)
- A placeholder deployment step that would SSH to a server, pull the new image, and restart services
- Add comments explaining what a real deployment would look like

```yaml
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
    branches: [main]
```

### Step 3: Create the Makefile

Create a `Makefile` at the project root with these targets:

- `make lint` — run ruff check and mypy
- `make format` — run ruff format (auto-fix)
- `make test` — run pytest
- `make build` — docker compose build
- `make up` — docker compose up -d
- `make down` — docker compose down
- `make logs` — docker compose logs -f
- `make migrate` — run alembic upgrade head
- `make shell` — open a bash shell in the api container

Each target should have a brief comment explaining what it does.

### Step 4: Add Branch Protection (Documentation)

Document (as comments in the CI workflow or in a separate file) the recommended GitHub branch protection rules for `main`:
- Require PR reviews before merging
- Require status checks to pass (the lint and test jobs)
- Require branches to be up to date before merging
- No direct pushes to main

### Step 5: Test the CI Pipeline Locally

Before pushing to GitHub, verify each CI step runs locally:

```bash
make lint    # should pass (fix any issues first)
make test    # should pass
make build   # should produce a working image
```

### Step 6: Handle CI-Specific Configuration

Create a `pytest` configuration (in `pyproject.toml` or `pytest.ini`) that CI can use:
- Set the test database URL from environment variables
- Configure test timeouts so CI does not hang on a stuck test
- Set up coverage thresholds (e.g., minimum 70% coverage)

## Expected Outcome
- Pull requests trigger lint and test jobs automatically
- Tests run with real PostgreSQL and Redis in CI (via GitHub Actions services)
- Merging to main triggers image build and push to GHCR
- Deploy workflow has a placeholder for actual deployment
- Makefile provides convenient shortcuts for all common operations
- CI pipeline catches code issues before they reach the main branch

## Hints
- For GitHub Actions services (PostgreSQL, Redis), they are accessible at `localhost` with the mapped port — just like running them locally.
- Use `actions/cache@v4` to cache pip dependencies between CI runs. This speeds up the install step significantly.
- The `GITHUB_TOKEN` secret is automatically available — you do not need to create it in repository settings.
- If mypy reports many errors in third-party libraries, add a `mypy.ini` or `pyproject.toml` section that ignores missing imports for packages without type stubs.

## What I'll Look For In Review
- CI workflow has proper stage dependencies (lint before test before build)
- GitHub Actions services are used for PostgreSQL and Redis in tests
- Docker images are tagged with both git SHA and `latest`
- Build and push only happens on main branch merges, not on PRs
- Makefile targets are useful and cover the common workflows
