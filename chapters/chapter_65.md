# Chapter 65 — Grafana Dashboards

## Concepts You'll Learn
- Dashboard design principles
- Grafana panels (time series, stat, gauge, table)
- PromQL queries for dashboards
- Alerting rules

## Concept Deep Dive

### Dashboard Design Principles

A monitoring dashboard should answer a question at a glance. The most dangerous dashboards are the ones packed with every metric available — when everything is important, nothing is. Good dashboards follow a hierarchy: the most critical information is at the top, and details are below.

The **RED method** (Rate, Errors, Duration) is a proven framework for service dashboards:
- **Rate** — requests per second. Is the service handling normal traffic? Sudden drops might mean an outage; sudden spikes might be a DDoS.
- **Errors** — error rate as a percentage. Is the service healthy? A jump from 0.1% to 5% error rate demands immediate investigation.
- **Duration** — request latency at P50, P95, P99. Is the service responsive? P50 is "typical user experience." P99 is "worst 1% of users" — this is where slow queries and cold caches hide.

A separate **business dashboard** tracks application-specific metrics: active readers, manga uploads, new registrations. These do not trigger alerts but inform product decisions.

Layout convention: place the most critical panels (error rate, latency) at the top-left where the eye lands first. Use consistent color coding — green for healthy, yellow for warning, red for critical. Time range should default to the last hour for operational dashboards and the last 24 hours for business dashboards.

### Grafana Panels

Grafana offers several visualization types:

**Time series** — The bread-and-butter panel. Shows metrics over time as line graphs. Use for: request rate, latency, error rate, throughput. Multiple series can overlay (e.g., P50 and P99 on the same graph).

**Stat** — A single large number. Use for: current error rate, active users, total requests today. Supports color thresholds (green when <1%, yellow when <5%, red when >5%).

**Gauge** — A visual meter. Use for: CPU utilization, memory usage, connection pool saturation. Shows current value against a maximum.

**Table** — Tabular data. Use for: top endpoints by error count, slowest queries, top manga by views.

**Bar chart** — Discrete comparisons. Use for: requests by status code, tasks by type, traffic by hour of day.

### PromQL Queries

PromQL is how you ask Prometheus questions. The key operations:

**Rate** — `rate(metric[5m])` calculates the per-second rate of a counter over the last 5 minutes. This turns a monotonically increasing counter into a useful "X per second" metric.

```promql
# Requests per second
rate(http_requests_total[5m])

# Error rate as a percentage
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100
```

**Histogram quantile** — `histogram_quantile(0.99, rate(metric_bucket[5m]))` computes the Pth percentile from histogram buckets.

```promql
# P99 latency
histogram_quantile(0.99, rate(api_request_duration_seconds_bucket[5m]))

# P50 (median) latency
histogram_quantile(0.50, rate(api_request_duration_seconds_bucket[5m]))
```

**Aggregation** — `sum()`, `avg()`, `max()`, `min()` aggregate across label dimensions.

```promql
# Total request rate across all endpoints
sum(rate(http_requests_total[5m]))

# Request rate per endpoint
sum by (endpoint) (rate(http_requests_total[5m]))
```

**Filtering** — Label matchers filter time series. `=` for exact match, `=~` for regex, `!=` for negation.

```promql
# Only 5xx errors
rate(http_requests_total{status=~"5.."}[5m])

# Exclude the /metrics endpoint
rate(http_requests_total{endpoint!="/metrics"}[5m])
```

### Alerting Rules

Grafana can fire alerts when metrics cross thresholds. Alerts should be actionable — every alert should require a human to do something. Non-actionable alerts train people to ignore them (alert fatigue).

Good alerts for MangaShelf:
- Error rate > 5% for 5 minutes → something is broken, investigate now
- P99 latency > 2 seconds for 10 minutes → performance degradation
- Database connection pool > 80% utilized → may need to increase pool size
- Disk usage > 85% → storage filling up

Alerts have three states: OK (green), Pending (threshold crossed but within grace period), and Firing (threshold exceeded for the required duration). The duration prevents flapping — a brief latency spike does not trigger an alert.

