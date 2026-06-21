# Chapter 54 — Auth Pages & Token Management

## Concepts You'll Learn
- Client-side auth flow with JWT tokens
- Token storage strategies (httpOnly cookies vs localStorage — trade-offs)
- React context for global auth state
- Next.js middleware for route protection

## Concept Deep Dive

### Client-Side Auth Flow

Your backend from Chapters 11-12 issues JWT access tokens and refresh tokens. The frontend auth flow works like this: the user submits credentials, the backend validates them and returns tokens, the frontend stores the tokens and includes the access token in every subsequent API request.

The flow has three states: **unauthenticated** (no tokens), **authenticated** (valid access token), and **refreshing** (access token expired, attempting to use refresh token). Your auth system needs to handle all three states and transitions between them transparently.

```
[Login Form] --> POST /auth/login --> {access_token, refresh_token}
                                           |
                                    Store tokens
                                           |
                              [Authenticated state]
                                           |
                              access_token expires
                                           |
                              POST /auth/refresh --> {new access_token}
                                           |
                              refresh_token expires
                                           |
                              [Redirect to login]
```

The tricky part is the refresh flow. When an API request returns a 401 (access token expired), the client should automatically attempt a token refresh. If the refresh succeeds, it retries the original request. If the refresh fails (refresh token also expired), it logs the user out. This should happen invisibly — the user should not notice unless they are truly logged out.

### Token Storage Strategies

Where to store tokens is one of the most debated topics in frontend security. There are two main options, each with real trade-offs.

**localStorage** is simple. You write `localStorage.setItem("access_token", token)` and read it back. It persists across tabs and browser restarts. The downside is that it is accessible to any JavaScript running on your page, which means a cross-site scripting (XSS) attack can steal the token. If your app ever has an XSS vulnerability, the attacker gets full API access.

**httpOnly cookies** are set by the server and automatically included in requests. JavaScript cannot access them, which makes them immune to XSS token theft. The downside is that cookies are sent automatically to the origin domain, which makes them vulnerable to cross-site request forgery (CSRF). You mitigate this with CSRF tokens or the `SameSite` cookie attribute.

For MangaShelf, use **localStorage** for simplicity during development. This is a learning project, and localStorage is easier to debug (you can see the tokens in DevTools). In a real production app, httpOnly cookies with CSRF protection are the more secure choice. Your auth hook should abstract storage behind a function so switching later requires changing only one module.

### React Context for Auth State

Auth state needs to be globally accessible — any component might need to know if the user is logged in, display the username, or call a protected API. React Context provides a way to share state across the component tree without passing props through every level.

```typescript
interface AuthContextType {
  user: UserResponse | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  register: (data: RegisterData) => Promise<void>;
}
```

The `AuthProvider` wraps your app (in a layout) and provides the context. A `useAuth` hook gives any component access to the auth state and actions. When the app loads, the provider checks for an existing token, validates it (or refreshes it), and sets the user state.

This is a **Client Component** pattern — it uses React hooks and browser APIs (localStorage). Mark it with `"use client"`. Server Components that need auth information will get it from different mechanisms (cookies, headers).

### Next.js Middleware for Route Protection

Next.js middleware runs *before* a request reaches a page. It is perfect for route protection: if a user tries to access `/library` without being logged in, the middleware redirects them to `/login`.

```typescript
// middleware.ts (at project root or src/)
import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const token = request.cookies.get("access_token")?.value;
  const isAuthPage = request.nextUrl.pathname.startsWith("/login") ||
                     request.nextUrl.pathname.startsWith("/register");

  if (!token && !isAuthPage) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (token && isAuthPage) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/library/:path*", "/profile/:path*", "/collections/:path*"],
};
```

The `config.matcher` array specifies which paths the middleware applies to. Public routes like `/manga` do not need protection. The middleware runs on the server (Edge runtime), so it only has access to cookies, not localStorage. This is one reason to consider cookies for token storage in a real app. For your localStorage approach, the middleware provides server-side protection while the client-side AuthProvider handles client-side redirects.

