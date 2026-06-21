# Chapter 67 — Load Testing & Performance Baseline

## Concepts You'll Learn
- Load testing methodology (ramp up, sustained, spike)
- Locust framework for writing load tests
- Identifying bottlenecks (CPU, database, cache, network)
- SLOs (Service Level Objectives)

## Concept Deep Dive

### Load Testing Methodology

Load testing answers a critical question: "How does my system behave under realistic traffic?" It is not about finding bugs in logic — it is about finding limits in capacity, latency, and reliability. Without load testing, your first time seeing your system under heavy load is when real users show up. That is not a good time to discover problems.

There are three common load test patterns:

**Ramp up** — Start with a few users and gradually increase. This reveals the point where performance starts to degrade. Maybe your system handles 50 concurrent users fine, but at 75, latency doubles. The ramp-up pattern helps you find this inflection point.

**Sustained load** — Hold a constant number of concurrent users for an extended period (10-30 minutes). This finds problems that accumulate over time: memory leaks, connection pool exhaustion, growing response times due to cache eviction.

**Spike test** — Suddenly jump from normal load to extreme load, then back down. This tests how your system handles sudden traffic bursts (e.g., a popular manga gets a new chapter and thousands of readers arrive at once) and whether it recovers gracefully after the spike.

### Locust Framework

Locust is a Python-based load testing tool that lets you write test scenarios as Python code. Users are modeled as classes that perform sequences of actions with think times (pauses between actions, simulating real user behavior).

```python
from locust import HttpUser, task, between

class MangaReader(HttpUser):
    wait_time = between(1, 5)  # 1-5 second pause between tasks

    @task(3)  # weight: 3x more likely than weight-1 tasks
    def browse_manga(self):
        self.client.get("/api/v1/manga?limit=20")

    @task(2)
    def search(self):
        self.client.get("/api/v1/search?q=naruto")

    @task(1)
    def view_manga(self):
        self.client.get("/api/v1/manga/one-piece")
```

The `@task` decorator defines what users do. The weight parameter controls the relative frequency of each task — in this example, browsing happens 3x as often as viewing a specific manga, which reflects real usage patterns (more people browse than deep-dive into a specific title).

`wait_time = between(1, 5)` means each user pauses 1-5 seconds between actions. This is crucial — without think time, each simulated user makes requests as fast as possible, which is unrealistic and produces misleading results. Real users read, scroll, and think between actions.

Locust provides a web UI at `http://localhost:8089` where you can set the number of users, ramp-up rate, and watch real-time charts of requests per second, response times, and failure rates.

### Identifying Bottlenecks

When load testing reveals performance degradation, you need to identify the bottleneck. The system is a chain: client → Nginx → FastAPI → database/Redis/MinIO, and the chain is only as fast as its slowest link.

**CPU-bound**: If your Python process hits 100% CPU, you are limited by computation. Symptoms: response times increase linearly with load, CPU monitoring shows saturation. Solutions: optimize hot code paths, add more workers/instances.

**Database-bound**: If PostgreSQL becomes the bottleneck, you will see slow queries, connection pool exhaustion, or lock contention. Symptoms: `pg_stat_activity` shows many active queries, response times spike when database queries are involved. Solutions: add indexes, optimize queries, increase connection pool, add read replicas.

**Memory-bound**: If Redis cache misses increase under load (because the cache is full and evicting entries), response times increase as more requests fall through to the database. Symptoms: Redis memory at max, cache hit ratio drops. Solutions: increase Redis memory, adjust eviction policy, cache more selectively.

**Connection-bound**: You run out of database connections or network sockets. Symptoms: connection timeout errors, "too many connections" from PostgreSQL. Solutions: tune connection pool sizes, add pgbouncer, reduce connection hold time.

Your monitoring from Chapters 64-65 (Prometheus + Grafana) should be running during load tests. The dashboards tell you exactly which component is struggling.

### Service Level Objectives (SLOs)

An SLO is a target for system performance that you commit to. SLOs define what "good enough" means and give you a clear bar for when to investigate vs when to relax.

Common SLOs for a web API:
- **Availability**: 99.9% of requests return a non-5xx response (allows ~43 minutes of downtime per month)
- **Latency**: P99 < 200ms for read endpoints, P99 < 500ms for write endpoints
- **Error rate**: < 0.1% of requests return 5xx errors

SLOs should be based on user impact, not arbitrary numbers. A manga reading endpoint needs to be fast (users notice 200ms+). A bulk admin operation can tolerate higher latency. Set different SLOs for different endpoint categories.

