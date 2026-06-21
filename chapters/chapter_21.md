# Chapter 21 — Rate Limiting & Token Revocation

## Concepts You'll Learn
- Sliding window rate limiting and why it matters
- Token blacklisting and the logout problem with JWTs
- Implementing a proper logout flow
- Security hardening for authentication endpoints

## Concept Deep Dive

### Rate Limiting

Rate limiting controls how many requests a client can make in a given time window. Without it, your API is vulnerable to:

- **Brute force attacks**: An attacker tries thousands of passwords per minute on your login endpoint.
- **Denial of Service**: A single client floods your API with requests, overwhelming the server.
- **Scraping**: Someone programmatically downloads your entire manga catalog.

The idea is simple: track how many requests each client makes, and reject excess requests with a `429 Too Many Requests` response.

**Sliding window** rate limiting is more sophisticated than fixed windows. A fixed window (e.g., "100 requests per minute") resets at the start of each minute. This means a client can send 100 requests at 12:00:59 and another 100 at 12:01:00 — 200 requests in 2 seconds. A sliding window counts requests in a rolling time period, providing a smoother limit.

The algorithm for an in-memory sliding window:

```python
import time
from collections import defaultdict

class SlidingWindowLimiter:
    def __init__(self):
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        window_start = now - window_seconds

        # Remove timestamps outside the window
        self.requests[key] = [
            ts for ts in self.requests[key] if ts > window_start
        ]

        if len(self.requests[key]) >= max_requests:
            return False

        self.requests[key].append(now)
        return True
```

For identifying clients, you can use the IP address (`request.client.host`), or for authenticated endpoints, the user ID. IP-based limiting has caveats (multiple users behind a NAT share an IP), but it's a reasonable starting point.

Important: this in-memory implementation only works for a single-process server. In production with multiple workers/containers, you'd use Redis (which you'll add later in the curriculum). For now, in-memory is fine for learning the pattern.

### Token Blacklisting and the JWT Logout Problem

JWTs are stateless — the server doesn't store them. This is a feature (no session store, easy to scale) and a bug (you can't invalidate a JWT). When a user logs out, you can delete the token from the client, but if an attacker has a copy, they can use it until it expires.

Token blacklisting solves this. When a user logs out, you add their token's `jti` (JWT ID) to a blacklist. On every request, you check: "is this token's `jti` blacklisted?" If yes, reject it.

```python
# In-memory blacklist (will move to Redis later)
token_blacklist: set[str] = set()

def blacklist_token(jti: str) -> None:
    token_blacklist.add(jti)

def is_token_blacklisted(jti: str) -> bool:
    return jti in token_blacklist
```

This slightly breaks the "stateless" nature of JWTs — you now need to check a store on every request. But the alternative (letting stolen tokens work until expiry) is worse. In practice, the blacklist is small (only recently logged-out tokens) and the lookup is O(1) in a set or Redis.

A subtlety: you only need to keep blacklisted JTIs until the token's natural expiration. After that, the token would be rejected anyway (expired). So your blacklist can have TTLs matching the token lifetime, keeping it small.

### The Logout Flow

Logout with JWTs typically works like this:

1. Client sends `POST /auth/logout` with the access token in the Authorization header.
2. Server decodes the token, extracts the `jti` (and optionally the `exp`).
3. Server adds the `jti` to the blacklist.
4. Server returns 200.
5. If a refresh token was provided, blacklist its `jti` too.

From this point, any request with the blacklisted token is rejected by `get_current_user`.

```python
@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_active_user),
    token: str = Depends(oauth2_scheme),
):
    payload = decode_token(token)
    jti = payload.get("jti")
    blacklist_token(jti)
    return {"message": "Successfully logged out"}
```

### Security Hardening for Auth Endpoints

Authentication endpoints are the most attacked surface of any API. Specific hardening measures:

1. **Stricter rate limits on login**: 5 attempts per minute per IP (vs. 100/min for general API). This makes brute force impractical.
2. **Stricter rate limits on registration**: Prevent mass account creation (spam, bot armies).
3. **Generic error messages**: "Invalid credentials" for both wrong email and wrong password. Don't say "email not found" — that reveals which emails are registered.
4. **Account lockout** (optional): After N failed login attempts, temporarily lock the account. But be careful — this can be a DoS vector (attacker locks out legitimate users).

