# Chapter 19 — Role-Based Access Control

## Concepts You'll Learn
- RBAC (Role-Based Access Control) design principles
- Permission checking via dependency factories
- Role hierarchy and the principle of least privilege
- Building reusable, composable authorization dependencies

## Concept Deep Dive

### RBAC Design

Role-Based Access Control assigns permissions to roles, then assigns roles to users. Instead of checking "can user #42 edit manga?" you check "does user #42 have a role that includes the edit-manga permission?"

For MangaShelf, we have three roles in ascending order of privilege:

```
user < moderator < admin
```

- **user**: Can browse manga, manage their own reading list, write reviews
- **moderator**: Everything a user can do, plus create/edit manga, manage content
- **admin**: Everything a moderator can do, plus manage users, delete content, change roles

This is a hierarchical model: each role inherits all permissions from the roles below it. An admin can do everything a moderator can do, which can do everything a user can do. This simplification means you only need to check "is the user's role at least X?" rather than checking individual permissions.

### Dependency Factories for Permission Checking

A dependency factory is a function that returns a dependency function. This pattern lets you create configurable, reusable authorization checks:

```python
from app.models.user import UserRole

def require_role(minimum_role: UserRole):
    """Factory that returns a dependency requiring at least the specified role."""

    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        role_hierarchy = {
            UserRole.USER: 0,
            UserRole.MODERATOR: 1,
            UserRole.ADMIN: 2,
        }

        user_level = role_hierarchy.get(current_user.role, 0)
        required_level = role_hierarchy.get(minimum_role, 0)

        if user_level < required_level:
            raise ForbiddenException("Insufficient permissions")

        return current_user

    return role_checker
```

Now you use it like this:

```python
# Only moderators and admins can create manga
@router.post("/manga")
async def create_manga(
    manga: MangaCreate,
    current_user: User = Depends(require_role(UserRole.MODERATOR)),
    db: AsyncSession = Depends(get_db),
):
    ...

# Only admins can delete manga
@router.delete("/manga/{manga_id}")
async def delete_manga(
    manga_id: uuid.UUID,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    ...
```

This is both clean and safe. The authorization check is declarative — you can see the required role right in the function signature. And because it's a dependency, it runs before your endpoint code, so unauthorized users never reach the business logic.

### Role Hierarchy

The hierarchy `user < moderator < admin` is implemented as a numeric comparison. Assign each role a number (user=0, moderator=1, admin=2), and "require moderator" means "require level >= 1."

This approach has a subtle but important benefit: when you add the `require_role(UserRole.MODERATOR)` dependency, admins automatically pass the check too. You don't need separate logic for "moderator or admin" — the hierarchy handles it.

When would you need something more complex? When permissions don't follow a simple hierarchy. For example, if "moderators can edit content but not manage users" and "support staff can manage users but not edit content," you'd need a full permission system (roles have sets of permissions, and you check for specific permissions). For MangaShelf, the hierarchy is sufficient.

### Principle of Least Privilege

The principle of least privilege says: give every user the minimum access they need to do their job, and nothing more. Apply this to your API:

- Don't make all endpoints require admin. If moderators need to create manga, let them.
- Don't make endpoints public if they should be protected. Even reading a list of users should require authentication.
- Default to restricted. If you're unsure whether an endpoint should be public, make it authenticated. You can always relax it later.

This also means new accounts should start as `user` (the lowest role). Only an admin can promote someone to moderator or admin. And there should be no self-service way to escalate your own role.

## Your Task

### Step 1: Create the permissions module

Create `app/core/permissions.py` with:

- A `require_role(minimum_role: UserRole)` dependency factory as described above
- A `ForbiddenException` in your exceptions module (if you haven't already) that returns 403 with code `"FORBIDDEN"`

### Step 2: Protect manga write endpoints

Update your manga endpoints:
- `POST /api/v1/manga` — requires moderator or above
- `PATCH /api/v1/manga/{manga_id}` (if you have it) — requires moderator or above
- `DELETE /api/v1/manga/{manga_id}` — requires admin only

Reading endpoints (GET list, GET by ID) should remain public (no auth required).

### Step 3: Create user management endpoints

In `app/api/v1/endpoints/users.py`, add:

- `GET /api/v1/users` — admin only. Returns a paginated list of all users. Use your paginated response format from Chapter 14.
- `PATCH /api/v1/users/{user_id}/role` — admin only. Accepts a body with the new role. Updates the user's role.

For the role update, create a small schema:

```python
class RoleUpdate(BaseModel):
    role: UserRole
```

The service should validate:
- The target user exists (404 if not)
- An admin can't demote themselves (prevent losing the last admin)
- The role is valid

### Step 4: Prevent self-role-escalation

Make sure the role update endpoint doesn't allow:
- A moderator promoting themselves to admin
- A user promoting themselves to anything

Only admins can change roles, and the `require_role(UserRole.ADMIN)` dependency ensures that. But also prevent an admin from demoting themselves if they're the last admin.

### Step 5: Add convenience dependencies

In `app/api/deps.py` (or `app/core/permissions.py`), create convenience shortcuts:

```python
require_moderator = require_role(UserRole.MODERATOR)
require_admin = require_role(UserRole.ADMIN)
```

These make endpoint signatures even cleaner:
```python
current_user: User = Depends(require_admin)
```

### Step 6: Test the RBAC system

1. Create three users: one regular user, one moderator, one admin (use the seed script or manually promote via a temporary endpoint)
2. As **user**: try to create manga → 403
3. As **moderator**: create manga → success
4. As **moderator**: try to delete manga → 403
5. As **admin**: delete manga → success
6. As **admin**: promote a user to moderator → success
7. As **moderator**: try to promote someone → 403
8. As **admin**: try to view user list → success
9. As **user**: try to view user list → 403

## Expected Outcome
- `require_role()` is a reusable dependency factory that works for any role level
- Role hierarchy is properly enforced: admin > moderator > user
- Manga create/update requires moderator+; manga delete requires admin
- User management (list users, change roles) requires admin
- Regular users get 403 when accessing restricted endpoints (not 401 — they're authenticated, just not authorized)
- The permission system is reusable — adding new protected endpoints requires only one `Depends()` call

## Hints
- Define the role hierarchy as a dict mapping roles to integers. This makes comparison easy and the hierarchy configurable.
- For the initial admin user, you have options: create them in your seed script, or add a one-time CLI command, or check if zero admins exist during startup and create one.
- When testing, you'll need to log in as different users to get different tokens. Keep track of which token belongs to which role.
- Remember: 401 means "not authenticated" (no/invalid token). 403 means "authenticated but not authorized" (valid token, insufficient role).

## What I'll Look For In Review
- `require_role` is a dependency factory, not a hardcoded check in each endpoint
- Role hierarchy is explicit and correct (user < moderator < admin)
- Admin-only endpoints are properly protected
- Self-escalation is prevented
- The 403 response uses the consistent error format from Chapter 5
