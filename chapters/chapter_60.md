# Chapter 60 — Nginx Reverse Proxy

## Concepts You'll Learn
- Reverse proxy pattern (why not expose the application directly)
- TLS termination
- Security headers (CSP, HSTS, X-Frame-Options)
- Proxy headers (X-Forwarded-For, X-Real-IP)

## Concept Deep Dive

### Reverse Proxy Pattern

A reverse proxy sits between the internet and your application servers. Clients talk to the proxy, and the proxy forwards requests to the appropriate backend service. This is how virtually every production web application works — you never expose your application server (uvicorn, gunicorn) directly to the internet.

```
[Client] --> [Nginx] --> [FastAPI (uvicorn)]
                    \--> [Next.js]
                    \--> [MinIO console]
```

Why? Several reasons. First, **TLS termination**: Nginx handles HTTPS, decrypts the traffic, and forwards plain HTTP to your application. Your app does not need to manage TLS certificates. Second, **static file serving**: Nginx serves static assets (images, CSS, JS) far more efficiently than a Python application server. Third, **request buffering**: Nginx buffers incoming requests and sends them to the application as complete requests. This protects slow application servers from holding connections open while clients slowly upload data. Fourth, **load balancing**: Nginx can distribute requests across multiple application instances.

For MangaShelf, Nginx will serve as the single entry point. All traffic comes in through Nginx on ports 80/443, and Nginx routes it to the correct service based on the URL path.

### TLS Termination

TLS (Transport Layer Security, the successor to SSL) encrypts traffic between the client and server. In production, you get TLS certificates from Let's Encrypt (free) or a certificate authority. For local development, you generate a self-signed certificate.

Nginx handles TLS termination — it decrypts incoming HTTPS requests and forwards plain HTTP to the backend. This means your FastAPI application only deals with HTTP internally, simplifying its configuration.

```nginx
server {
    listen 443 ssl;
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;

    location /api/ {
        proxy_pass http://api:8000;
    }
}
```

The connection between Nginx and your application is plain HTTP over the internal Docker network. This is safe because Docker's internal network is not accessible from outside. The encrypted segment is the one facing the internet — from the client to Nginx.

For local development, self-signed certificates trigger browser warnings ("Your connection is not private"). You can accept the warning and proceed. Some developers add the self-signed CA to their system's trust store to suppress the warning.

### Security Headers

HTTP security headers instruct browsers to enable or restrict certain behaviors. They are your second line of defense (after fixing vulnerabilities in your code). Nginx is the ideal place to add these because they apply to all responses regardless of which backend served them.

**Content-Security-Policy (CSP)**: Controls which resources the browser is allowed to load. Prevents cross-site scripting (XSS) by restricting script sources.

**Strict-Transport-Security (HSTS)**: Tells the browser to always use HTTPS for your domain. After receiving this header, the browser will refuse to connect over plain HTTP for the specified duration.

**X-Frame-Options**: Prevents your site from being embedded in an iframe on another domain. This mitigates clickjacking attacks.

**X-Content-Type-Options**: Prevents the browser from MIME-sniffing a response away from the declared content type. Setting it to `nosniff` means the browser trusts your Content-Type header.

```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:;" always;
```

The `always` keyword ensures headers are added to all responses, including error pages (4xx, 5xx).

### Proxy Headers

When Nginx proxies a request, the backend sees Nginx's IP address as the client, not the actual client's IP. This breaks logging, rate limiting, and geolocation. **Proxy headers** solve this by carrying the original client information through the proxy.

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

- `X-Real-IP`: The direct client IP address (the one Nginx sees).
- `X-Forwarded-For`: A chain of all proxy IPs. If there are multiple proxies, each appends its address. Your application reads the first address in the chain as the original client.
- `X-Forwarded-Proto`: Whether the original request was HTTP or HTTPS. Your application needs this to generate correct redirect URLs.

