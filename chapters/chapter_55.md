# Chapter 55 — Manga Browsing & Discovery Pages

## Concepts You'll Learn
- Server Components vs Client Components in Next.js
- Data fetching in Next.js (server-side)
- Infinite scroll with Intersection Observer
- Responsive grid layouts with Tailwind CSS

## Concept Deep Dive

### Server Components vs Client Components

The App Router introduced a paradigm shift in React: components are **Server Components** by default. They render on the server, send HTML to the browser, and never hydrate. They cannot use hooks (`useState`, `useEffect`), event handlers, or browser APIs. Their advantage is performance — they send zero JavaScript to the client and can directly access server-side resources.

**Client Components** are marked with `"use client"` at the top of the file. They hydrate in the browser and work like traditional React components with full interactivity.

The key principle is: **push interactivity to the leaves**. Your page layout, data fetching, and static content should be Server Components. Interactive elements — buttons, forms, scroll handlers, state-driven UI — should be Client Components embedded within the server-rendered page.

```tsx
// app/manga/page.tsx — Server Component (default)
export default async function MangaBrowsePage() {
  const initialManga = await api.listManga({ limit: 20 }); // server-side fetch

  return (
    <div>
      <h1>Browse Manga</h1>
      <FilterSidebar />  {/* Client Component — interactive */}
      <MangaGrid initialData={initialManga} />  {/* Client Component — infinite scroll */}
    </div>
  );
}
```

In this pattern, the page itself is a Server Component that fetches the first page of data on the server. The `MangaGrid` is a Client Component that receives this initial data as props and handles infinite scroll on the client. The user sees the first 20 manga instantly (server-rendered HTML), and more load as they scroll.

### Data Fetching in Next.js

In Server Components, you can use `async/await` directly — no `useEffect`, no loading states for the initial render. The component function itself is `async` and awaits your API calls.

```tsx
// This runs on the server before the page is sent to the browser
export default async function MangaDetailPage({ params }: { params: { slug: string } }) {
  const manga = await api.getManga(params.slug);

  return <MangaDetail manga={manga} />;
}
```

For server-side fetches, you call your backend API from the server. The API client you built in Chapter 53 works here, but without auth headers (Server Components do not have access to localStorage). For public endpoints like manga listings, this is fine. For authenticated fetches from Server Components, you would read the token from cookies — but for now, keep server-side fetches for public data only.

Next.js also provides caching and revalidation options for server-side fetches. The `revalidate` export controls how long the cached response is used before re-fetching. For a manga detail page, a 60-second revalidation is reasonable — it will not change every second.

### Infinite Scroll with Intersection Observer

Infinite scroll replaces traditional pagination with automatic loading as the user scrolls. The **Intersection Observer API** is the modern, performant way to detect when an element enters the viewport.

```typescript
"use client";
import { useEffect, useRef, useCallback } from "react";

function useIntersectionObserver(onIntersect: () => void) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          onIntersect();
        }
      },
      { threshold: 0.1 }
    );

    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [onIntersect]);

  return ref;
}
```

You place an invisible "sentinel" `<div>` at the bottom of your list and observe it. When the user scrolls to the bottom and the sentinel enters the viewport, you fetch the next page. The cursor from your backend's cursor-based pagination (built in Chapter 39) tells the API where to continue from.

The critical UX details: show a loading spinner while fetching, stop observing when there are no more pages (`has_more === false`), and prevent duplicate fetches when the user scrolls quickly (guard with a `loading` state).

### Responsive Grid Layouts with Tailwind CSS

Tailwind's grid utilities make responsive layouts straightforward. For a manga card grid, you want different column counts at different screen sizes:

```tsx
<div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
  {manga.map(m => <MangaCard key={m.id} manga={m} />)}
</div>
```

This gives 2 columns on mobile, scaling up to 6 on large screens. Each `MangaCard` shows the cover image, title, and status badge. The aspect ratio of manga covers is typically 2:3, so use Tailwind's `aspect-[2/3]` utility to maintain consistent card sizes regardless of the actual image dimensions.

