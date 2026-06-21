# Chapter 70 — Database Read Replicas & Scaling

## Concepts You'll Learn
- Read/write splitting for database scalability
- PostgreSQL streaming replication
- Connection routing in the application layer
- Eventual consistency trade-offs

## Concept Deep Dive

### Read/Write Splitting

Most web applications have an asymmetric read/write ratio. MangaShelf's API is probably 80-90% reads (browsing manga, loading chapters, viewing profiles, searching) and 10-20% writes (creating reviews, updating progress, uploading). If you can send read queries to a separate database server (a replica), you cut the primary server's load dramatically.

```
Write requests → Primary (read-write)
Read requests  → Replica (read-only)
```

The primary database handles all writes and replicates changes to one or more replicas. Replicas are read-only copies that serve read queries. This doubles (or more) your database capacity for reads without any application logic changes — you just route queries to the right server.

In your application, this means maintaining two database sessions: a write session that connects to the primary, and a read session that connects to the replica. The routing decision happens at the endpoint or service level: "this endpoint only reads data, use the replica."

### PostgreSQL Streaming Replication

PostgreSQL's built-in streaming replication works by having the primary continuously send its Write-Ahead Log (WAL) to the replica. The WAL is a sequential log of every change made to the database. The replica applies these changes to maintain a near-identical copy.

Setting up replication involves configuring the primary to accept replication connections and configuring the replica to connect to the primary and receive WAL data. In Docker Compose, this means running two PostgreSQL containers with specific configuration.

The primary needs:
```
wal_level = replica
max_wal_senders = 3
```

The replica needs:
```
primary_conninfo = 'host=db port=5432 user=replicator password=...'
```

Replication lag — the delay between a write on the primary and it appearing on the replica — is typically milliseconds in a healthy system. But under heavy write load or network issues, it can grow to seconds. This lag is the source of eventual consistency issues.

### Connection Routing

Your application needs a clean way to choose between the primary and replica connections. The cleanest approach is a dependency injection that provides the correct session based on the operation type.

```python
# app/db/routing.py
from app.db.session import primary_engine, replica_engine

async def get_write_session():
    """Session connected to the primary — use for writes."""
    async with AsyncSession(primary_engine) as session:
        yield session

async def get_read_session():
    """Session connected to the replica — use for reads."""
    async with AsyncSession(replica_engine) as session:
        yield session
```

In your endpoints, choose the appropriate dependency:

```python
@router.get("/manga")
async def list_manga(db: AsyncSession = Depends(get_read_session)):
    # This query hits the replica
    ...

@router.post("/manga")
async def create_manga(db: AsyncSession = Depends(get_write_session)):
    # This query hits the primary
    ...
```

This is explicit and easy to reason about. Some frameworks offer automatic routing (send SELECTs to replica, everything else to primary), but explicit routing gives you control over which queries tolerate eventual consistency.

### Eventual Consistency Trade-Offs

When you read from a replica, you might see slightly stale data. This is **eventual consistency** — the replica will eventually have all the data, but there is a window (usually milliseconds, sometimes seconds) where it lags behind.

For some operations, this is perfectly fine:
- Browsing the manga catalog (a manga created 1 second ago not showing up is not noticeable)
- Search results (Meilisearch already has its own sync delay)
- Activity feeds (a 1-second delay is invisible)
- Analytics queries (already working with historical data)

For other operations, stale data causes bugs:
- **Read-after-write**: User creates a review, then immediately loads the page and does not see their review. The write went to the primary, the read goes to the replica, and the replica has not caught up yet. Solution: use the primary for reads that follow writes (same request or same user session for a brief period).
- **Authentication**: Checking if a user exists during login must hit the primary. If you check the replica, a just-registered user might not be found.
- **Inventory/counter operations**: Anything where reading stale data leads to wrong business decisions (double-spending, over-counting).

The rule of thumb: use replicas for list/search/browse endpoints. Use the primary for auth, for any endpoint that follows a write, and for any query where correctness depends on the latest data.

Document your routing decisions. Future developers need to know which endpoints tolerate eventual consistency and which do not.

## Your Task

### Step 1: Add a PostgreSQL Replica to Docker Compose

Modify `docker-compose.yml` to add a replica service:

**db (primary):**
- Add environment variables or custom postgresql.conf for replication:
  - `wal_level=replica`
  - `max_wal_senders=3`
  - `max_replication_slots=3`
