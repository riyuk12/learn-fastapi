# Chapter 24 — File Upload Fundamentals

## Concepts You'll Learn
- Multipart form data and how file uploads work in HTTP
- FastAPI's `UploadFile` type and its streaming interface
- File size validation and MIME type checking via magic bytes
- Organizing uploaded files in temporary local storage

## Concept Deep Dive

### Multipart Form Data

When you submit a JSON body to your API, the Content-Type is `application/json`. But JSON can't carry binary data (like images) efficiently. For file uploads, HTTP uses `multipart/form-data` — a content type designed to send a mix of text fields and binary files in a single request.

A multipart request looks roughly like this (simplified):

```
Content-Type: multipart/form-data; boundary=----FormBoundary123

------FormBoundary123
Content-Disposition: form-data; name="file"; filename="cover.jpg"
Content-Type: image/jpeg

[binary image data here]
------FormBoundary123--
```

The "boundary" string separates different parts of the request. Each part has a name, optional filename, content type, and the actual data. This is what your browser sends when you use `<input type="file">` in an HTML form.

FastAPI handles parsing multipart requests automatically. You just need to declare a parameter with the right type.

### FastAPI's UploadFile

`UploadFile` is FastAPI's abstraction for uploaded files. It provides a file-like interface with async methods:

```python
from fastapi import UploadFile, File

@router.post("/manga/{manga_id}/cover")
async def upload_cover(
    manga_id: uuid.UUID,
    file: UploadFile = File(...),
):
    content = await file.read()  # Read entire file into memory
    # Or stream in chunks:
    # async for chunk in file:
    #     process(chunk)
```

