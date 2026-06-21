# Chapter 57 — Library, Collections & Profile Pages

## Concepts You'll Learn
- CRUD interfaces with optimistic updates
- Drag-and-drop reordering with dnd-kit
- User profile pages with data visualization
- TanStack Query for server state management

## Concept Deep Dive

### Optimistic Updates

In a traditional CRUD flow, the user clicks a button, you send a request to the server, wait for the response, and then update the UI. This works but feels slow — the user clicks "Add to Library" and sees a spinner for 200-500ms before anything changes.

**Optimistic updates** flip this: you update the UI immediately (optimistically assuming the request will succeed), then send the request in the background. If the request fails, you roll back the UI to the previous state. The result is an interface that feels instant.

```typescript
// Without optimistic update:
const addToLibrary = async (mangaId: string) => {
  setLoading(true);
  await api.addToLibrary(mangaId, "reading");
  setLibrary(prev => [...prev, { mangaId, status: "reading" }]);
  setLoading(false);
};

// With optimistic update:
const addToLibrary = async (mangaId: string) => {
  const previousLibrary = library; // save for rollback
  setLibrary(prev => [...prev, { mangaId, status: "reading" }]); // update immediately
  try {
    await api.addToLibrary(mangaId, "reading"); // background request
  } catch {
    setLibrary(previousLibrary); // rollback on failure
    toast.error("Failed to add to library");
  }
};
```

The key insight is that most requests succeed. By optimizing for the common case (success), you make the UI feel dramatically faster. The rollback path handles the rare failure case. Users perceive the app as responsive because they see immediate feedback.

TanStack Query (React Query) has built-in support for optimistic updates through its `onMutate`, `onError`, and `onSettled` callbacks, which is why it pairs so well with this pattern.

### Drag-and-Drop Reordering

Collections in MangaShelf let users curate lists of manga. A natural interaction for reordering items in a list is drag-and-drop. The **dnd-kit** library is the modern choice for React drag-and-drop — it is accessible, performant, and works on touch devices.

The core architecture of dnd-kit has three parts: a `DndContext` that manages the drag session, `useDraggable` for items that can be picked up, and `useDroppable` for zones where items can be dropped. For list reordering, the `@dnd-kit/sortable` extension simplifies everything:

```tsx
import { DndContext, closestCenter } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";

<DndContext collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
  <SortableContext items={items} strategy={verticalListSortingStrategy}>
    {items.map(item => <SortableItem key={item.id} item={item} />)}
  </SortableContext>
</DndContext>
```

When a drag ends, you get the `active` (dragged item) and `over` (target position). You recompute the order array locally and send the new order to the backend. This is another perfect case for optimistic updates — reorder the list immediately in the UI, then persist to the server.

### TanStack Query for Server State

So far, your components manage server data with `useState` and `useEffect`. This works but means each component independently handles loading, errors, caching, refetching, and stale data. **TanStack Query** (formerly React Query) centralizes server state management with a declarative API.

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

// Fetching data
const { data: library, isLoading } = useQuery({
  queryKey: ["library"],
  queryFn: () => api.getLibrary(),
});

// Mutating data with optimistic update
const queryClient = useQueryClient();
const addToLibrary = useMutation({
  mutationFn: (data) => api.addToLibrary(data),
  onMutate: async (newItem) => {
    await queryClient.cancelQueries({ queryKey: ["library"] });
    const previous = queryClient.getQueryData(["library"]);
    queryClient.setQueryData(["library"], old => [...old, newItem]);
    return { previous };
  },
  onError: (err, newItem, context) => {
    queryClient.setQueryData(["library"], context.previous); // rollback
  },
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: ["library"] }); // refetch to sync
  },
});
```

TanStack Query gives you automatic caching (data fetched once is reused), background refetching (stale data is refreshed automatically), deduplication (multiple components requesting the same data trigger only one fetch), and the optimistic update pattern shown above. It replaces a huge amount of boilerplate code.

### User Profile and Data Visualization

Profile pages aggregate data from multiple endpoints: user info, reading statistics, reading history, activity. Displaying stats meaningfully often requires charts. For simple charts, a lightweight library like **recharts** (built on D3) integrates well with React:

```tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip } from "recharts";

