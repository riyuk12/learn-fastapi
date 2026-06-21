# Chapter 61 — Environment Management & Secrets

## Concepts You'll Learn
- Environment separation (dev/staging/prod)
- 12-factor app configuration
- Docker secrets vs environment variables
- Never baking secrets into images

## Concept Deep Dive

### Environment Separation

A professional application runs in multiple environments. **Development** (your laptop, Docker Compose) is where you write code with debug logging, hot reload, and relaxed security. **Staging** mirrors production closely — the same infrastructure, configuration patterns, and data shapes — but uses test data and is not public. **Production** is the real thing: real users, real data, hardened security, performance optimized.

Each environment needs different configuration values: database URLs, API keys, logging levels, feature flags, allowed CORS origins. The code should be identical across environments — only the configuration changes. This is a core principle of the 12-factor methodology.

```
dev.env:     DATABASE_URL=postgresql://user:devpass@localhost:5432/mangashelf_dev
staging.env: DATABASE_URL=postgresql://user:stagingpass@staging-db:5432/mangashelf_staging
prod.env:    DATABASE_URL=postgresql://user:???@prod-db:5432/mangashelf
```

Notice the `???` for production. Production secrets should never live in files that are committed to version control. The env templates document which variables are needed, but the actual values are injected at deployment time through secure channels.

### 12-Factor App Configuration

The [12-factor methodology](https://12factor.net) is a set of principles for building software-as-a-service applications. Factor III — "Config" — states: **Store config in the environment.**

This means your application reads all environment-specific values from environment variables, never from hardcoded values or config files baked into the deployment artifact. Your FastAPI app's `Settings` class (from Chapter 5) already does this with Pydantic's `BaseSettings` reading from environment variables. The Docker and Compose setup should feed those variables from environment-appropriate sources.

The benefits are clear: the same Docker image runs in any environment. You build once and deploy everywhere. The image is a tested artifact — you do not rebuild for each environment. Only the environment variables change.

```python
# Your Settings class already follows this pattern
class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    DEBUG: bool = False
    LOG_LEVEL: str = "info"

    model_config = SettingsConfigDict(env_file=".env")
```

### Docker Secrets vs Environment Variables

Environment variables are the standard way to pass configuration into containers. But they have a security weakness: `docker inspect` shows all environment variables in plain text. Anyone with Docker access can see your database password. Additionally, environment variables are visible to all processes inside the container and may appear in logs, crash dumps, or debugging tools.

**Docker secrets** are a more secure alternative available in Docker Swarm mode (and Docker Compose with some support). Secrets are mounted as files inside the container at `/run/secrets/<name>`:

```yaml
services:
  api:
    secrets:
      - db_password
      - secret_key

secrets:
  db_password:
    file: ./secrets/db_password.txt
  secret_key:
    file: ./secrets/secret_key.txt
```

Inside the container, the secret is readable at `/run/secrets/db_password`. Your application reads the file instead of an environment variable. Secrets are only available to services that explicitly declare them, they are stored encrypted at rest (in Swarm mode), and they do not show up in `docker inspect`.

For local development with Docker Compose, environment variables are fine. For production, secrets (or a dedicated secrets manager like HashiCorp Vault, AWS Secrets Manager, or Kubernetes Secrets) are the standard.

### Never Baking Secrets Into Images

This cannot be overstated: **Docker images must never contain secrets.** If your Dockerfile has `ENV SECRET_KEY=mysecret` or copies a `.env` file into the image, anyone who pulls that image (from your registry, from a compromised CI pipeline) gets your secrets.

```dockerfile
# NEVER DO THIS
COPY .env /app/.env
ENV SECRET_KEY=super-secret-value

# DO THIS INSTEAD
# Pass at runtime via environment variables or secrets
# The Dockerfile does not reference any secret values
```

Images are build artifacts. They are stored in registries, cached on build machines, and potentially shared. Treat them as public — even if your registry is private, defense in depth means assuming it could be compromised.

The correct flow: the Dockerfile installs dependencies and copies code. At runtime, the orchestrator (Docker Compose, Kubernetes, etc.) injects secrets via environment variables, mounted files, or a secrets manager. The application reads them at startup.

## Your Task

### Step 1: Create Environment Templates

Create an `env/` directory at the project root with template files:

**`env/dev.env`** — Development values (safe to commit because dev passwords are not secret):
- DEBUG=true
- LOG_LEVEL=debug
- DATABASE_URL=postgresql+asyncpg://mangashelf:devpassword@db:5432/mangashelf
- REDIS_URL=redis://redis:6379/0
- MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY (dev values)
- MEILISEARCH_URL, MEILI_MASTER_KEY (dev values)
- SECRET_KEY=dev-secret-key-not-for-production
- CORS_ORIGINS=http://localhost:3000,https://localhost

**`env/staging.env`** — Staging template (placeholder values):
- DEBUG=false
- LOG_LEVEL=info
- DATABASE_URL=CHANGE_ME
- Same pattern for all other variables

**`env/prod.env`** — Production template (all sensitive values are placeholders):
- DEBUG=false
- LOG_LEVEL=warning
- All sensitive values: CHANGE_ME or ${SECRET_FROM_VAULT}
- CORS_ORIGINS limited to production domain only

### Step 2: Create Production Docker Compose Override

Create `docker-compose.prod.yml` that overrides the base `docker-compose.yml`:
- No volume mounts for source code (no hot reload in production)
- No exposed debug ports
- Resource limits for each service (memory and CPU constraints):

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"
      replicas: 2  # run 2 instances for high availability
```

- Restart policy: `restart: unless-stopped` for all services
- Log driver configuration (JSON file with rotation):

```yaml
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

### Step 3: Create Secrets Generation Script

Create `scripts/generate-secrets.sh`:
- Generates random values for: SECRET_KEY, POSTGRES_PASSWORD, MINIO_SECRET_KEY, MEILI_MASTER_KEY
- Uses `openssl rand` or `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- Outputs the generated values to stdout (or writes to a file)
- Include a warning: "Store these securely. Do not commit them to version control."

```bash
#!/bin/bash
echo "SECRET_KEY=$(openssl rand -base64 32)"
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24)"
echo "MINIO_SECRET_KEY=$(openssl rand -base64 24)"
echo "MEILI_MASTER_KEY=$(openssl rand -base64 24)"
```

### Step 4: Update Docker Compose for Environment Files

Modify your `docker-compose.yml` to use `env_file` instead of inline environment variables:

```yaml
services:
  api:
    env_file:
      - ./env/dev.env  # base uses dev
