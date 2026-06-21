# Chapter 32 — Chapter Pages API & Reader Data Contract

## Concepts You'll Learn
- API design for frontend consumption: shaping responses to eliminate client-side data assembly
- Data contracts between frontend and backend
- Response shaping based on query parameters
- Avoiding N+1 queries from the frontend

## Concept Deep Dive

### API Design for Frontend Consumption

A manga reader frontend has a very specific data need when opening a chapter: it needs ALL the pages, their image URLs (in multiple sizes), their dimensions (for layout), blurhashes (for placeholders), and navigation context (what are the previous and next chapters?). If the API returns just a list of page IDs and the frontend has to make 30 follow-up requests to get each page's details, the reader feels sluggish.

The golden rule: **one screen, one API call.** The chapter reader screen should be powered by a single `GET /chapters/{id}/pages` request that returns everything the frontend needs. This is not about being lazy -- it is about optimizing for the user's experience. Each additional HTTP round-trip adds 50-200ms of latency on mobile.

This approach is sometimes called a **Backend for Frontend (BFF)** pattern, even when it is just thoughtful endpoint design rather than a separate service. You shape your API responses around what the UI needs, not around your database schema.

### Data Contracts

A **data contract** is the agreed-upon shape of data between frontend and backend. When your frontend developer (even if it is you) asks "what does the chapter pages response look like?", the data contract is the answer. It includes field names, types, nesting, and what is always present vs optional.

A strong data contract means the frontend can build the reader UI without the backend being finished. They agree on the response shape, the frontend mocks it, and both sides code independently.

```python
class PageVariants(BaseModel):
    original: PageImage
    medium: PageImage
    thumbnail: PageImage

class PageImage(BaseModel):
    url: str          # presigned S3 URL
    width: int
    height: int

class ReaderPage(BaseModel):
    page_number: int
    variants: PageVariants
    blurhash: str

class ChapterReaderResponse(BaseModel):
    chapter_id: int
    chapter_number: int
    chapter_title: str
    manga_id: int
    manga_title: str
    pages: list[ReaderPage]
    prev_chapter_id: int | None
    next_chapter_id: int | None
    total_pages: int
```

The frontend never has to figure out how to construct a URL or look up chapter navigation. It is all right there.

### Response Shaping with Reading Modes

Different manga formats require different reading modes. Traditional manga is read right-to-left, one or two pages at a time. Webtoons (Korean webcomics) are vertical scrolls -- a single long strip. Your API can support this by accepting a `reading_mode` query parameter that adjusts the response shape:

**Single mode** (default): each page is an individual item. The frontend displays one page at a time and the user swipes/clicks to advance.

**Double mode**: pages are paired for two-page spread layouts (like a physical book). Page 1 is alone (right side), pages 2-3 are a pair, 4-5 are a pair, etc. The API returns page pairs so the frontend does not have to figure out pairing logic.

**Webtoon mode**: all pages are returned with cumulative height information. The frontend renders them as a continuous vertical scroll. Each page includes a `cumulative_y` offset so the frontend knows where to place it in the scroll container.

```python
@router.get("/chapters/{chapter_id}/pages")
async def get_chapter_pages(
    chapter_id: int,
    reading_mode: Literal["single", "double", "webtoon"] = "single",
):
    pages = await page_service.get_pages_for_chapter(chapter_id)
    if reading_mode == "double":
        return shape_double_pages(pages)
    elif reading_mode == "webtoon":
        return shape_webtoon_pages(pages)
    return shape_single_pages(pages)
```

### Avoiding N+1 from the Frontend

The classic N+1 problem is usually discussed in the context of ORM queries, but it applies equally to frontend-to-backend communication. If the API returns a list of page IDs and the frontend fetches each page's details individually, that is N+1 HTTP requests: 1 to get the list + N to get each page's data.

Solving this is a backend responsibility. Eager-load all related data in a single database query and return it in a single response. For chapter pages, this means joining the Page table with any necessary metadata and generating all presigned URLs in one pass, not lazily per-page.

On the backend side, be careful not to introduce your own N+1: if you loop through 30 pages and call `storage.get_presigned_url()` once per page, that is 30 separate calls (even if they are fast). Consider batch-generating URLs or at least ensuring the URL generation is non-blocking.

## Your Task