Your load test results establish a **baseline** — what your system currently achieves. If your baseline P99 is 150ms at 100 concurrent users, you know you are meeting your 200ms SLO with margin. If the baseline is 350ms, you have work to do.

## Your Task

### Step 1: Install Locust

Install `locust` in your development environment (it does not need to be in the production Docker image). You can install it in a separate virtual environment or in your existing one.

### Step 2: Create User Scenarios

Create `tests/load/locustfile.py` with realistic user scenarios:

**BrowsingUser** (weight: most common):
- Browse manga list (GET /api/v1/manga with pagination)
- Search for manga (GET /api/v1/search)
- View manga detail (GET /api/v1/manga/{slug})
- View chapter list for a manga

**ReaderUser** (weight: second most common):
- View manga detail
- Get chapter pages (GET /api/v1/manga/{slug}/chapters/{num}/pages)
- Save reading progress (PUT /api/v1/reading-progress)
- Sequential page navigation (simulate reading multiple pages)

**AuthenticatedUser** (weight: less common):
- Login (POST /api/v1/auth/login) — do this in `on_start`
- Add to library (POST /api/v1/library)
- Post a review (POST /api/v1/reviews)
- Browse feed (GET /api/v1/feed)

Set realistic think times (1-5 seconds for browsing, shorter for page turns in the reader).

### Step 3: Seed Test Data

Create a script or fixture that ensures test data exists before load testing:
- At least 50 manga with chapters and pages
- Several user accounts for authenticated scenarios
- Enough data that queries are realistic (not just querying empty tables)

You can run this as a setup step before the load test, or use the `on_start` method in Locust to create data.

### Step 4: Run the Load Test

Start your full Docker Compose stack, then run Locust:

```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

Open the Locust web UI at http://localhost:8089. Run the following test sequence:

1. **Ramp up**: Start 0 users, ramp to 50 over 2 minutes. Observe how metrics change.
2. **Sustained**: Hold 50 users for 5 minutes. Record baseline metrics.
3. **Increase**: Ramp to 100 users over 1 minute. Hold for 5 minutes.
4. **Spike**: Ramp to 200 users over 30 seconds. Hold for 2 minutes.

### Step 5: Record Baseline Metrics

For each load level (50, 100, 200 users), record:
- Requests per second (total)
- P50 latency (median)
- P95 latency
- P99 latency
- Error rate (percentage of failed requests)
- Which endpoints are slowest

Record this data in a markdown file or a comment in the locustfile. This is your performance baseline.

### Step 6: Identify Bottlenecks

During the load test, watch your Grafana dashboards (Chapter 65):
- Is the database connection pool saturating?
- Is Redis cache hit ratio dropping?
- Are specific endpoints disproportionately slow?
- Is the API container's CPU maxed out?

Document which component is the first bottleneck as you increase load. Explain why it is the bottleneck and what you would do to address it (you do not need to fix it now — just understand it).

### Step 7: Define SLOs

Based on your baseline results, define SLOs for MangaShelf:
- Availability target (e.g., 99.9%)
- Read endpoint P99 latency target
- Write endpoint P99 latency target
- Error rate target
- Document these in a markdown file or as comments in your codebase

## Expected Outcome
- Locust load test with realistic user scenarios and think times
- Baseline metrics documented for 50, 100, and 200 concurrent users
- Bottleneck identified and explained (database, connection pool, CPU, etc.)
- SLOs defined based on actual baseline data
- Load test is reproducible (same test can be run again after optimizations to measure improvement)

## Hints
- For authenticated scenarios, perform login in `on_start()` and store the token on `self`. Include it in subsequent requests via `self.client.get(url, headers={"Authorization": f"Bearer {self.token}"})`.
- Locust's `--headless` mode runs without the web UI and is useful for CI integration: `locust -f locustfile.py --headless -u 100 -r 10 --run-time 5m`.
- If you see many connection errors, it might not be your app — it might be your machine's TCP connection limit. On macOS, check `ulimit -n`.
- Do not load test against production databases or external services. Always test against your local Docker stack.

## What I'll Look For In Review
- User scenarios reflect realistic usage patterns with appropriate weights and think times
- Baseline metrics are recorded at multiple load levels
- The first bottleneck is correctly identified and explained
- SLOs are reasonable (not too aggressive, not too lenient) and based on actual data
- The load test is reproducible and well-documented
