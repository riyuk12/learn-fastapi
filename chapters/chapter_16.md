# Chapter 16 — Registration Endpoint

## Concepts You'll Learn
- Designing a registration flow with proper validation
- Email and username uniqueness enforcement
- Response models that exclude sensitive fields
- Choosing the right HTTP status codes

## Concept Deep Dive

### Registration Flow

User registration seems simple — "take an email, username, and password, create a user" — but a production-quality implementation has several important steps:

1. **Validate input**: Is the email format valid? Is the username within length limits? Does the password meet strength requirements?
2. **Check uniqueness**: Is the email already registered? Is the username taken?
3. **Hash the password**: Never store plain text (covered in Chapter 15).
4. **Create the user**: Insert into the database with the hashed password.
5. **Return the response**: Send back user data WITHOUT the password hash.

Each step has its own failure mode, and each failure should produce a clear, specific error message. "Something went wrong" is not helpful. "Email 'user@example.com' is already registered" is.

### Email and Username Uniqueness

Uniqueness validation happens at two levels: application level and database level. Both are necessary.

**Application level**: Before inserting, query the database to check if the email/username exists. This gives you the opportunity to return a friendly error message with the correct HTTP status code (409 Conflict).

**Database level**: The UNIQUE constraint on the column catches race conditions. If two requests try to register the same email simultaneously, both application-level checks might pass (neither sees the other's uncommitted row), but the database constraint will reject the second insert with an `IntegrityError`.

```python
async def create_user(self, db: AsyncSession, data: UserCreate) -> User:
    # Application-level check (friendly error)
    existing = await self.user_repo.get_by_email(db, data.email)
    if existing:
        raise AlreadyExistsException("User", "email")

    existing = await self.user_repo.get_by_username(db, data.username)
    if existing:
        raise AlreadyExistsException("User", "username")

    # Create user...
```

For production systems, you'd also wrap the create in a try/except for `IntegrityError` to handle the race condition. For now, the application-level check is sufficient.

### Response Models Excluding Sensitive Fields

This is where the Create/Response schema split from Chapter 3 becomes critical. Your `UserCreate` schema has a `password` field (the plaintext input). Your `UserResponse` schema must NOT have `password` or `hashed_password`. If you accidentally return the hash, you've given attackers material for offline brute-force attacks.

```python
class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    is_active: bool
    role: UserRole
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

Notice `UserResponse` has no password field at all. When you use `response_model=UserResponse` on the endpoint, FastAPI filters the response through this model, stripping any fields not defined on it. Even if your internal User object has `hashed_password`, it won't appear in the API response.

### Password Strength Validation

Weak passwords are a security liability. At minimum, require:
- 8+ characters
- Not in a list of common passwords (optional but good)

You can add more rules (uppercase, numbers, special characters), but research suggests length is the most important factor. A 20-character passphrase like "correct horse battery staple" is stronger than "P@$$w0rd" despite the latter having "complexity."

Pydantic validators are perfect for this:

```python
@field_validator("password")
@classmethod
def validate_password_strength(cls, v):
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if v.lower() in COMMON_PASSWORDS:
        raise ValueError("This password is too common")
    return v
```

### Proper HTTP Status Codes

Status codes communicate what happened:
- **201 Created**: Registration successful. Use 201, not 200, because a new resource was created.
- **409 Conflict**: Email or username already exists. Use 409, not 400, because the request itself is valid — it conflicts with existing data.
- **422 Unprocessable Entity**: Validation failed (invalid email format, weak password). This is FastAPI/Pydantic's default for validation errors.

Don't return 200 for everything. Status codes exist for a reason — they help API clients handle responses programmatically without parsing the body.

## Your Task

### Step 1: Create user schemas

Create `app/schemas/user.py` with:

- `UserCreate`: email (use Pydantic's `EmailStr` for format validation), username (3-50 chars, alphanumeric + underscores only), password (8-128 chars with strength validation)
- `UserResponse`: id (UUID), email, username, is_active, role, created_at (NO password fields)

For `EmailStr`, you'll need to install `pydantic[email]` (or `email-validator`) and add it to requirements.

### Step 2: Add password validation

On `UserCreate`, add a field validator for `password` that:
- Checks minimum length (8 characters)
- Optionally checks against a small list of common passwords ("password", "12345678", etc.)
- Optionally checks for at least one digit and one letter

### Step 3: Add username validation

Add a field validator for `username` that:
- Ensures it's alphanumeric (letters, numbers, underscores only)
- Rejects usernames that are purely numeric (to avoid confusion with IDs)

### Step 4: Create the auth router

Create `app/api/v1/endpoints/auth.py` with an auth router. Define:

`POST /register` that:
1. Accepts `UserCreate` as request body
2. Calls `UserService.create_user()`
3. Returns `UserResponse` with status code 201

### Step 5: Wire the auth router

In `app/api/v1/router.py`, include the auth router with prefix `/auth` and tag `"auth"`.

### Step 6: Test registration

Test these scenarios:
- Valid registration → 201 with user data (no password in response)
- Duplicate email → 409
- Duplicate username → 409
- Invalid email format → 422
- Short password → 422
- Username with special characters → 422

## Expected Outcome
- `POST /api/v1/auth/register` creates a user and returns 201
- Response does NOT include `password` or `hashed_password`
- Duplicate email returns 409 with a clear error message
- Duplicate username returns 409
- Invalid email format returns 422
- Weak password (less than 8 chars) returns 422
- Swagger UI shows the registration endpoint under the "auth" tag

## Hints
- Install `email-validator` for Pydantic's `EmailStr`: `pip install email-validator` (or `pydantic[email]`).
- For the username regex, Pydantic's `Field(pattern=r"^[a-zA-Z0-9_]+$")` works well.
- Make sure your `UserService.create_user()` normalizes the email to lowercase before checking and storing. "User@Example.com" and "user@example.com" should be considered the same.
- Remember to add the auth router to your v1 router in `app/api/v1/router.py`.

## What I'll Look For In Review
- `UserCreate` has proper validation (email format, password strength, username format)
- `UserResponse` explicitly excludes all password fields
- The endpoint returns 201 (not 200) on successful registration
- Uniqueness violations return 409 with descriptive messages
- Email is normalized to lowercase before storage and comparison
