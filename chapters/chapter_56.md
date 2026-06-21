# Chapter 56 — The Reader Component

## Concepts You'll Learn
- Image preloading with JavaScript Image objects
- Keyboard event handling in React
- Zustand for reader state management
- Progress auto-save with debouncing

## Concept Deep Dive

### Image Preloading

When a user reads a manga chapter, they flip through pages quickly. If every page requires a network fetch on navigation, the reading experience feels sluggish. **Image preloading** downloads upcoming images in the background so they are already in the browser cache when the user navigates to them.

The technique uses the `Image` constructor in JavaScript. When you create a new `Image()` and set its `src`, the browser starts downloading the image even though it is not displayed anywhere in the DOM. The image goes into the browser's memory cache, and when an `<img>` tag later references the same URL, the browser serves it from cache instantly.

```typescript
function preloadImages(urls: string[]) {
  urls.forEach(url => {
    const img = new Image();
    img.src = url;
  });
}

// When user is on page 5, preload pages 6, 7, 8
const currentPage = 5;
const nextUrls = pages.slice(currentPage, currentPage + 3).map(p => p.image_url);
preloadImages(nextUrls);
```

The sweet spot is preloading 2-3 pages ahead. Preloading too many wastes bandwidth (the user might stop reading). Preloading too few means they might outpace the cache. Trigger preloading whenever the current page changes.

For the initial page load before images are ready, use **blurhash placeholders**. Your backend from Chapter 25 generates blurhash strings for uploaded images. Render the blurhash as a blurred placeholder, then swap in the real image once loaded. This eliminates the jarring pop-in effect.

### Keyboard Event Handling

Manga readers expect keyboard navigation: arrow keys, space bar, and possibly number keys for jumping to specific pages. In React, keyboard events need to be handled at the right level.

The standard approach is to attach a `keydown` listener to the `window` object (so it works regardless of which element has focus) and clean it up on unmount:

```typescript
useEffect(() => {
  const handleKeyDown = (e: KeyboardEvent) => {
    switch (e.key) {
      case "ArrowRight":
      case " ": // space
        nextPage();
        break;
      case "ArrowLeft":
        prevPage();
        break;
      case "Escape":
        exitReader();
        break;
    }
  };

  window.addEventListener("keydown", handleKeyDown);
  return () => window.removeEventListener("keydown", handleKeyDown);
}, [nextPage, prevPage]);
```

Two important details: first, include the callback functions in the dependency array (or use `useCallback` to stabilize them). Second, prevent default behavior for keys that would otherwise scroll the page — `e.preventDefault()` inside the cases where you handle the key.

For the webtoon (vertical scroll) mode, you probably do not want arrow keys to override natural scrolling. Make keyboard bindings mode-aware.

### Zustand for Reader State

The reader component has a lot of interconnected state: current page, reading mode, zoom level, preloaded images, loading state, and more. React's `useState` works but becomes unwieldy with many interdependent state variables. **Zustand** is a minimal state management library that gives you a store outside the component tree.

```typescript
import { create } from "zustand";

interface ReaderState {
  currentPage: number;
  totalPages: number;
  readingMode: "single" | "double" | "webtoon";
  isLoading: boolean;
  setPage: (page: number) => void;
  nextPage: () => void;
  prevPage: () => void;
  setMode: (mode: ReaderState["readingMode"]) => void;
}

export const useReaderStore = create<ReaderState>((set, get) => ({
  currentPage: 0,
  totalPages: 0,
  readingMode: "single",
  isLoading: false,
  setPage: (page) => set({ currentPage: Math.max(0, Math.min(page, get().totalPages - 1)) }),
  nextPage: () => {
    const { currentPage, totalPages } = get();
    if (currentPage < totalPages - 1) set({ currentPage: currentPage + 1 });
  },
  prevPage: () => {
    const { currentPage } = get();
    if (currentPage > 0) set({ currentPage: currentPage - 1 });
  },
  setMode: (mode) => set({ readingMode: mode }),
}));
```

Zustand stores live outside React's component tree, so they do not cause unnecessary re-renders. Components subscribe to specific slices of state, and only re-render when those slices change. The store is also accessible outside of components (in event handlers, utility functions), which is useful for keyboard handling.

### Progress Auto-Save with Debouncing

Your backend has a reading progress API (from Chapter 28). Every time the user changes pages, you want to save their progress. But saving on every single page change would mean rapid-fire API calls as the user flips through quickly — wasteful and potentially rate-limited.

**Debouncing** delays the execution of a function until a pause in activity. If the user flips from page 5 to page 6 to page 7 to page 8 in quick succession, a 2-second debounce means the save only fires once (for page 8) after the user stops for 2 seconds.