Key properties and methods of `UploadFile`:
- `file.filename` — the original filename from the client (e.g., "cover.jpg")
- `file.content_type` — the MIME type reported by the client (DON'T trust this for validation)
- `file.size` — the file size in bytes (may be None for streaming uploads)
- `await file.read()` — read the entire file content
- `await file.read(size)` — read up to `size` bytes
- `await file.seek(0)` — reset to the beginning (useful after reading)
- `file.file` — the underlying SpooledTemporaryFile

`File(...)` is the dependency declaration for a file parameter. The `...` means required. You can also have optional file uploads with `File(default=None)`.

For large files, avoid `await file.read()` (which loads the entire file into memory). Instead, read in chunks:

```python
CHUNK_SIZE = 1024 * 1024  # 1MB chunks

async with aiofiles.open(save_path, "wb") as out_file:
    while chunk := await file.read(CHUNK_SIZE):
        await out_file.write(chunk)
```

### File Size Validation

You must validate file size BEFORE processing the file. A malicious user could upload a 10GB file and crash your server.

There are two approaches:

**1. Check Content-Length header** (fast but unreliable):
```python
content_length = request.headers.get("content-length")
if content_length and int(content_length) > MAX_SIZE:
    raise FileTooLargeException()
```
This is fast but clients can lie about Content-Length. Use it as a quick pre-check.

**2. Track bytes while reading** (reliable):
```python
MAX_SIZE = 5 * 1024 * 1024  # 5MB

content = bytearray()
while chunk := await file.read(CHUNK_SIZE):
    content.extend(chunk)
    if len(content) > MAX_SIZE:
        raise FileTooLargeException(max_size_mb=5)
```

This is reliable because you're counting actual bytes. Use both approaches together: Content-Length for a fast reject, byte counting for definitive validation.

### MIME Type Checking via Magic Bytes

Never trust the Content-Type header or the file extension. A user can rename `malware.exe` to `cover.jpg` and set Content-Type to `image/jpeg`. Your server must verify the actual file content.

Every file format has "magic bytes" — a specific sequence of bytes at the start of the file that identifies the format. For example:

| Format | Magic Bytes (hex) | As ASCII |
|--------|------------------|----------|
| JPEG | `FF D8 FF` | (non-printable) |
| PNG | `89 50 4E 47` | `.PNG` |
| WebP | `52 49 46 46 ... 57 45 42 50` | `RIFF....WEBP` |
| GIF | `47 49 46 38` | `GIF8` |

To check, read the first few bytes and compare:

```python
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
}

async def detect_image_type(file: UploadFile) -> str | None:
    header = await file.read(16)  # Read first 16 bytes
    await file.seek(0)  # Reset for later use

    for magic, mime_type in MAGIC_BYTES.items():
        if header.startswith(magic):
            return mime_type

    return None  # Unknown format
```

WebP is slightly more complex because the magic bytes aren't contiguous — the file starts with "RIFF", followed by a 4-byte file size, then "WEBP". You need to check bytes 0-3 and bytes 8-11.

The `python-magic` library (a wrapper around `libmagic`) can detect file types more comprehensively, but for a known set of image formats, checking magic bytes directly is simpler and dependency-free.

### Local File Storage

For now, you'll store uploaded files in a local `uploads/` directory. This is temporary — in production you'd use cloud storage (S3, GCS, etc.), which you'll implement later in the curriculum.

Important practices for local storage:
1. **Never use the client's filename.** Generate a UUID-based filename to prevent path traversal attacks and filename collisions.
2. **Organize by resource.** Store manga covers in `uploads/manga/{manga_id}/`, chapter pages in `uploads/chapters/{chapter_id}/`.
3. **Preserve the original extension** (after validating it matches the magic bytes).
4. **Add the uploads directory to .gitignore.**

```python
import aiofiles
from pathlib import Path

UPLOAD_DIR = Path("uploads")

async def save_upload(file: UploadFile, subdirectory: str) -> str:
    # Generate safe filename
    extension = get_extension_from_mime(detected_type)
    filename = f"{uuid.uuid4()}{extension}"
    save_dir = UPLOAD_DIR / subdirectory
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename

    async with aiofiles.open(save_path, "wb") as out:
        while chunk := await file.read(CHUNK_SIZE):
            await out.write(chunk)

    return str(save_path)
```

## Your Task

### Step 1: Install dependencies

Install `aiofiles` (for async file operations) and `python-multipart` (required by FastAPI for form/file parsing). Update `requirements.txt`.

### Step 2: Create file validation utilities

Create `app/utils/files.py` with:

- `validate_file_size(file: UploadFile, max_size_bytes: int) -> None` — raises an exception if the file is too large. Read in chunks and track total size.
- `detect_image_type(file: UploadFile) -> str | None` — reads the magic bytes and returns the MIME type (`"image/jpeg"`, `"image/png"`, `"image/webp"`) or `None` for unrecognized formats. Remember to `seek(0)` after reading.
- `validate_image_file(file: UploadFile, max_size_mb: int = 5) -> str` — combines size and type validation. Returns the detected MIME type or raises a clear error.

Support at minimum: JPEG, PNG, and WebP.

### Step 3: Create file storage utility

In the same file (or `app/utils/storage.py`), create:

- `save_upload(file: UploadFile, subdirectory: str, filename: str | None = None) -> str` — saves the file to `uploads/{subdirectory}/` with a UUID filename. Returns the relative path. Uses `aiofiles` for async writing.
- `delete_upload(file_path: str) -> None` — deletes a file from the uploads directory. Handle "file not found" gracefully.

### Step 4: Create the cover upload endpoint

Add to your manga endpoints:

`POST /api/v1/manga/{manga_id}/cover` — Upload a cover image:
1. Requires moderator+ authentication
2. Accepts a multipart file upload
3. Validates: max 5MB, JPEG/PNG/WebP only (check magic bytes)
4. Saves to `uploads/manga/{manga_id}/cover.{ext}`
5. Updates the manga's `cover_image_url` field with the file path
6. If a cover already exists, delete the old file before saving the new one
7. Returns the updated manga

### Step 5: Create the batch page upload endpoint

Add to your chapter endpoints:

`POST /api/v1/chapters/{chapter_id}/pages` — Upload pages for a chapter:
1. Requires moderator+ authentication
2. Accepts multiple file uploads (FastAPI supports `list[UploadFile]`)
3. Validates each file: max 5MB each, images only
4. Saves each file to `uploads/chapters/{chapter_id}/`
5. Creates Page records in the database with sequential page numbers (starting from the current max page number + 1, or 1 if no pages exist)
6. Updates the chapter's `page_count`
7. Returns the list of created pages

For multiple file uploads in FastAPI:
```python
@router.post("/{chapter_id}/pages")
async def upload_pages(
    chapter_id: uuid.UUID,
    files: list[UploadFile] = File(...),
):
    ...
```

### Step 6: Add uploads to .gitignore

Add `uploads/` to your `.gitignore`.

### Step 7: Create page schemas

In `app/schemas/page.py`, create:
- `PageResponse`: id, chapter_id, page_number, image_url, width, height, blurhash

### Step 8: Test the upload flow

**Cover upload:**
1. Upload a valid JPEG → 200, manga's `cover_image_url` is updated
2. Upload a valid PNG → 200, old cover is replaced
3. Upload a 10MB file → error (too large)
4. Upload a `.txt` file renamed to `.jpg` → error (invalid magic bytes)
5. Upload without authentication → 401

**Page upload:**
1. Upload 3 images to a chapter → 3 Page records created with page_numbers 1, 2, 3
2. Upload 2 more images → Page records with page_numbers 4, 5
3. Upload a non-image file → error
4. Verify chapter's `page_count` is updated to 5

## Expected Outcome
- Cover upload validates file size (max 5MB) and type (JPEG/PNG/WebP via magic bytes)
- Non-image files are rejected with a clear error, regardless of file extension
- Oversized files are rejected before being fully processed
- Files are saved with UUID filenames (never client-provided names)
- Batch page upload creates multiple Page records with sequential numbering
- Chapter's `page_count` is updated after page upload
- Old cover files are deleted when replaced
- `uploads/` directory is gitignored

## Hints
- FastAPI requires `python-multipart` to parse file uploads. If you get `AttributeError: 'Request' object has no attribute 'form'`, you forgot to install it.
- For WebP magic byte detection: check that bytes 0-3 are `RIFF` and bytes 8-11 are `WEBP`.
- `await file.seek(0)` is essential after reading magic bytes — otherwise subsequent reads start from where you left off.
- When reading file size in chunks, use a counter variable instead of loading the whole file. Break early if the counter exceeds the limit.
- `aiofiles.open(path, "wb")` is the async equivalent of `open(path, "wb")`. The `wb` mode means write binary.
- For batch uploads, process files sequentially (not concurrently) to keep page numbering deterministic.

## What I'll Look For In Review
- Magic byte validation is used (not Content-Type header or file extension alone)
- File size is validated by counting bytes during reading, not just trusting Content-Length
- Files are saved with UUID filenames, never with the client's original filename
- The cover upload deletes the old file before saving the new one
- Batch page upload assigns sequential page numbers correctly
- Error messages for invalid files are clear ("File must be JPEG, PNG, or WebP" not just "Invalid file")