The responsive breakpoints (`sm`, `md`, `lg`, `xl`) are mobile-first: unqualified classes apply to all sizes, and prefixed classes override at that breakpoint and above. This means you design for mobile first, then add complexity for larger screens.

## Your Task

### Step 1: Create Shared Components

Build these reusable components in `frontend/src/components/`:

**MangaCard** — A card component showing:
- Cover image (with fallback placeholder if no cover)
- Title (truncated to 2 lines)
- Status badge (ongoing/completed/hiatus with different colors)
- Optional: chapter count, rating

**LoadingSpinner** — A simple loading indicator (Tailwind animation).

**Pagination sentinel** — An invisible div that triggers the intersection observer.

### Step 2: Build the Home Page

Update `frontend/src/app/page.tsx` as a Server Component:
- Fetch featured/recently updated manga from the backend (server-side)
- Render a "Recently Updated" section as a responsive grid of MangaCards
- Optionally add a hero section or welcome banner at the top
- This page should work without JavaScript (it is server-rendered)

### Step 3: Build the Browse/Discovery Page

Create `frontend/src/app/manga/page.tsx`:
- Server Component that fetches the initial page of manga
- Passes initial data to a Client Component `<MangaGrid>`

Create `frontend/src/components/MangaGrid.tsx` as a Client Component:
- Receives initial data as props
- Implements infinite scroll using Intersection Observer
- Uses your API client to fetch subsequent pages with cursor-based pagination
- Shows a loading spinner while fetching
- Stops loading when `has_more` is false

Create `frontend/src/components/FilterSidebar.tsx` as a Client Component:
- Dropdowns/checkboxes for genre, status, sort order
- Changing a filter resets the grid and fetches new results
- Use URL search params (`useSearchParams`) to make filters shareable via URL

### Step 4: Build the Manga Detail Page

Create `frontend/src/app/manga/[slug]/page.tsx` as a Server Component:
- Fetch manga details by slug from the backend
- Display: cover image, title, description, genres, status, chapter count, average rating
- List chapters in order (with links to reader — placeholder for now)
- Show reviews section (list of reviews with ratings)
- Optionally show "Similar Manga" if your discovery endpoint supports it

### Step 5: Handle Loading and Error States

Create `frontend/src/app/manga/[slug]/loading.tsx` — a loading skeleton that shows while the manga detail is being fetched (Next.js renders this automatically during server-side data fetching).

Create `frontend/src/app/manga/[slug]/error.tsx` — an error boundary component that shows a user-friendly message if the fetch fails (manga not found, server error, etc.).

### Step 6: Make Everything Responsive

Test your layouts at multiple viewport widths:
- Mobile (375px): single column or 2-column grid
- Tablet (768px): 3-4 columns
- Desktop (1024px+): 5-6 columns

The manga detail page should stack vertically on mobile (cover above content) and show cover beside content on desktop.

## Expected Outcome
- Home page shows recently updated manga in a responsive grid
- Browse page has working filters and infinite scroll
- Changing filters resets the grid and fetches matching results
- Manga detail page shows full information with chapter list and reviews
- Loading states show skeletons/spinners
- Error states show user-friendly messages
- Pages are responsive from mobile to desktop

## Hints
- For server-side API calls, create a separate API client instance that does not use localStorage (Server Components have no browser APIs). You can use `fetch` directly with the server's API URL.
- The Intersection Observer hook should use `useCallback` for the intersection handler to prevent re-creating the observer on every render.
- For infinite scroll, store the cursor in component state. The initial cursor comes from the server-rendered first page.
- Tailwind's `line-clamp-2` utility truncates text to 2 lines — useful for manga titles on cards.

## What I'll Look For In Review
- Server Components are used for data fetching, Client Components for interactivity (not the other way around)
- Infinite scroll properly uses cursor-based pagination (not offset)
- Intersection Observer is properly cleaned up on unmount
- Filters sync with URL search params for shareability
- Responsive design works at all standard breakpoints