On the FastAPI side, if you are using a trusted proxy, configure the ASGI server to trust these headers. Uvicorn supports `--proxy-headers` and `--forwarded-allow-ips` flags to correctly interpret proxy headers.

## Your Task

### Step 1: Create Nginx Configuration

Create `nginx/nginx.conf` with:

**HTTP server** (port 80) — redirects all traffic to HTTPS:
```nginx
server {
    listen 80;
    return 301 https://$host$request_uri;
}
```

**HTTPS server** (port 443) with routing rules:
- `/api/` — proxy to the `api` service at port 8000
- `/minio/` — proxy to MinIO console at port 9001
- `/` — proxy to the frontend Next.js service at port 3000 (or serve static files)
- Add proxy headers (X-Real-IP, X-Forwarded-For, X-Forwarded-Proto)
- Add security headers
- Enable gzip compression for text-based content types

### Step 2: Generate Self-Signed TLS Certificate

Create a script `nginx/generate-cert.sh` that uses `openssl` to generate a self-signed certificate and key:

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/server.key \
  -out nginx/certs/server.crt \
  -subj "/CN=localhost"
```

Run this script to generate the certificate files. Add `nginx/certs/` to `.gitignore` (certificates should not be committed).

### Step 3: Add Nginx to Docker Compose

Add an `nginx` service to `docker-compose.yml`:
- Image: `nginx:alpine`
- Map ports: 80 and 443
- Mount `nginx/nginx.conf` as the configuration
- Mount `nginx/certs/` for TLS certificates
- Depends on: api (and frontend if running)

### Step 4: Configure SSE Proxy Settings

For your SSE endpoint (from Chapter 51-52), Nginx needs special configuration to avoid buffering the streaming response:

```nginx
location /api/v1/events/stream {
    proxy_pass http://api:8000;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
    proxy_buffering off;
    proxy_cache off;
}
```

Without `proxy_buffering off`, Nginx will buffer SSE events and the client will not receive them in real-time.

### Step 5: Enable Gzip Compression

Add gzip configuration to Nginx (this replaces or supplements any response compression you built in Chapter 40):

```nginx
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css application/json application/javascript text/xml;
```

This compresses responses at the proxy level, which is more efficient than compressing in Python.

### Step 6: Test Everything

Start the full stack and verify:
- `http://localhost` redirects to `https://localhost`
- `https://localhost/api/docs` shows the Swagger UI
- `https://localhost/minio/` shows the MinIO console
- SSE endpoint works through Nginx (no buffering issues)
- Check response headers for security headers using curl:

```bash
curl -kI https://localhost/api/v1/manga
# Should include X-Frame-Options, X-Content-Type-Options, etc.
```

The `-k` flag tells curl to accept the self-signed certificate.

## Expected Outcome
- All traffic goes through Nginx on ports 80/443
- HTTP redirects to HTTPS
- API, frontend, and MinIO are accessible through Nginx routing
- Security headers are present on all responses
- Proxy headers correctly carry client IP to the backend
- SSE streaming works without buffering delays
- Gzip compression reduces response sizes for text content

## Hints
- If you get 502 Bad Gateway, the upstream service is not reachable. Check that the service name in `proxy_pass` matches the Docker Compose service name and the port is correct.
- For the SSE location block, order matters in Nginx — more specific locations should come before more general ones. Put the SSE location before the general `/api/` location.
- Use `docker compose logs nginx` to see Nginx access and error logs for debugging.
- The `proxy_read_timeout` directive controls how long Nginx waits for a response from the backend. For SSE, set it high (e.g., `proxy_read_timeout 3600s`) or the connection will drop after the default 60 seconds.

## What I'll Look For In Review
- Nginx correctly routes to all backend services based on URL path
- TLS is configured (even self-signed for local dev)
- Security headers are present on all responses
- Proxy headers are set so the backend sees real client IPs
- SSE endpoint has buffering disabled and a long read timeout