### Step 1: Design the Response Schemas

Create `app/schemas/reader.py` with these models:

- `PageImage`: url (str), width (int), height (int)
- `PageVariants`: original (PageImage), medium (PageImage), thumbnail (PageImage)
- `ReaderPage`: page_number (int), variants (PageVariants), blurhash (str)
- `DoublePage`: left (ReaderPage | None), right (ReaderPage | None) -- for spreads
- `WebtoonPage`: extends ReaderPage with cumulative_y (int)
- `ChapterReaderResponse`: chapter metadata + pages list + prev_chapter_id + next_chapter_id + total_pages

### Step 2: Create the Reader Service

Create `app/services/reader.py` with:

- `get_chapter_reader_data(chapter_id, reading_mode) -> ChapterReaderResponse`: the main method
- `_get_pages_with_urls(chapter_id) -> list[ReaderPage]`: fetches pages, generates presigned URLs for all variants
- `_get_adjacent_chapters(chapter_id) -> tuple[int | None, int | None]`: queries for the previous and next chapter based on chapter_number within the same manga
- `_shape_double(pages) -> list[DoublePage]`: pairs pages for spread view
- `_shape_webtoon(pages) -> list[WebtoonPage]`: adds cumulative height offsets

For `_get_adjacent_chapters`: given chapter 5 of manga X, find chapter 4 (prev) and chapter 6 (next) by querying the Chapter table ordered by chapter_number. Return None if there is no previous (first chapter) or next (last chapter).

### Step 3: Implement the Double Page Layout

For double-page mode:
- Page 1 is displayed alone on the right side (it is typically the cover)
- Pages 2-3 form a spread, 4-5 form a spread, etc.
- If the total page count is even, the last page is alone
- Return as a list of `DoublePage` objects where each has `left` and `right`, with one being None for solo pages

### Step 4: Implement the Webtoon Layout

For webtoon mode:
- Each page includes `cumulative_y`: the sum of heights of all preceding pages
- Page 1: cumulative_y = 0
- Page 2: cumulative_y = page_1_height
- Page 3: cumulative_y = page_1_height + page_2_height
- Use the medium variant's height for calculations (that is what the frontend renders)

### Step 5: Create the Endpoint

Create `GET /chapters/{chapter_id}/pages` that:

1. Accepts `reading_mode` query parameter ("single", "double", "webtoon") defaulting to "single"
2. Calls the reader service
3. Returns the shaped response

This single endpoint replaces any simpler page-listing endpoint you had before.

### Step 6: Optimize the Query

Ensure the database query for pages uses eager loading. You should:
- Fetch all pages for the chapter in a single query
- Fetch the chapter with its manga relationship (for manga_title)
- Fetch adjacent chapters with a simple query, not by loading all chapters

Also ensure that presigned URL generation does not become a bottleneck. If generating 30 URLs takes 300ms synchronously, consider running them concurrently with `asyncio.gather`.

## Expected Outcome
- `GET /chapters/{id}/pages` returns all pages with full variant URLs, dimensions, and blurhashes
- The response includes `prev_chapter_id` and `next_chapter_id` for navigation
- `?reading_mode=single` returns individual pages
- `?reading_mode=double` returns paired pages in spread format
- `?reading_mode=webtoon` returns pages with cumulative height offsets
- The endpoint makes a minimal number of database queries (no N+1)
- A frontend developer could build the entire reader UI from this single response

## Hints
- For adjacent chapters, use two queries: `SELECT id FROM chapters WHERE manga_id = :mid AND chapter_number < :num ORDER BY chapter_number DESC LIMIT 1` for previous, and the inverse for next
- When computing cumulative heights for webtoon mode, the medium variant height is most relevant since that is what the reader renders
- For double-page pairing, think of it as: `[page_1], [page_2, page_3], [page_4, page_5], ...` -- the first page is solo, then pairs
- Use `asyncio.gather` to generate presigned URLs concurrently if latency is noticeable

## What I'll Look For In Review
- A single API call returns everything the reader needs -- no follow-up requests required
- The response schemas are clean data contracts that a frontend developer can code against
- Adjacent chapter lookup is efficient (indexed query, not loading all chapters)
- Reading mode shapes the response appropriately, not just filtering fields
- Presigned URL generation does not introduce a performance bottleneck for chapters with many pages