The rate limit configuration should be different per endpoint type:

```python
# General API: 100 requests per minute
# Login: 5 requests per minute per IP
# Registration: 3 requests per minute per IP
# Token refresh: 10 requests per minute
```

## Your Task

### Step 1: Create the rate limiter

Create `app/middleware/rate_limit.py` with:

- A `SlidingWindowRateLimiter` class that stores request timestamps in memory (dict of lists or deque).
- A method `is_allowed(key: str, max_requests: int, window_seconds: int) -> bool` that implements the sliding window algorithm.
- Automatic cleanup of old timestamps to prevent memory leaks.

### Step 2: Create rate limit middleware

Build a middleware that:
- Identifies the client by IP address (`request.client.host`)
- Applies a default rate limit (e.g., 100 requests per minute) to all endpoints
- Returns 429 with a `Retry-After` header when the limit is exceeded
- Uses your consistent error response format from Chapter 5

### Step 3: Apply stricter limits to auth endpoints

For `/api/v1/auth/login` and `/api/v1/auth/register`, apply a much stricter limit: 5 requests per minute per IP. You can do this by:

- Checking the request path in the middleware and applying different limits
- Or creating a rate-limit dependency that you apply to specific endpoints

The dependency approach is more flexible:

```python
def rate_limit(max_requests: int, window_seconds: int):
    """Dependency factory for per-endpoint rate limiting."""
    async def dependency(request: Request):
        key = f"{request.client.host}:{request.url.path}"
        if not limiter.is_allowed(key, max_requests, window_seconds):
            raise TooManyRequestsException()
    return dependency
```

### Step 4: Create token blacklist

Create a token blacklist (can be a module-level set in `app/core/security.py` or a separate `app/core/token_blacklist.py`):

- `blacklist_token(jti: str, exp: datetime) -> None` — add a token's JTI to the blacklist
- `is_token_blacklisted(jti: str) -> bool` — check if a token is blacklisted
- Optional: periodically clean up expired entries (tokens past their `exp`)

### Step 5: Create the logout endpoint

Add `POST /api/v1/auth/logout` that:
1. Requires authentication (get the current user and the raw token)
2. Decodes the token to get the `jti`
3. Adds the `jti` to the blacklist
4. Returns a success message

### Step 6: Update get_current_user

Modify your `get_current_user` dependency to check the blacklist:
1. Decode the token
2. Extract the `jti`
3. Check if the `jti` is blacklisted — if yes, return 401 "Token has been revoked"
4. Continue with the normal user lookup

### Step 7: Test everything

**Rate limiting:**
1. Send 5 login requests in rapid succession — all should succeed
2. Send a 6th request within the same minute → 429 Too Many Requests
3. Wait for the window to pass, try again → succeeds
4. Verify the 429 response includes a `Retry-After` header

**Token revocation:**
1. Login, get a token
2. Use the token to access `/users/me` → 200
3. Call `/auth/logout` with the token
4. Use the same token to access `/users/me` → 401 "Token has been revoked"
5. Login again with the same credentials → get a new token that works

## Expected Outcome
- Auth endpoints have stricter rate limits than general endpoints
- The 6th login attempt within a minute returns 429 with `Retry-After` header
- `POST /auth/logout` blacklists the token
- Blacklisted tokens are rejected by `get_current_user` with a 401
- The rate limiter uses a sliding window (not fixed window)
- Old token still works until logout; new token works after login

## Hints
- For the `Retry-After` header, calculate how many seconds until the oldest request in the window expires: `window_seconds - (now - oldest_timestamp)`.
- The blacklist only needs to hold JTIs for tokens that haven't expired yet. Once a token's `exp` passes, remove its JTI.
- `collections.deque` is slightly more efficient than a list for the sliding window since you're removing from the left.
- In tests, you might need to set a very short rate limit window (e.g., 5 requests per 5 seconds) to avoid slow tests.
- A `TooManyRequestsException` class (or just use `HTTPException(status_code=429)`) should follow your error format.

## What I'll Look For In Review
- Sliding window algorithm is correctly implemented (not a fixed window)
- Auth endpoints have stricter limits than general endpoints (5/min vs 100/min)
- Token blacklist is checked in `get_current_user` before user lookup
- Logout endpoint properly blacklists the token's JTI
- 429 responses include a `Retry-After` header
