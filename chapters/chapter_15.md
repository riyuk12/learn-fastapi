# Chapter 15 — User Model & Password Hashing

## Concepts You'll Learn
- User model design for an authentication system
- Password hashing with bcrypt and why it matters
- Why SHA/MD5 are wrong for passwords
- Using passlib for hashing and verification

## Concept Deep Dive

### User Model Design

The User model is the cornerstone of your authentication system. It needs to store enough information to identify, authenticate, and authorize users, while being designed for security from the start.

A well-designed user model typically includes:
- **id**: UUID primary key (never expose auto-incrementing IDs — they reveal user count)
- **email**: unique, indexed — the primary login identifier
- **username**: unique, indexed — for display purposes and public-facing URLs
- **hashed_password**: the bcrypt hash (NEVER the plaintext password)
- **is_active**: boolean flag to disable accounts without deleting them
- **role**: enum for authorization levels (user, moderator, admin)
- **created_at / updated_at**: timestamps for auditing

The `is_active` flag is critical. When a user violates terms of service, you don't delete their account (that destroys audit trails). You deactivate it. This also lets you implement email verification: new accounts start inactive until the user confirms their email.

The `role` enum determines what a user can do. You'll build the full RBAC (Role-Based Access Control) system in Chapter 19, but the model needs the field now:

```python
class UserRole(str, enum.Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"
```

### Password Hashing: Why It Matters

When a user creates an account with password "correcthorsebatterystaple", you must NEVER store that password in the database. Not in plain text, not encrypted, not encoded. You store a hash — a one-way mathematical transformation that produces a fixed-length string from any input.

Why? Because databases get breached. It's not a question of if, but when. If your database is stolen and contains plaintext passwords, every user's password is instantly compromised. Since most people reuse passwords, that breach cascades to their email, their bank, their everything.

With proper hashing, a breach exposes only hashes. An attacker would need to reverse the hash to get the password, which — with the right algorithm — is computationally infeasible.

### Why NOT SHA/MD5

You might think: "I know about hashing! I'll use SHA-256!" Don't. SHA-256 and MD5 are cryptographic hash functions, but they were designed to be FAST. A modern GPU can compute billions of SHA-256 hashes per second. An attacker with a dictionary of common passwords can hash every one and compare against your database in seconds.

bcrypt, scrypt, and Argon2 are specifically designed for password hashing. They are intentionally SLOW — they take ~100ms per hash instead of nanoseconds. They include a "work factor" you can increase as hardware gets faster. And they automatically handle salting (adding random data to each hash so two users with the same password get different hashes).

```
MD5("password")     → "5f4dcc3b5aa765d61d8327deb882cf99"  (same every time)
bcrypt("password")  → "$2b$12$LJ3m4ys3Lg2Rpx7TBi2HGuD0RK6c06eMXBJjY5dMFVn.gXOYKN5xK"
bcrypt("password")  → "$2b$12$DIFFERENT_SALT_DIFFERENT_HASH_EVERY_TIME"
```

The `$2b$12$` prefix tells you it's bcrypt with a cost factor of 12 (2^12 = 4096 rounds of hashing). This makes brute-force attacks prohibitively expensive.

### passlib for Hashing and Verification

`passlib` is a Python library that provides a clean API for password hashing. It supports multiple algorithms and handles the complexity of salting, cost factors, and hash format parsing.

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
```

`CryptContext` manages the hashing scheme. `schemes=["bcrypt"]` says "use bcrypt." `deprecated="auto"` means if you later add a stronger scheme, passlib will automatically upgrade old hashes when users log in.

The `verify()` function extracts the salt and cost factor from the stored hash, hashes the provided password with the same parameters, and compares. It uses constant-time comparison to prevent timing attacks (where an attacker measures how long comparison takes to guess characters).

Two functions are all you need: `hash_password()` for registration, `verify_password()` for login.

## Your Task

### Step 1: Install dependencies

Install `passlib[bcrypt]` (which installs passlib and the bcrypt backend). Update `requirements.txt`.

### Step 2: Create the security module

Create `app/core/security.py` with:

- A `CryptContext` configured for bcrypt
- `hash_password(password: str) -> str` function
- `verify_password(plain_password: str, hashed_password: str) -> bool` function

### Step 3: Create the User model

Create `app/models/user.py` with a `User` model:

- `id`: UUID primary key
- `email`: String(255), unique, indexed, not nullable
- `username`: String(50), unique, indexed, not nullable
- `hashed_password`: String(255), not nullable
- `is_active`: Boolean, default `True`
- `role`: Enum (user, moderator, admin), default "user"
- `created_at`: DateTime with timezone, server default
- `updated_at`: DateTime with timezone, server default + onupdate

Define the `UserRole` enum either in the model file or in `app/schemas/user.py`.

### Step 4: Create user repository

Create `app/repositories/user.py` with `UserRepository(BaseRepository[User])`. Add methods:

- `get_by_email(db, email)` — find user by email
- `get_by_username(db, username)` — find user by username

### Step 5: Create user service

Create `app/services/user.py` with a `UserService` class that has a `create_user(db, data)` method. This method should:

1. Check that email is not already taken (raise `AlreadyExistsException` if so)
2. Check that username is not already taken
3. Hash the password using `hash_password()`
4. Create the user via the repository (passing the hash, NOT the plain password)
5. Return the created user

### Step 6: Import the model and generate migration

Update `app/models/__init__.py` to import `User`. Generate a new Alembic migration and apply it:

```bash
alembic revision --autogenerate -m "create user table"
alembic upgrade head
```

### Step 7: Verify

Write a quick test (can be in a temporary script) that:
1. Hashes a password
2. Verifies the correct password returns `True`
3. Verifies an incorrect password returns `False`
4. Hashes the same password twice and confirms the hashes are DIFFERENT (proving salting works)

## Expected Outcome
- `User` model exists in the database with all fields
- `hash_password()` produces a bcrypt hash (starts with `$2b$`)
- `verify_password()` correctly validates passwords
- Same password hashed twice produces different hashes (salting)
- `UserService.create_user()` stores the hash, never the plaintext
- Migration creates the users table with unique constraints on email and username

## Hints
- `passlib[bcrypt]` requires the `bcrypt` package as a backend. If you get an error about missing bcrypt, install it explicitly: `pip install bcrypt`.
- The `UserRole` enum should inherit from `str, enum.Enum` just like `MangaStatus`.
- In the User model, the column is `hashed_password` — never call it `password`. The naming reinforces that you're storing a hash.
- Don't forget to add unique constraints and indexes on `email` and `username`. These are your primary lookup fields.

## What I'll Look For In Review
- Passwords are hashed with bcrypt (via passlib), never stored in plaintext
- `hash_password` and `verify_password` are in a dedicated `security.py` module
- User model has `hashed_password` field (NOT `password`)
- Email and username have unique constraints and indexes
- The user service hashes the password before calling the repository
