# Chapter 20 — OAuth2 with Google

## Concepts You'll Learn
- The OAuth2 Authorization Code flow (the "OAuth dance")
- How third-party identity providers work
- Account linking: connecting OAuth identities to existing users
- Building the Google OAuth integration with httpx

## Concept Deep Dive

### The OAuth2 Authorization Code Flow

OAuth2 is a protocol that lets users log into your app using their existing accounts (Google, GitHub, etc.) without sharing their passwords with you. The flow has several steps, often called the "OAuth dance":

**Step 1: Your app redirects the user to Google**
```
https://accounts.google.com/o/oauth2/auth?
    client_id=YOUR_CLIENT_ID
    &redirect_uri=http://localhost:8000/api/v1/auth/google/callback
    &response_type=code
    &scope=openid email profile
```

The user sees Google's login page. They enter their Google credentials (on Google's site, never on yours). Google asks "MangaShelf wants to access your email and profile — allow?"

**Step 2: Google redirects back to your app with a code**
```
http://localhost:8000/api/v1/auth/google/callback?code=AUTHORIZATION_CODE
```

This "authorization code" is a one-time-use, short-lived token. It proves the user approved your app, but it's not an access token yet.

**Step 3: Your server exchanges the code for tokens**

Your server makes a backend (server-to-server) POST request to Google:
```
POST https://oauth2.googleapis.com/token
    code=AUTHORIZATION_CODE
    &client_id=YOUR_CLIENT_ID
    &client_secret=YOUR_CLIENT_SECRET
    &redirect_uri=http://localhost:8000/api/v1/auth/google/callback
    &grant_type=authorization_code
```

