# Chapter 18 — Protected Routes & Current User Dependency

## Concepts You'll Learn
- OAuth2PasswordBearer scheme in FastAPI
- Building a `get_current_user` dependency that extracts user identity from JWT
- The difference between 401 Unauthorized and 403 Forbidden
- Protecting routes with dependency injection

## Concept Deep Dive

### OAuth2PasswordBearer

FastAPI has built-in support for OAuth2 flows. `OAuth2PasswordBearer` is a special class that tells FastAPI: "this API uses Bearer token authentication, and the token endpoint is at this URL."

```python
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
```

What does this do? Two things:

1. **Swagger Integration**: The `/docs` page shows a lock icon on protected endpoints. Clicking it opens a login form that calls your `tokenUrl` to get a token, then automatically includes it in subsequent requests.

2. **Token Extraction**: When used as a dependency, it extracts the token from the `Authorization: Bearer <token>` header and returns it as a string. If no token is present, it automatically returns 401.

```python
@router.get("/protected")
async def protected_route(token: str = Depends(oauth2_scheme)):
    # token is the raw JWT string from the Authorization header
    ...
```

`oauth2_scheme` itself doesn't validate the token — it just extracts it. The actual validation (decoding, checking expiration, fetching the user) is done by the `get_current_user` dependency.

### Building get_current_user

The `get_current_user` dependency is the heart of your authentication system. It takes the raw token, decodes it, finds the user, and returns a `User` object. Every protected endpoint uses it.

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # 1. Decode the JWT
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Extract the user ID
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # 3. Verify it's an access token, not a refresh token
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # 4. Fetch the user from the database
    user = await user_repo.get(db, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
```

Notice that this dependency itself depends on `oauth2_scheme` and `get_db`. FastAPI's dependency injection handles the chain: when an endpoint depends on `get_current_user`, FastAPI first resolves `oauth2_scheme` (extracts the token) and `get_db` (creates a session), then passes both to `get_current_user`.

You can build on this with additional dependencies:

```python
async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    return current_user
```

This creates a dependency chain: `get_current_active_user` -> `get_current_user` -> `oauth2_scheme` + `get_db`. An inactive user gets past authentication (their token is valid) but is blocked at authorization (they're not allowed to do anything).

### 401 Unauthorized vs 403 Forbidden

These are often confused, but the distinction matters:

**401 Unauthorized**: "I don't know who you are." No token was provided, or the token is invalid/expired. The response should include a `WWW-Authenticate` header telling the client how to authenticate.

**403 Forbidden**: "I know who you are, but you're not allowed to do this." The token is valid, the user is identified, but they lack permission. An inactive user, or a regular user trying to access an admin endpoint.

In practice:
- No token → 401
- Expired token → 401
- Invalid token → 401
- Valid token, inactive user → 403
- Valid token, wrong role → 403

```python
raise HTTPException(
    status_code=401,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)
```

The `WWW-Authenticate: Bearer` header is part of the HTTP spec for bearer token authentication. It tells the client "you need a Bearer token to access this resource."

### Protecting Routes

With these dependencies, protecting a route is just adding a parameter:

```python
# Public — anyone can access
@router.get("/manga")
async def list_manga(...):
    ...

# Protected — requires valid token
@router.post("/manga")
async def create_manga(
    manga: MangaCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    ...

# The current_user is now available for business logic
# e.g., manga.created_by = current_user.id
```

The elegance of this approach is that authentication is declarative. You don't write `if not authenticated: return 401` in every endpoint. You declare a dependency, and FastAPI handles the rest.

## Your Task

### Step 1: Create the OAuth2 scheme

In `app/core/security.py` (or a new `app/api/deps.py`), create an `OAuth2PasswordBearer` instance with the `tokenUrl` pointing to your login endpoint.

### Step 2: Create get_current_user dependency

Create `app/api/deps.py` (if it doesn't exist) with a `get_current_user` async function that:

1. Depends on `oauth2_scheme` for the token
2. Depends on `get_db` for the database session
3. Decodes the token
4. Validates it's an access token (not refresh)
5. Extracts the user ID from the `sub` claim
6. Fetches the user from the database
7. Returns the User object or raises 401

Use your custom exception classes where appropriate.

### Step 3: Create get_current_active_user dependency

In the same file, create `get_current_active_user` that depends on `get_current_user` and additionally checks `is_active`. Returns 403 for inactive users.

### Step 4: Protect the POST manga endpoint

Update `POST /api/v1/manga` to require authentication. Add `current_user: User = Depends(get_current_active_user)` to the function signature.

### Step 5: Create the /users/me endpoint

Create `app/api/v1/endpoints/users.py` with a users router. Add:

`GET /me` that:
1. Requires authentication (depends on `get_current_active_user`)
2. Returns the current user's profile as `UserResponse`

Wire this router into the v1 router with prefix `/users` and tag `"users"`.

### Step 6: Test authentication flow

1. Try `POST /api/v1/manga` without a token → 401
2. Login, get a token
3. Try `POST /api/v1/manga` with the token in `Authorization: Bearer <token>` → success
4. Try with an expired token (set ACCESS_TOKEN_EXPIRE_MINUTES=0 temporarily) → 401
5. Try with a garbled token → 401
6. Try with a refresh token instead of access token → 401
7. `GET /api/v1/users/me` with valid token → user profile
8. Check Swagger UI → protected endpoints show a lock icon

## Expected Outcome
- Protected endpoints require a valid Bearer token
- Invalid/expired/missing tokens return 401 with `WWW-Authenticate: Bearer` header
- Inactive users get 403 (not 401)
- `GET /api/v1/users/me` returns the authenticated user's profile
- Swagger UI shows lock icons on protected endpoints and has a working "Authorize" button
- Public endpoints (GET manga list, health check) still work without authentication

## Hints
- `OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")` — the tokenUrl must match your actual login endpoint path for Swagger UI to work.
- When raising 401, always include `headers={"WWW-Authenticate": "Bearer"}`.
- If Swagger's "Authorize" button doesn't work, check that your login endpoint accepts form data (`OAuth2PasswordRequestForm`) in addition to or instead of JSON. FastAPI's Swagger uses form data for the OAuth2 flow.
- You can make authentication optional for some endpoints by using `Depends(oauth2_scheme)` with a default of `None` and handling the case where no token is provided.

## What I'll Look For In Review
- `get_current_user` properly decodes the JWT and fetches the user from the database
- `get_current_active_user` adds the `is_active` check as a separate dependency
- 401 responses include the `WWW-Authenticate: Bearer` header
- Token type is validated (access tokens only for API calls)
- Protected and public endpoints are clearly distinguished