```typescript
import { useCallback, useRef } from "react";

function useDebouncedCallback<T extends (...args: any[]) => any>(
  callback: T,
  delay: number
) {
  const timeoutRef = useRef<NodeJS.Timeout>();

  return useCallback((...args: Parameters<T>) => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => callback(...args), delay);
  }, [callback, delay]);
}

// Usage in reader:
const saveProgress = useDebouncedCallback(
  (page: number) => api.updateReadingProgress(mangaId, chapterId, page),
  2000
);

// Call on every page change — only actually fires after 2s pause
useEffect(() => {
  saveProgress(currentPage);
}, [currentPage, saveProgress]);
```

Also save progress on component unmount (the user navigates away) — use a cleanup function in `useEffect` that fires the save immediately, regardless of the debounce timer.

## Your Task

### Step 1: Create the Reader Store

Create `frontend/src/stores/readerStore.ts` using Zustand:
- `currentPage` (number)
- `totalPages` (number)
- `readingMode` ("single" | "double" | "webtoon")
- `pages` (array of page data: id, page_number, image_url, blurhash, width, height)
- `isLoading` (boolean)
- Actions: `setPage`, `nextPage`, `prevPage`, `setMode`, `initializeChapter` (sets pages and resets state)
- Computed: `currentPageData`, `hasNext`, `hasPrev`

### Step 2: Build the Reader Page

Create `frontend/src/app/manga/[slug]/read/[chapter]/page.tsx`:
- Fetch chapter page data from the backend
- Initialize the reader store with the page data
- Render the `<Reader>` component
- This should be a full-screen experience (no normal navigation header)

### Step 3: Build Reading Mode Components

Create three reader mode components in `frontend/src/components/reader/`:

**SinglePageReader** — Shows one page at a time. Click left half to go back, right half to go forward. Display page number indicator.

**DoublePageReader** — Shows two pages side by side (like a physical book). Navigate by 2 pages at a time. Handle odd page counts (first page might be solo, like a cover).

**WebtoonReader** — Vertical scroll layout. All pages stacked vertically. Use lazy loading (Intersection Observer) so offscreen pages are not all loaded at once. Track current page based on scroll position.

### Step 4: Build the Main Reader Component

Create `frontend/src/components/reader/Reader.tsx`:
- Renders the appropriate mode component based on `readingMode` from the store
- Includes a floating toolbar (semi-transparent, auto-hides after 3 seconds of inactivity): page indicator, mode switcher buttons, chapter navigation (prev/next chapter), close button
- Attaches keyboard event listeners: ArrowLeft/ArrowRight for prev/next page, Space for next, Escape to exit reader

### Step 5: Implement Image Preloading

In the Reader component or a custom hook `useImagePreloader`:
- When `currentPage` changes, preload the next 3 pages' images
- Track which images have been preloaded (avoid re-preloading)
- Show the blurhash placeholder while an image is loading, swap to real image on load
- For `webtoon` mode, preload based on scroll position rather than page number

### Step 6: Implement Progress Auto-Save

Create a `useProgressSave` hook:
- Calls `PUT /reading-progress` with current manga, chapter, and page number
- Debounced with a 2-second delay
- Also saves immediately on unmount (user leaves the reader)
- Handles errors silently (progress save failure should not disrupt reading)

### Step 7: Add Progress Resume

When the reader page loads:
- Check if the user has existing progress for this chapter
- If so, jump to the saved page number instead of starting at page 1
- Show a brief toast: "Resuming from page X"

## Expected Outcome
- Reader displays chapter pages in all three modes (single, double, webtoon)
- Mode switching works without losing position
- Keyboard navigation works (arrow keys, space, escape)
- Images preload 3 pages ahead for smooth transitions
- Blurhash placeholders show while images load
- Progress auto-saves after 2 seconds of inactivity
- Progress is restored when returning to a previously-read chapter
- Floating toolbar shows/hides on mouse movement

## Hints
- For the double page reader, think about manga reading direction — some manga reads right-to-left. You could add a direction setting, but left-to-right is fine as a default.
- For blurhash rendering, use the `blurhash` npm package which provides a `decode` function. Render the decoded pixels to a small canvas element, then use CSS to scale it up (it will be blurry by nature).
- The webtoon reader's "current page" tracking can use Intersection Observer: observe each page image, and the page with the highest visibility ratio is the "current" page.
- For the floating toolbar auto-hide, use a `mousemove` event listener that resets a timer. After 3 seconds of no mouse movement, hide the toolbar.

## What I'll Look For In Review
- Zustand store has clean separation of state and actions
- All three reading modes work correctly
- Preloading is triggered on page change and limited to a reasonable number of pages ahead
- Debounced progress save fires correctly and also saves on unmount
- Keyboard event listeners are properly cleaned up on component unmount