```

Your production compose override can reference a different env file:

```yaml
services:
  api:
    env_file:
      - ./env/prod.env
```

### Step 5: Document Docker Secrets Usage

Add comments or a section in your codebase documenting how to use Docker secrets for production. Show how to modify the `Settings` class to read from secret files as a fallback:

```python
# Pseudocode for reading secrets from files
import os

def get_secret(env_var: str, secret_name: str = None) -> str:
    """Read from env var, falling back to Docker secret file."""
    value = os.getenv(env_var)
    if value:
        return value
    secret_path = f"/run/secrets/{secret_name or env_var.lower()}"
    if os.path.exists(secret_path):
        return open(secret_path).read().strip()
    raise ValueError(f"Neither {env_var} env var nor {secret_path} secret found")
```

### Step 6: Verify Environment Isolation

Test that you can start the stack with different environment configurations:

```bash
# Development (default)
docker compose up

# Production simulation
docker compose -f docker-compose.yml -f docker-compose.prod.yml up
```

Verify that the production override applies resource limits, disables debug mode, and does not mount source code.

## Expected Outcome
- Three environment templates exist (dev, staging, prod) with appropriate values
- Production compose override is hardened (no hot reload, resource limits, restart policies)
- Secret generation script creates strong random values
- Environment is selected by choosing the appropriate compose file and env file
- No secrets are baked into Docker images
- Documentation explains how to use Docker secrets for production

## Hints
- Use `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` to see the merged configuration without actually starting services. This is useful for verifying overrides.
- The `.env` file at the project root is automatically loaded by Docker Compose for variable substitution in the YAML file itself. This is different from `env_file`, which loads variables into the container.
- For resource limits, start with generous limits and tighten based on actual usage from monitoring (Chapter 65).
- Add `env/prod.env` to `.gitignore` and only commit `env/prod.env.example` with placeholder values.

## What I'll Look For In Review
- Clear separation between development, staging, and production configurations
- Production compose override includes resource limits, restart policies, and no development conveniences
- No real secrets in any committed file
- Secret generation script produces strong random values
- The codebase supports reading secrets from both environment variables and Docker secret files