## Your Task

### Step 1: Add Grafana to Docker Compose

Add a `grafana` service to `docker-compose.yml`:
- Image: `grafana/grafana:latest`
- Map port 3000
- Named volume for Grafana data (dashboards, settings)
- Environment: `GF_SECURITY_ADMIN_PASSWORD=admin` (for local dev)

### Step 2: Provision the Prometheus Datasource

Create `monitoring/grafana/provisioning/datasources/prometheus.yml`:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

Mount this into the Grafana container at `/etc/grafana/provisioning/datasources/`. This auto-configures Prometheus as a data source so you do not have to set it up manually in the UI.

### Step 3: Create the API Health Dashboard

Create `monitoring/grafana/dashboards/api-health.json` (you can build this in the Grafana UI and then export the JSON). The dashboard should have these panels:

**Row 1 — Overview stats (Stat panels):**
- Current request rate (requests/sec)
- Current error rate (percentage)
- P99 latency (current)
- Active SSE connections

**Row 2 — Time series:**
- Request rate over time (line graph)
- Error rate over time (line graph, with threshold line at 5%)
- Latency over time (P50, P95, P99 as separate lines on one graph)

**Row 3 — Infrastructure:**
- Database active connections (gauge, max = pool size)
- Redis cache hit ratio (calculated from hits / (hits + misses))
- Celery task rate (success vs failure stacked)

### Step 4: Create the Business Dashboard

Create `monitoring/grafana/dashboards/business.json` with:

- Active readers (gauge — from `active_sse_connections` or a custom metric)
- Manga views per hour (bar chart)
- New user registrations per day (time series)
- Top 10 manga by views (table)
- Search queries per hour (time series)

### Step 5: Provision Dashboards

Create `monitoring/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
apiVersion: 1
providers:
  - name: "MangaShelf"
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

Mount your dashboard JSON files into `/var/lib/grafana/dashboards/` in the Grafana container. This auto-loads dashboards on startup.

### Step 6: Configure Alerting Rules

In Grafana, create alert rules (either through the UI or in provisioned files):
- Alert if error rate exceeds 5% for 5 minutes
- Alert if P99 latency exceeds 2 seconds for 10 minutes
- Alert if database connection pool exceeds 80% for 5 minutes

For local development, configure alerts to send to a "log" contact point (writes to Grafana logs). In production, you would configure email, Slack, or PagerDuty.

### Step 7: Test Under Load

Generate some traffic (manually or with a script) and verify:
- The dashboards show real data
- Latency graphs respond to load
- Error rate panel works (temporarily return 500 from an endpoint)
- Alert fires when error rate threshold is exceeded

## Expected Outcome
- Grafana is accessible at http://localhost:3000 with auto-provisioned Prometheus datasource
- API Health dashboard shows request rate, error rate, latency, and infrastructure metrics
- Business dashboard shows active readers, views, registrations
- Dashboards use appropriate panel types (stat, time series, gauge, table)
- Alert rules are configured for critical thresholds
- Dashboards load automatically from provisioned JSON files

## Hints
- The easiest way to create dashboards is in the Grafana UI first, then export the JSON (Dashboard settings > JSON Model). Copy this into your provisioning file.
- For the Redis cache hit ratio, if you are not exposing Redis metrics directly, you can create a custom metric in your application that tracks cache hits and misses from your caching layer (Chapter 41).
- PromQL's `rate()` function requires a counter metric. Applying `rate()` to a gauge gives wrong results. Use `deriv()` for gauges if you need rate of change.
- For the P99 latency panel, the `histogram_quantile` function needs the `_bucket` metric (not `_sum` or `_count`).

## What I'll Look For In Review
- Dashboards follow the RED method hierarchy (rate, errors, duration at the top)
- PromQL queries are correct (rate on counters, histogram_quantile for percentiles)
- Dashboard provisioning works (Grafana starts with dashboards pre-loaded)
- Panel types match the data they display (do not use a time series for a single current value)
- Alert rules are actionable and have appropriate duration thresholds to prevent flapping