## Your Task

### Step 1: Create Auth Utility Module

Create `frontend/src/lib/auth.ts` with:
- `getStoredTokens()` — reads access_token and refresh_token from localStorage
- `setStoredTokens(access, refresh)` — saves both tokens
- `clearStoredTokens()` — removes both tokens
- `isTokenExpired(token)` — decodes the JWT (just the payload, base64) and checks the `exp` claim against current time

Note: You are not verifying the JWT signature on the client (that is the server's job). You are only reading the expiration time to know when to refresh proactively.

### Step 2: Create AuthProvider and useAuth Hook

Create `frontend/src/components/providers/AuthProvider.tsx`:
- A React context providing: `user`, `isLoading`, `isAuthenticated`, `login()`, `logout()`, `register()`
- On mount, check for stored tokens. If found, fetch the current user profile (`GET /users/me`) to validate the token. If it fails with 401, try refreshing.
- `login()` calls the backend login endpoint, stores tokens, fetches and sets user
- `logout()` clears tokens and user state
- `register()` calls the backend register endpoint, then auto-logs in

### Step 3: Wire AuthProvider into the App Layout

In `frontend/src/app/layout.tsx`, wrap the page content with `<AuthProvider>`. This makes auth state available everywhere.

### Step 4: Build Login Page

Create `frontend/src/app/(auth)/login/page.tsx` with:
- A form with email and password fields
- Submit handler calls `useAuth().login()`
- Shows validation errors from the backend
- Redirects to home page on success
- Link to registration page

Style it with Tailwind CSS. It does not need to be beautiful, but it should be functional and readable.

### Step 5: Build Registration Page

Create `frontend/src/app/(auth)/register/page.tsx` with:
- A form with username, email, and password fields
- Submit handler calls `useAuth().register()`
- Shows validation errors
- Redirects to home page on success
- Link to login page

### Step 6: Implement Token Auto-Refresh

Enhance your API client from Chapter 53 to handle token expiration:
- Before each request, check if the access token is close to expiring (within 30 seconds)
- If so, proactively refresh it before making the request
- If a request returns 401, try refreshing and retrying once
- If refresh fails, log the user out

This logic belongs in the API client's request method, not in individual components.

### Step 7: Create Next.js Middleware

Create `frontend/src/middleware.ts`:
- Protect routes that require auth: `/library`, `/profile`, `/collections`
- Redirect unauthenticated users to `/login`
- Redirect authenticated users away from `/login` and `/register` to home
- Use a simple cookie check (you can set a non-httpOnly cookie alongside localStorage for the middleware to read, or check for the token in a cookie)

### Step 8: Add a Navigation Header

Create `frontend/src/components/Header.tsx`:
- Shows app name and navigation links
- When logged out: show Login and Register links
- When logged in: show username, Library link, and Logout button
- Use the `useAuth` hook for state

Add this header to your root layout so it appears on every page.

## Expected Outcome
- Login page submits credentials and receives tokens
- Registration page creates an account and auto-logs in
- Tokens are stored in localStorage and included in API requests
- Token auto-refresh works transparently when access token expires
- Protected routes redirect to login when not authenticated
- Logged-in users are redirected away from auth pages
- Navigation header reflects auth state

## Hints
- To decode a JWT payload on the client: `JSON.parse(atob(token.split(".")[1]))`. This gives you the payload object with `exp`, `sub`, etc.
- For the auth provider, use `useEffect` with an empty dependency array to run the initialization check on mount.
- When handling form submission, use React's `useState` for form fields and a `try/catch` around the auth call to capture errors.
- The middleware and the AuthProvider serve different purposes: middleware does server-side route guarding, AuthProvider manages client-side state. Both are needed for a complete auth experience.

## What I'll Look For In Review
- Token storage is abstracted behind functions (easy to swap localStorage for cookies later)
- Auto-refresh works transparently without requiring components to know about token lifecycle
- Login/register forms handle and display backend validation errors
- Protected routes are guarded at both middleware and client level
- Auth state is reactive (components re-render when login/logout happens)