Google returns an access token and an ID token (a JWT containing the user's email, name, and Google user ID).

**Step 4: Your server uses the tokens to get user info**

Decode the ID token or call Google's userinfo endpoint to get the user's email, name, and Google user ID. Then find or create a user in your database and issue your own JWTs.

Why is the code exchange done server-to-server? Because the `client_secret` must never be exposed to the browser. The authorization code is safe to pass through the browser (it's useless without the secret), but the exchange for tokens happens entirely on your backend.

### Third-Party Identity Providers

Google is just one provider. The same pattern works with GitHub, Facebook, Apple, etc. — the URLs change but the flow is identical. This is why OAuth2 is a protocol, not a product.

For MangaShelf, we'll implement Google OAuth. The skills you learn apply to any provider:

1. Register your app with the provider to get a `client_id` and `client_secret`
2. Build a redirect endpoint that sends users to the provider
3. Build a callback endpoint that handles the return
4. Exchange the code for tokens
5. Extract user identity and create/link accounts

### Account Linking

What happens when a user who already registered with email+password tries to log in with Google (using the same email)? You have two options:

1. **Reject**: "This email is already registered. Please log in with your password." Safe but inconvenient.
2. **Link**: Automatically connect the Google identity to the existing account. The user can now log in with either method.

Option 2 is better UX but requires care. You should only auto-link when the email from Google is verified (Google includes an `email_verified` claim in the ID token). You store the link in an `OAuthAccount` model:

```python
class OAuthAccount(Base):
    __tablename__ = "oauth_account"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)      # "google"
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Google's user ID
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Unique constraint: one Google account can only link to one user
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )
```

### Building with httpx

`httpx` is an async HTTP client for Python — perfect for making server-to-server requests in an async FastAPI app. You'll use it to exchange the authorization code for tokens and to call Google's userinfo endpoint.

```python
import httpx

async def exchange_code_for_tokens(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()
```

## Your Task

### Step 1: Set up Google OAuth credentials

Go to [Google Cloud Console](https://console.cloud.google.com/):
1. Create a project (or use an existing one)
2. Go to "APIs & Services" → "Credentials"
3. Create an "OAuth 2.0 Client ID" (Web application type)
4. Set the authorized redirect URI to `http://localhost:8000/api/v1/auth/google/callback`
5. Note the `client_id` and `client_secret`

If you can't set up Google OAuth credentials right now, you can still build all the code and test with mock values. The architecture is what matters.

### Step 2: Add settings

In `app/core/config.py`, add:
- `GOOGLE_CLIENT_ID`: str, default empty string
- `GOOGLE_CLIENT_SECRET`: str, default empty string
- `GOOGLE_REDIRECT_URI`: str, default `"http://localhost:8000/api/v1/auth/google/callback"`

Update `.env` and `.env.example`.

### Step 3: Install httpx

Install `httpx` and update `requirements.txt`.

### Step 4: Create the OAuthAccount model

Create `app/models/oauth_account.py` with the `OAuthAccount` model described above. Add a relationship to the User model (a user can have multiple OAuth accounts, one per provider). Generate and run the migration.

### Step 5: Create the OAuth module

Create `app/core/oauth.py` with functions:

- `get_google_auth_url() -> str`: Build and return the Google authorization URL with the correct parameters (client_id, redirect_uri, response_type, scope).

- `exchange_google_code(code: str) -> dict`: Exchange the authorization code for tokens using httpx. Return the token response.

- `get_google_user_info(access_token: str) -> dict`: Call Google's userinfo endpoint (`https://www.googleapis.com/oauth2/v2/userinfo`) with the access token. Return the user info (email, name, Google user ID).

### Step 6: Create OAuth endpoints

In `app/api/v1/endpoints/auth.py`, add:

`GET /google` — Redirects the user to Google's authorization page. Use FastAPI's `RedirectResponse`.

`GET /google/callback` — The callback Google redirects to. This endpoint:
1. Receives the `code` query parameter
2. Exchanges it for tokens
3. Gets the user's Google profile (email, name, Google user ID)
4. Checks if an OAuthAccount with this provider+provider_user_id exists:
   - If yes → fetch the linked user → issue your JWTs
   - If no → check if a user with this email exists:
     - If yes → create an OAuthAccount linking to the existing user → issue JWTs
     - If no → create a new user (with a generated username, no password) + OAuthAccount → issue JWTs
5. Returns your JWT tokens (or redirects to a frontend URL with tokens as query params)

### Step 7: Create an OAuth service

The callback logic is complex — put it in `app/services/oauth.py` (or extend your user service). The service should handle the find-or-create-and-link logic.

### Step 8: Generate migration and test

Generate and apply the migration for the OAuthAccount table. Test the flow:

1. Visit `http://localhost:8000/api/v1/auth/google` — should redirect to Google
2. After Google auth, the callback should return JWTs
3. Calling the flow again with the same Google account should log in the existing user (not create a duplicate)
4. If you registered an email/password account first, the Google login with the same email should link to it

## Expected Outcome
- `GET /api/v1/auth/google` redirects to Google's OAuth consent screen
- The callback exchanges the code for user info and issues your app's JWTs
- New users are created for first-time Google logins
- Existing users with the same email get their accounts linked
- The OAuthAccount model tracks which provider accounts are linked to which users
- Subsequent Google logins for the same user reuse the existing account

## Hints
- The `scope` for Google should be `"openid email profile"` to get the user's email and name.
- For users created via OAuth, set `hashed_password` to an empty string or a random hash. They can set a password later. Mark the account appropriately.
- Google's ID token is a JWT that you can decode to get user info without a separate API call. Use `jwt.decode()` but set `options={"verify_signature": False}` since you already trust Google's token endpoint.
- If you can't test with real Google credentials, build the endpoints anyway and test with mocked responses. The code structure is the learning goal.
- Use `from fastapi.responses import RedirectResponse` for the initial redirect.

## What I'll Look For In Review
- The OAuth flow follows the Authorization Code pattern (redirect → code → token exchange → user info)
- Token exchange happens server-to-server with httpx (client_secret never exposed to browser)
- Account linking logic handles all three cases (existing OAuth, existing email, new user)
- OAuthAccount model has a unique constraint on (provider, provider_user_id)
- The callback issues YOUR app's JWTs, not Google's tokens
