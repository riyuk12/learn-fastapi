# Chapter 53 — Next.js Project Setup & API Client

## Concepts You'll Learn
- Next.js App Router architecture
- TypeScript for type safety on the frontend
- API client pattern (typed fetch wrapper)
- Environment configuration for frontend applications

## Concept Deep Dive

### Next.js App Router Architecture

Next.js is a React framework that provides structure, routing, and rendering strategies out of the box. The **App Router** (introduced in Next.js 13) uses the file system for routing: every folder inside `app/` becomes a URL segment, and a `page.tsx` file in that folder becomes a routable page.

```
app/
  page.tsx           -> /
  manga/
    page.tsx         -> /manga
    [slug]/
      page.tsx       -> /manga/one-piece
      read/
        [chapter]/
          page.tsx   -> /manga/one-piece/read/42
  (auth)/
    login/
      page.tsx       -> /login
```

Square brackets denote dynamic segments (`[slug]` matches any value). Parenthesized folders like `(auth)` are **route groups** — they organize code without affecting the URL. A `layout.tsx` in any folder wraps all pages in that subtree, letting you share navigation, sidebars, and auth context.

The App Router also distinguishes between **Server Components** (the default) and **Client Components** (marked with `"use client"` at the top). Server Components render on the server and send HTML to the browser. Client Components hydrate in the browser and can use React hooks, event handlers, and browser APIs. This distinction will be critical in Chapter 55.

### TypeScript for Type Safety

TypeScript adds static types to JavaScript. For a frontend consuming your FastAPI backend, this means you can define TypeScript types that mirror your Pydantic schemas, and the compiler catches mismatches at development time instead of runtime.

```typescript
// This mirrors your backend's MangaResponse Pydantic schema
interface MangaResponse {
  id: string;
  title: string;
  slug: string;
  description: string | null;
  status: "ongoing" | "completed" | "hiatus";
  cover_url: string | null;
  created_at: string;
  updated_at: string;
}
```

The critical insight is that these types are a **contract** between frontend and backend. When you change a Pydantic schema on the backend, you should update the corresponding TypeScript type on the frontend. Some teams auto-generate TypeScript types from OpenAPI specs (your FastAPI backend already generates one at `/docs`). For now, maintaining them manually teaches you the discipline of keeping contracts in sync.

### API Client Pattern

Rather than scattering `fetch()` calls throughout your components, you should centralize all API communication in a typed client. This client handles authentication headers, base URL configuration, error parsing, and response typing in one place.

```typescript
class ApiClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  setToken(token: string | null) {
    this.token = token;
  }

  async request<T>(path: string, options?: RequestInit): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...options?.headers as Record<string, string>,
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new ApiError(response.status, error.detail);
    }

    return response.json() as T;
  }
}
```

This gives you a single place to handle all cross-cutting concerns. Every component that needs data calls `api.request<MangaResponse>("/manga/one-piece")` and gets a typed result.

### Environment Configuration

Next.js supports environment variables through `.env.local` (for local development) and `.env.production` (for production builds). Variables prefixed with `NEXT_PUBLIC_` are exposed to the browser; unprefixed variables are only available server-side.

```bash
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

The `NEXT_PUBLIC_` prefix is a security boundary. Your API URL is safe to expose to the browser (the user can see it in network requests anyway). But secrets like API keys for server-side operations should never have the `NEXT_PUBLIC_` prefix.

Access them in code via `process.env.NEXT_PUBLIC_API_URL`. In the API client, use this as the base URL. This means switching between development (localhost:8000) and production (your real API domain) requires only changing the environment variable, not the code.

## Your Task

### Step 1: Create the Next.js Project

From the project root, create a new Next.js application:

```bash
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --use-npm
```

Choose the following options when prompted: use TypeScript, use Tailwind CSS, use App Router, use src/ directory. This creates a `frontend/` directory alongside your existing backend code.

### Step 2: Configure Environment

Create `frontend/.env.local` with:
- `NEXT_PUBLIC_API_URL` pointing to your local backend (`http://localhost:8000/api/v1`)

