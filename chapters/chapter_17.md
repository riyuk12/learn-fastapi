# Chapter 17 — JWT Access & Refresh Tokens

## Concepts You'll Learn
- JWT structure: header, payload, signature
- Access tokens vs refresh tokens and why you need both
- Token expiration and configurable lifetimes
- Creating and decoding JWTs with python-jose

## Concept Deep Dive

### JWT Structure

A JSON Web Token (JWT) is a compact, self-contained way to represent a claim. When a user logs in, you create a JWT containing their user ID. On every subsequent request, the client sends this token, and your server verifies it to identify the user — no need to store sessions in a database.

A JWT has three parts, separated by dots: `header.payload.signature`

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U
```

**Header**: Declares the algorithm (`HS256`) and token type (`JWT`). Base64-encoded JSON.

**Payload**: The actual data (called "claims"). Contains the user ID (`sub`), expiration time (`exp`), issued-at time (`iat`), and any custom data you add. Base64-encoded JSON.

**Signature**: Created by hashing the header + payload with your secret key. This prevents tampering — if anyone modifies the payload, the signature won't match, and the token is rejected.

```python
# Conceptual: what's inside a JWT payload
{
    "sub": "550e8400-e29b-41d4-a716-446655440000",  # user ID
    "exp": 1705123456,                                # expiration timestamp
    "iat": 1705119856,                                # issued at
    "jti": "unique-token-id",                          # JWT ID (for revocation)
    "type": "access"                                   # token type
}
```

Important: JWTs are NOT encrypted. The payload is merely base64-encoded — anyone can decode it. Never put sensitive data (passwords, SSNs) in a JWT. The signature only prevents tampering, not reading.

### Access Tokens vs Refresh Tokens

A single token creates a dilemma: make it long-lived and a stolen token is dangerous for weeks. Make it short-lived and users have to log in every 30 minutes.

The solution is two tokens:

**Access Token**: Short-lived (15-30 minutes). Sent with every API request in the `Authorization` header. If stolen, the attacker has a narrow window. The server validates it on every request.

**Refresh Token**: Long-lived (7-30 days). Used ONLY to get new access tokens. Stored more securely (httpOnly cookie, or secure storage on mobile). If the access token expires, the client sends the refresh token to get a new access token without asking the user to log in again.

The flow:
1. User logs in → server returns both access and refresh tokens.
2. Client uses access token for API calls.
3. Access token expires → client sends refresh token to a refresh endpoint.
4. Server validates refresh token → returns a new access token.
5. Refresh token expires → user must log in again.

This separation limits damage from token theft. An access token stolen from a logged request (they're in every request) expires quickly. A refresh token is harder to steal (only sent to one endpoint).

### Token Expiration

`exp` (expiration) is a standard JWT claim. It's a Unix timestamp (seconds since epoch). When your server receives a token, it checks: is `exp` in the past? If yes, the token is rejected.

```python
from datetime import datetime, timedelta, timezone

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=30))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
```

Make expiration times configurable via your settings (from Chapter 6). Don't hardcode them — different environments might need different values.

### python-jose

`python-jose` is a library for creating and verifying JWTs. It supports multiple algorithms and handles the encoding/decoding/signature verification:

```python
from jose import jwt, JWTError

ALGORITHM = "HS256"
SECRET_KEY = "your-secret-key"

# Create a token
token = jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

# Decode and verify a token
try:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    user_id = payload.get("sub")
except JWTError:
    # Token is invalid (expired, tampered, wrong signature)
    raise
```

`HS256` (HMAC-SHA256) is a symmetric algorithm — the same key signs and verifies. This is appropriate when your API creates and verifies its own tokens. For microservice architectures where one service creates tokens and another verifies them, you'd use asymmetric algorithms (RS256) with public/private key pairs.

## Your Task

### Step 1: Install python-jose

Install `python-jose[cryptography]` and update `requirements.txt`.

### Step 2: Add token creation functions

In `app/core/security.py`, add:

- `create_access_token(data: dict, expires_delta: timedelta | None = None) -> str`:
  - Copies the input data
  - Adds `exp` (expiration), `iat` (issued at), `jti` (a UUID for token identification), and `type: "access"`
  - Encodes with your `SECRET_KEY` from settings and `HS256` algorithm

- `create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str`:
  - Same as access token but with `type: "refresh"` and a longer default expiration

- `decode_token(token: str) -> dict`:
  - Decodes and verifies the JWT
  - Returns the payload dict
  - Raises an appropriate error if the token is invalid or expired

### Step 3: Create token schemas

In `app/schemas/auth.py` (or `app/schemas/token.py`), create:

- `TokenResponse`: `access_token` (str), `refresh_token` (str), `token_type` (str, always "bearer")
- `LoginRequest`: `email` (EmailStr), `password` (str)

### Step 4: Create the login endpoint

In `app/api/v1/endpoints/auth.py`, add:

`POST /login` that:
1. Accepts `LoginRequest` (email + password)
2. Finds the user by email (404 or 401 if not found — use 401 to avoid revealing which emails are registered)
3. Verifies the password against the stored hash
4. If invalid, returns 401 "Invalid credentials" (same message whether email or password is wrong — don't reveal which)
5. Creates an access token and refresh token with `sub` set to the user's ID
6. Returns `TokenResponse`

### Step 5: Create the refresh endpoint

`POST /refresh` that:
1. Accepts a request body with the refresh token
2. Decodes the refresh token
3. Verifies it's a refresh token (check the `type` claim)
4. Fetches the user to ensure they still exist and are active
5. Creates a new access token
6. Returns `TokenResponse` (with the same refresh token, or a new one — your choice)

### Step 6: Use configurable expiration

Read `ACCESS_TOKEN_EXPIRE_MINUTES` and `REFRESH_TOKEN_EXPIRE_DAYS` from your settings. Don't hardcode the values in `security.py`.

### Step 7: Test the flow

1. Register a user (Chapter 16)
2. Login with correct credentials → get two tokens
3. Login with wrong password → 401
4. Login with nonexistent email → 401 (same message as wrong password)
5. Decode the access token (use jwt.io or Python) and verify it contains `sub`, `exp`, `iat`, `jti`, `type`
6. Use the refresh token to get a new access token

## Expected Outcome
- `POST /api/v1/auth/login` returns `{"access_token": "...", "refresh_token": "...", "token_type": "bearer"}`
- Access token expires in 30 minutes (configurable)
- Refresh token expires in 7 days (configurable)
- Decoding the access token reveals the user ID in the `sub` claim
- Wrong credentials return 401 without revealing whether email or password was wrong
- Refresh endpoint issues a new access token from a valid refresh token
- Expired tokens are rejected

## Hints
- `python-jose[cryptography]` needs the `cryptography` extra for proper algorithm support.
- `datetime.now(timezone.utc)` gives you a timezone-aware UTC datetime. Always use UTC for token expiration.
- For the login endpoint, consider using the same error message for "email not found" and "wrong password" — this prevents email enumeration attacks.
- The `jti` (JWT ID) claim is a unique identifier for each token. Use `str(uuid4())`. You'll use this in Chapter 21 for token revocation.
- When decoding, `jwt.decode()` automatically checks expiration. An expired token raises `ExpiredSignatureError`.

## What I'll Look For In Review
- Both `create_access_token` and `create_refresh_token` exist with proper claims
- Tokens include `sub`, `exp`, `iat`, `jti`, and `type` claims
- Login returns 401 for both wrong email and wrong password (no email enumeration)
- Refresh endpoint validates the token type (rejects access tokens used as refresh)
- Expiration times are read from settings, not hardcoded
