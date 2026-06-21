# Chapter 64 — Prometheus Metrics

## Concepts You'll Learn
- Metric types (counter, histogram, gauge, summary)
- Application instrumentation
- The /metrics endpoint and Prometheus scraping
- Custom application metrics

## Concept Deep Dive

### Metric Types

Prometheus defines four fundamental metric types, each suited to different kinds of measurements:

**Counter** — A value that only goes up. Use it for counting occurrences: total requests, total errors, total manga views. Counters reset to zero when the application restarts. Prometheus handles this by calculating rates (change per second) rather than using the raw value.

```python
from prometheus_client import Counter

manga_views_total = Counter(
    "manga_views_total",
    "Total number of manga page views",
    ["manga_id"]  # labels for grouping
)
manga_views_total.labels(manga_id="abc123").inc()
```

**Histogram** — Records observations (like request durations or response sizes) and buckets them. This lets you compute percentiles (P50, P95, P99) without storing every individual observation. Histograms are the workhorse metric for latency tracking.

```python
from prometheus_client import Histogram

request_duration = Histogram(
    "api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "endpoint", "status"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
```

**Gauge** — A value that can go up and down. Use it for current state: active connections, in-progress tasks, queue depth, memory usage. Unlike counters, gauges represent a snapshot of the current value.

```python
from prometheus_client import Gauge

active_readers = Gauge(
    "active_readers_gauge",
    "Number of currently active SSE reader connections"
)
active_readers.inc()   # new connection
active_readers.dec()   # connection closed
```

**Summary** — Similar to histogram but calculates quantiles on the client side. Generally prefer histograms because they are more flexible (you can aggregate histograms across instances, but not summaries).

### Application Instrumentation

Instrumentation means adding measurement points to your code. The `prometheus-fastapi-instrumentator` library automatically instruments all HTTP endpoints with request count, duration, and size metrics. But automatic instrumentation only covers the HTTP layer. **Custom metrics** reveal business-specific health.

Think about what questions you want to answer with metrics:
- How many manga are being viewed per minute? (Counter)
- What is the API latency at P99? (Histogram)
- How many Celery tasks are pending? (Gauge)
- How many image uploads succeed vs fail? (Counter with labels)

Labels (also called dimensions or tags) let you slice metrics. A single `api_requests_total` counter with labels for `method`, `path`, and `status` lets you query "POST requests to /manga that returned 500" without creating separate metrics for every combination. But be careful: every unique combination of label values creates a new time series. High-cardinality labels (like user_id) can overwhelm Prometheus.

### The /metrics Endpoint and Prometheus Scraping

Prometheus is a **pull-based** monitoring system. Your application exposes a `/metrics` endpoint, and Prometheus scrapes (fetches) it at regular intervals (typically every 15-30 seconds). The endpoint returns all metrics in Prometheus's text exposition format:

```
# HELP api_request_duration_seconds API request duration in seconds
# TYPE api_request_duration_seconds histogram
api_request_duration_seconds_bucket{method="GET",endpoint="/manga",status="200",le="0.01"} 42
api_request_duration_seconds_bucket{method="GET",endpoint="/manga",status="200",le="0.025"} 87
...
api_request_duration_seconds_sum{method="GET",endpoint="/manga",status="200"} 12.45
api_request_duration_seconds_count{method="GET",endpoint="/manga",status="200"} 100
```

Prometheus stores these time series and provides PromQL (Prometheus Query Language) for querying them. For example:
- `rate(api_requests_total[5m])` — requests per second over the last 5 minutes
- `histogram_quantile(0.99, rate(api_request_duration_seconds_bucket[5m]))` — P99 latency

The `/metrics` endpoint should not require authentication (Prometheus needs unauthenticated access from within your network). In production, restrict access via network rules (only the Prometheus server can reach it).

### Prometheus Scrape Configuration

Prometheus needs to know where to scrape. This is configured in `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "mangashelf-api"
    scrape_interval: 15s
    static_configs:
      - targets: ["api:8000"]
```

In Docker Compose, the target is the service name and port. Prometheus resolves `api` to the container's IP on the Docker network and scrapes `/metrics` every 15 seconds.