Create `frontend/.env.example` as a template (same keys, placeholder values) for other developers.

### Step 3: Create TypeScript Types

Create `frontend/src/lib/types.ts` with TypeScript interfaces matching your backend Pydantic schemas. At minimum, define:
- `MangaResponse` — id, title, slug, description, status, cover_url, genres, created_at, updated_at
- `MangaListResponse` — items array, total count, pagination cursor
- `ChapterResponse` — id, manga_id, chapter_number, title, page_count, created_at
- `UserResponse` — id, username, email, role, avatar_url, created_at
- `ReviewResponse` — id, user_id, manga_id, rating, content, created_at, user (nested)
- `NotificationResponse` — id, type, title, body, is_read, data, created_at
- `PaginatedResponse<T>` — a generic type for paginated responses with items, cursor, has_more
- `ApiError` — status, detail

Keep these aligned with your actual Pydantic schemas. If your backend schema has a field, the TypeScript type should have it.

### Step 4: Build the API Client

Create `frontend/src/lib/api-client.ts` with:
- A class or set of functions that wrap `fetch()`
- Automatic `Authorization: Bearer <token>` header injection
- Base URL from environment variable
- Response type parsing with generics
- Error handling that throws a typed `ApiError`
- Methods for common HTTP verbs: `get<T>()`, `post<T>()`, `put<T>()`, `patch<T>()`, `delete<T>()`

Also create convenience methods for common endpoints:
- `getManga(slug: string): Promise<MangaResponse>`
- `listManga(params): Promise<PaginatedResponse<MangaResponse>>`
- `getChapters(mangaId: string): Promise<ChapterResponse[]>`
- `login(email, password): Promise<TokenResponse>`
- `register(data): Promise<UserResponse>`
- `getNotifications(): Promise<PaginatedResponse<NotificationResponse>>`

Export a singleton instance for use throughout the app.

### Step 5: Create a Custom Error Class

Create `frontend/src/lib/errors.ts` with an `ApiError` class that includes the HTTP status code and the error detail from the backend. Components can catch these and display appropriate messages.

### Step 6: Set Up Project Structure

Create the folder structure for upcoming chapters:
- `frontend/src/app/(auth)/login/` — will hold login page
- `frontend/src/app/(auth)/register/` — will hold register page
- `frontend/src/app/manga/` — will hold browsing pages
- `frontend/src/app/library/` — will hold library pages
- `frontend/src/lib/` — shared utilities
- `frontend/src/components/` — shared components
- `frontend/src/stores/` — client-side state (for Zustand later)

Create placeholder `page.tsx` files where needed so the routes exist (they can just render "Coming soon" text).

### Step 7: Verify Everything Runs

Start the Next.js development server and verify:
- The dev server starts without errors
- The home page renders
- The API client can be imported without errors
- Environment variables are accessible

## Expected Outcome
- `frontend/` directory contains a working Next.js project with TypeScript and Tailwind CSS
- TypeScript types match backend Pydantic schemas
- API client handles auth, errors, and typing in a centralized way
- Environment is configured for local development
- `npm run dev` in `frontend/` starts the dev server alongside the backend
- Project structure is ready for the pages you will build in Chapters 54-57

## Hints
- For the API client, the `fetch` API is built into modern Node.js and browsers — you do not need axios or any HTTP library.
- Use TypeScript generics to make the API client methods type-safe: `async get<T>(path: string): Promise<T>`.
- When defining types, prefer `interface` over `type` for object shapes — interfaces give better error messages and can be extended.
- For paginated responses, a generic type like `PaginatedResponse<T>` avoids repeating the pagination wrapper for every entity type.

## What I'll Look For In Review
- Types accurately mirror backend Pydantic schemas (field names, types, nullability)
- API client is a single centralized module, not scattered fetch calls
- Error handling produces typed errors that components can reason about
- Environment variables are properly used (no hardcoded URLs)
- Project structure is clean and follows Next.js conventions