const readingHistory = [
  { month: "Jan", chapters: 42 },
  { month: "Feb", chapters: 38 },
  // ...
];

<BarChart data={readingHistory}>
  <XAxis dataKey="month" />
  <YAxis />
  <Tooltip />
  <Bar dataKey="chapters" fill="#8884d8" />
</BarChart>
```

Charts transform raw numbers into visual insights. A reading history chart lets users see their reading patterns over time — do they read more on weekends? Did they have a binge month? This transforms data that already exists in your backend (reading progress, timestamps) into a meaningful user feature.

## Your Task

### Step 1: Set Up TanStack Query

Install `@tanstack/react-query` and create a `QueryClientProvider` wrapper. Add it to your app layout alongside the AuthProvider. Create a shared `queryClient` instance with sensible defaults (stale time, retry count).

### Step 2: Build the Library Page

Create `frontend/src/app/library/page.tsx`:
- Tabbed interface with statuses: Reading, Completed, Plan to Read, On Hold, Dropped
- Each tab shows a grid of manga cards from the user's library filtered by that status
- Each manga card has quick-action buttons: change status (dropdown), remove from library
- Use TanStack Query for data fetching with the `["library", status]` query key pattern
- Implement optimistic updates for status changes (immediate UI update, background sync)
- Add a search/filter within the library

### Step 3: Build the Collections List Page

Create `frontend/src/app/collections/page.tsx`:
- Grid or list of user's collections
- Each collection card shows: name, description, manga count, cover thumbnails (first 3-4 manga covers)
- "Create Collection" button that opens a modal/form
- Use TanStack Query for fetching and creating collections

### Step 4: Build the Collection Detail Page with Drag-and-Drop

Create `frontend/src/app/collections/[id]/page.tsx`:
- Shows collection title, description, and the ordered list of manga
- Install `@dnd-kit/core` and `@dnd-kit/sortable`
- Each manga item is draggable — users can reorder by dragging
- On drag end, reorder the local list and send the new order to the backend
- "Add Manga" button that opens a search modal to find and add manga to the collection
- "Remove" button on each item

### Step 5: Build the Profile Page

Create `frontend/src/app/profile/page.tsx`:
- Display user info: avatar, username, join date, role
- Reading statistics section: total manga read, total chapters read, total reading time
- Library breakdown: pie chart or bar chart showing counts by status
- Reading history chart: chapters read per week/month over the last 6 months
- Recent activity list (from the activity feed)

Install `recharts` for the charts. Use your backend's statistics endpoints (from Chapter 30) to get the data.

### Step 6: Implement Optimistic Updates Throughout

For every mutation in the library and collections pages, implement the optimistic update pattern:
- Status change: immediately update the card's status badge
- Remove from library: immediately remove the card from the grid
- Reorder collection: immediately reflect the new order
- All mutations should roll back on error and show an error toast

### Step 7: Add Loading and Empty States

- Loading states: show skeleton cards while data is fetching
- Empty states: show a friendly message when library is empty ("Your library is empty. Browse manga to get started!" with a link to the browse page)
- Error states: show error message with a retry button

## Expected Outcome
- Library page with tabbed status filtering and quick-action buttons
- Status changes are instant (optimistic update) with background sync
- Collections page with creation and listing
- Collection detail page with functional drag-and-drop reordering
- Profile page with reading statistics and charts
- All mutations use optimistic updates with proper rollback
- Loading, empty, and error states are handled throughout

## Hints
- For TanStack Query, the `queryKey` should include all parameters that affect the data. For library tabs, use `["library", { status }]` so each tab has its own cache entry.
- For drag-and-drop, the `arrayMove` utility from `@dnd-kit/sortable` helps reorder arrays when given the old and new indexes.
- For the reading history chart, group your reading progress data by week or month on the frontend. Alternatively, create a backend endpoint that returns pre-aggregated data.
- Empty state components with calls-to-action (like "Browse manga") improve the new-user experience dramatically.

## What I'll Look For In Review
- TanStack Query is properly configured with QueryClientProvider and sensible defaults
- Optimistic updates work correctly: immediate UI change, background persistence, rollback on error
- Drag-and-drop reordering persists to the backend
- Profile charts render meaningful data from actual backend endpoints
- Loading, empty, and error states exist for every data-dependent component