## Your Task

### Step 1: Install and Configure Base Instrumentation

Install `prometheus-fastapi-instrumentator` and `prometheus-client`. In your `app/main.py`, add the instrumentator:

```python
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator()
instrumentator.instrument(app)
instrumentator.expose(app, endpoint="/metrics")
```

This immediately gives you request count, duration, and size metrics for all endpoints.

### Step 2: Create Custom Metrics

Create `app/monitoring/metrics.py` with application-specific metrics:

**Counters:**
- `manga_views_total` — labeled by `manga_id` (but consider cardinality — maybe label by genre instead)
- `celery_tasks_total` — labeled by `task_name` and `status` (success/failure)
- `auth_attempts_total` — labeled by `result` (success/failure)
- `notifications_sent_total` — labeled by `type`

**Histograms:**
- `db_query_duration_seconds` — labeled by `operation` (select/insert/update)
- `image_processing_duration_seconds` — for upload processing time
- `search_query_duration_seconds` — for Meilisearch query time

**Gauges:**
- `active_sse_connections` — number of active SSE connections
- `celery_queue_length` — number of pending Celery tasks
- `db_pool_active_connections` — number of active database connections from the pool

### Step 3: Instrument Your Services

Add metric recording to key code paths:

In your manga service: increment `manga_views_total` when a manga detail is fetched.
In your Celery tasks: increment `celery_tasks_total` with the appropriate status label in a `try/except/finally`.
In your SSE endpoint: increment/decrement `active_sse_connections` on connect/disconnect.
In your database session management: record query durations.

### Step 4: Add Prometheus to Docker Compose

Add a `prometheus` service to `docker-compose.yml`:
- Image: `prom/prometheus:latest`
- Map port 9090
- Mount a prometheus configuration file

Create `monitoring/prometheus/prometheus.yml`:
- Scrape the api service at 15-second intervals
- Optionally scrape Redis exporter, PostgreSQL exporter (if you add them)

### Step 5: Verify Metrics

Start the stack and verify:
- `http://localhost:8000/metrics` returns Prometheus text format
- `http://localhost:9090` shows the Prometheus web UI
- In Prometheus, query `api_request_duration_seconds_count` and see data
- Generate some traffic and verify custom metrics are incrementing

### Step 6: Add Worker Metrics

Celery workers also need metrics. Configure the Celery worker to expose metrics:
- Use Celery signals (`task_prerun`, `task_postrun`, `task_failure`) to record task metrics
- Consider using `flower` (Celery monitoring tool) which has built-in Prometheus metrics, or expose a metrics endpoint from the worker process

## Expected Outcome
- `/metrics` endpoint returns Prometheus-format metrics
- Automatic HTTP metrics cover all endpoints (count, duration, size)
- Custom business metrics track manga views, task execution, SSE connections
- Prometheus successfully scrapes and stores metrics
- Prometheus web UI at port 9090 shows queryable data
- Celery task metrics are recorded (success/failure counts, duration)

## Hints
- `prometheus-fastapi-instrumentator` has built-in hooks for adding custom metrics. Check its `add()` method for instrumenting specific endpoints.
- For the database query duration histogram, you can use SQLAlchemy events (`before_cursor_execute` / `after_cursor_execute`) to measure query time without modifying every repository method.
- Be careful with high-cardinality labels. Labeling by `manga_id` creates a time series per manga. If you have thousands of manga, that is thousands of time series. Consider aggregating by genre or just tracking the total.
- The `/metrics` endpoint should be excluded from your application's own request metrics (to avoid recursive metric inflation). The instrumentator library typically handles this.

## What I'll Look For In Review
- Automatic HTTP instrumentation is enabled for all endpoints
- Custom metrics use the appropriate types (counters for counts, histograms for durations, gauges for current state)
- Metrics follow Prometheus naming conventions (`noun_unit_type`, e.g., `api_request_duration_seconds`)
- Labels are used thoughtfully (no high-cardinality explosion)
- Prometheus is configured to scrape the application and metrics appear in the UI
