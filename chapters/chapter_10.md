# Chapter 10 — Alembic Migrations

## Concepts You'll Learn
- What database migrations are and why they're essential
- Alembic initialization and configuration for async
- Autogenerating migrations from SQLAlchemy models
- Running upgrade/downgrade and migration discipline

## Concept Deep Dive

### What Are Database Migrations?

Imagine you're building a house. First you lay the foundation. Then you add walls. Then you decide you need an extra window. You don't demolish the house and rebuild — you modify the existing structure. Database migrations work the same way.

A migration is a script that describes a change to your database schema: "add this table," "add this column," "create this index," "rename this field." Each migration has an upgrade (apply the change) and a downgrade (undo the change). Together, they form a linear history of how your schema evolved.

Without migrations, you'd have two bad options: (1) manually run SQL commands on each environment and pray you don't forget any, or (2) drop all tables and recreate them, losing all data. Migrations give you a third option: apply incremental, reversible changes in a consistent order across all environments.

Migration discipline means:
- Never modify the database schema by hand. Always create a migration.
- Never edit an existing migration that has been applied (especially in production). Create a new one instead.
- Always test downgrade as well as upgrade.
- Commit migration files to Git so every developer and every environment runs the same changes.

### Alembic

Alembic is the migration tool for SQLAlchemy. It reads your SQLAlchemy models, compares them to the current database state, and generates migration scripts that bridge the gap. This is called "autogeneration" — Alembic figures out what changed so you don't have to write migration SQL by hand (though you can).

Alembic uses a `versions/` directory to store migration files. Each file has a unique revision ID and knows which revision came before it (the `down_revision`), forming a linked list of changes.

### Alembic Init for Async

The standard `alembic init` creates a synchronous configuration. Since we're using async SQLAlchemy, we need the async template:

```bash
alembic init -t async alembic
```

This creates an `alembic/` directory with:
- `alembic.ini` — Alembic's configuration file (database URL, scripts location)
- `alembic/env.py` — the migration environment (how Alembic connects to the DB and discovers models)
- `alembic/versions/` — where migration scripts are stored
- `alembic/script.py.mako` — template for new migration files

The most important file to configure is `env.py`. You need to:
1. Point it to your async database URL
2. Import your `Base.metadata` so Alembic knows about your models
3. Import all your model modules so they're registered on the metadata

### Autogenerate from Models

The `autogenerate` feature is Alembic's killer feature. It compares your model definitions (what should exist) to the actual database (what does exist) and generates the SQL to reconcile them:

```bash
alembic revision --autogenerate -m "create manga and genre tables"
```

This generates a migration file in `alembic/versions/` containing `op.create_table(...)` calls for your Manga and Genre models. Always review the generated migration before applying it — autogenerate is smart but not perfect. It can miss some changes (like table renames, which it sees as "drop old + create new").

### Upgrade and Downgrade

```bash
# Apply all pending migrations
alembic upgrade head

# Apply next one migration
alembic upgrade +1

# Rollback one migration
alembic downgrade -1

# Rollback everything
alembic downgrade base

# See current migration status
alembic current

# See migration history
alembic history
```

`alembic upgrade head` is what you'll run most often — it applies all pending migrations to bring the database up to date. In production, this is typically run as part of deployment, before the new code starts serving requests.

## Your Task

### Step 1: Install Alembic

Install `alembic` and update `requirements.txt`.

### Step 2: Initialize Alembic with async template

From your project root, run:

```bash
alembic init -t async alembic
```

This creates `alembic.ini` in the project root and an `alembic/` directory.

### Step 3: Configure alembic.ini

Open `alembic.ini` and remove or comment out the `sqlalchemy.url` line. You'll set the URL programmatically in `env.py` instead (so it reads from your settings, not from a separate config file).

### Step 4: Configure env.py

This is the most important step. Open `alembic/env.py` and modify it to:

1. Add the project root to `sys.path` so imports work.
2. Import your `Settings` and create an instance to get the `DATABASE_URL`.
3. Import `Base` from `app.db.base` — this is how Alembic discovers your tables.
4. Import all your model modules (`app.models.manga`, `app.models.genre`) so they register on `Base.metadata`. The easiest way is to `import app.models` if your `__init__.py` imports them.
5. Set `target_metadata = Base.metadata`.
6. In `run_migrations_online()`, use your `DATABASE_URL` from settings instead of the one from `alembic.ini`.

### Step 5: Generate the first migration

Run:

```bash
alembic revision --autogenerate -m "create manga and genre tables"
```

A new file appears in `alembic/versions/`. Open it and review:
- The `upgrade()` function should contain `op.create_table(...)` calls for both `manga` and `genre` tables.
- The `downgrade()` function should contain `op.drop_table(...)` calls.
- Verify that all columns, types, indexes, and constraints are present.

### Step 6: Apply the migration

```bash
alembic upgrade head
```

### Step 7: Verify

Connect to your PostgreSQL database and verify the tables exist:

```bash
# Docker
docker exec -it mangashelf-db psql -U mangashelf -d mangashelf -c "\dt"

# Native
psql -d mangashelf -c "\dt"
```

You should see `manga`, `genre`, and `alembic_version` tables. The `alembic_version` table is how Alembic tracks which migrations have been applied.

### Step 8: Test downgrade and re-upgrade

```bash
alembic downgrade -1   # Rolls back — tables are dropped
alembic upgrade head    # Re-applies — tables are recreated
```

This verifies your migration is reversible.

## Expected Outcome
- `alembic/` directory exists with properly configured `env.py`
- `alembic/versions/` contains one migration file for creating manga and genre tables
- Running `alembic upgrade head` creates the tables in PostgreSQL
- Running `alembic downgrade -1` removes them
- `alembic history` shows one migration
- `alembic current` shows the current revision

## Hints
- The most common error is "Can't find module 'app'" from `env.py`. Fix this by adding `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` at the top of `env.py`.
- If autogenerate produces an empty migration (no changes detected), your models aren't being imported before Alembic checks the metadata. Make sure `import app.models` runs before `target_metadata = Base.metadata`.
- If you get an error about the enum type already existing during re-upgrade, add `checkfirst=True` to your enum creation or handle it in the migration.
- The async template's `env.py` already uses `AsyncEngine` — don't change it to sync.

## What I'll Look For In Review
- Alembic initialized with the async template (`-t async`)
- `env.py` reads DATABASE_URL from settings (not hardcoded in `alembic.ini`)
- All models are imported in `env.py` so autogenerate detects them
- The generated migration correctly creates both tables with all columns, types, and indexes
- Both upgrade and downgrade work without errors