- Create a replication user with appropriate permissions

**db-replica:**
- Image: `postgres:16`
- Configure as a standby with `primary_conninfo` pointing to the `db` service
- Depends on: `db` with health check
- Map to a different port (e.g., 5433) for external debugging access

You may need a custom initialization script for the replica that uses `pg_basebackup` to create the initial copy from the primary. This is the trickiest part of the setup — research PostgreSQL Docker replication setups for guidance.

### Step 2: Create Connection Routing

Create `app/db/routing.py` with:
- `primary_engine` — connects to the primary database (your existing DATABASE_URL)
- `replica_engine` — connects to the replica (a new DATABASE_REPLICA_URL setting)
- `get_write_session()` — async dependency providing a session on the primary
- `get_read_session()` — async dependency providing a session on the replica
- If `DATABASE_REPLICA_URL` is not configured (e.g., in development), `get_read_session` falls back to the primary engine

Add `DATABASE_REPLICA_URL` to your Settings class with a default of `None`.

### Step 3: Modify the Database Dependency

Update (or create an alternative to) your existing `get_db` dependency to accept a `read_only` parameter:

```python
def get_db(read_only: bool = False):
    if read_only:
        return Depends(get_read_session)
    return Depends(get_write_session)
```

Or create two separate dependencies (`get_read_db`, `get_write_db`) and update endpoints to use the appropriate one.

### Step 4: Route High-Traffic Read Endpoints to the Replica

Update these endpoints to use the read session:
- `GET /manga` (list manga)
- `GET /manga/{slug}` (manga detail)
- `GET /manga/discover` (discovery/filtering)
- `GET /search` (search)
- `GET /feed` (activity feed)
- `GET /manga/{slug}/chapters/{num}/pages` (reader pages)
- All analytics endpoints (Chapter 69)

Keep these on the primary (write session):
- All POST, PUT, PATCH, DELETE endpoints
- `GET /users/me` (should always reflect latest state)
- `GET /notifications` (should show the latest notifications immediately)
- `GET /auth/*` (all authentication endpoints)

### Step 5: Document Consistency Decisions

Create documentation (comments in code or a dedicated file) that lists:
- Which endpoints use the replica (and why it is safe)
- Which endpoints use the primary (and why they need strong consistency)
- How to handle the "read-after-write" problem for specific flows

### Step 6: Handle Read-After-Write for Critical Flows

For flows where a user writes and then immediately reads:
- **Review creation**: After creating a review, the response should include the created review (from the primary). The subsequent page load can safely use the replica because the user has already seen their review in the creation response.
- **Library updates**: After changing library status, return the updated status in the response. The library list page can use the replica.

The general pattern: return the written data in the write response so the user sees it immediately, even if the next read from the replica is slightly stale.

### Step 7: Verify Replication

Test that replication is working:
1. Start the Docker stack
2. Create a manga via the API (writes to primary)
3. Query the replica directly to verify the data appears
4. Check replication lag: `SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn(), pg_last_xact_replay_timestamp() FROM pg_stat_wal_receiver;` (run on the replica)

## Expected Outcome
- PostgreSQL replica is running in Docker Compose, receiving streaming replication from the primary
- Application has two database connection pools (primary and replica)
- High-traffic read endpoints use the replica
- Write endpoints and consistency-critical reads use the primary
- Routing decisions are documented with reasoning
- Replication lag is minimal (sub-second under normal conditions)
- If the replica is unavailable, read endpoints fall back to the primary

## Hints
- Setting up PostgreSQL replication in Docker can be complex. Consider using a Docker image specifically designed for replication (like `bitnami/postgresql`) which simplifies the initial setup.
- For the fallback behavior, wrap the replica session creation in a try/except. If the replica connection fails, return a primary session instead. Log a warning when this happens.
- Monitor replication lag with a Prometheus metric. If lag exceeds a threshold, you might temporarily route all reads to the primary.
- Do not use the replica for migrations or schema changes. Alembic must always run against the primary.

## What I'll Look For In Review
- Docker Compose properly configures streaming replication between primary and replica
- Connection routing is clean and uses dependency injection
- Endpoint-level routing decisions are explicit and documented
- Fallback to primary works when the replica is unavailable
- Read-after-write consistency is handled for critical user flows
