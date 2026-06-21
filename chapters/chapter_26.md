# Chapter 26 — Image Processing with Pillow

## Concepts You'll Learn
- Image resizing strategies: fit, fill, and cover modes
- Format conversion and why WebP is the modern default
- Thumbnail generation for fast-loading previews
- Blurhash: compact placeholder previews for progressive loading

## Concept Deep Dive

### Image Resizing Strategies

When a user uploads a manga page at 2400x3400 pixels, you do not serve that full-resolution image to every device. A phone screen is 400px wide -- sending a 2400px image wastes bandwidth and slows loading. Instead, you generate multiple variants at upload time and serve the right one.

There are three common resizing strategies. **Fit** (also called "contain") scales the image down so it fits entirely within the target dimensions, preserving aspect ratio. A 2400x3400 image fit into 800px wide becomes 800x1133. This is what you want for manga pages -- no cropping, no distortion. **Fill** scales and crops to exactly fill the target dimensions, cutting off edges. This is useful for square thumbnails of non-square images. **Cover** is similar to fill but ensures the image covers the target area, possibly overflowing.

```python
from PIL import Image

def resize_fit(img: Image.Image, max_width: int) -> Image.Image:
    if img.width <= max_width:
        return img
    ratio = max_width / img.width
    new_height = int(img.height * ratio)
    return img.resize((max_width, new_height), Image.LANCZOS)
```

`Image.LANCZOS` is the highest-quality downsampling filter in Pillow. It is slower than `BILINEAR` or `NEAREST`, but for a one-time processing job, quality matters more than speed.

### Format Conversion and WebP

JPEG is lossy and ubiquitous. PNG is lossless and huge. WebP, developed by Google, offers both lossy and lossless compression and typically produces files 25-35% smaller than JPEG at equivalent quality. Every modern browser supports it. For a manga library serving thousands of page images, switching from JPEG to WebP saves meaningful bandwidth and storage costs.

Pillow makes conversion trivial:

```python
from io import BytesIO

def convert_to_webp(img: Image.Image, quality: int = 85) -> bytes:
    buffer = BytesIO()
    img.save(buffer, format="WEBP", quality=quality)
    return buffer.getvalue()
```

A quality of 80-85 is the sweet spot for manga pages -- text remains sharp, gradients stay smooth, and file size drops significantly. You keep the original upload as-is (never destroy source data) and generate WebP variants for serving.

### Thumbnail Generation

Thumbnails serve a different purpose than resized images. A resized image maintains the full aspect ratio for reading. A thumbnail is a tiny preview (100-200px wide) used in grid layouts, search results, and library views. They load near-instantly and let users visually scan content.

Pillow has a dedicated `thumbnail()` method that modifies the image in-place and is optimized for small output sizes. Unlike `resize()`, it automatically handles aspect ratio and never upscales:

```python
def generate_thumbnail(img: Image.Image, size: tuple = (200, 300)) -> Image.Image:
    thumb = img.copy()
    thumb.thumbnail(size, Image.LANCZOS)
    return thumb
```

Always work on a copy -- `thumbnail()` mutates the image object.

### Blurhash for Placeholder Previews

When a page is loading, showing a blank rectangle or a spinner is a poor user experience. Modern apps show a blurred placeholder that approximates the image's colors and composition. This is called a **blurhash** -- a compact string (20-30 characters) that encodes a blurred version of the image.

The `blurhash` Python library computes this from image data. The result is a short string like `LEHV6nWB2yk8pyo0adR*.7kCMdnj` that the frontend decodes into a blurred placeholder canvas. The string is small enough to include directly in your API response alongside the image URL, meaning the placeholder renders before the image even starts downloading.

```python
import blurhash

def generate_blurhash(img: Image.Image, x_components: int = 4, y_components: int = 3) -> str:
    # blurhash expects RGB
    img_rgb = img.convert("RGB")
    # Resize to small dimensions for speed (blurhash doesn't need high res)
    img_small = img_rgb.resize((64, 64))
    return blurhash.encode(img_small.tobytes(), 64, 64, x_components, y_components)
```

The `x_components` and `y_components` control detail level. 4x3 is a good default -- enough to capture the general color layout without making the string too long.

## Your Task

### Step 1: Install Dependencies

Add `Pillow` and `blurhash-python` (or `blurhash`) to your requirements. These are the only new dependencies for this chapter.

### Step 2: Create the Image Processor Service

Create `app/services/image_processor.py` with an `ImageProcessor` class containing:

- `resize_image(image_data: bytes, max_width: int) -> bytes`: takes raw image bytes, resizes to fit within max_width, returns WebP bytes
- `convert_to_webp(image_data: bytes, quality: int = 85) -> bytes`: converts any image format to WebP
- `generate_thumbnail(image_data: bytes, size: tuple = (200, 300)) -> bytes`: creates a small thumbnail, returns WebP bytes
- `generate_blurhash(image_data: bytes) -> str`: returns the blurhash string
- `get_dimensions(image_data: bytes) -> tuple[int, int]`: returns (width, height)

Each method should open the image from bytes using `Image.open(BytesIO(data))`, process it, and return bytes via a `BytesIO` buffer. Handle common errors: corrupt images, unsupported formats, images that are too small to resize.

### Step 3: Update the Page Model

Add these columns to your Page model (create an Alembic migration):

- `s3_key_original`: the full-resolution upload key
- `s3_key_medium`: the 800px-wide variant key
- `s3_key_thumbnail`: the 200px-wide variant key
- `width`: original image width in pixels
- `height`: original image height in pixels
- `blurhash`: the blurhash string (VARCHAR 50 or so)

### Step 4: Integrate Processing into Page Upload

Modify the page upload endpoint. When a page image is uploaded:

1. Read the uploaded file bytes
2. Use `ImageProcessor` to get the original dimensions
3. Generate the medium variant (800px wide)
4. Generate the thumbnail (200px wide)
5. Generate the blurhash string
6. Upload all three variants to S3 with keys like:
   - `pages/{chapter_id}/original/{page_num}.webp`
   - `pages/{chapter_id}/medium/{page_num}.webp`
   - `pages/{chapter_id}/thumbnail/{page_num}.webp`
7. Store all three S3 keys, dimensions, and blurhash in the Page record

### Step 5: Update the Page Response Schema

Create or update the Pydantic schema for page responses to include:

- `original_url`: presigned URL for the original
- `medium_url`: presigned URL for the 800px variant
- `thumbnail_url`: presigned URL for the thumbnail
- `width`: int
- `height`: int
- `blurhash`: str

When serializing a Page for API response, convert all three S3 keys to presigned URLs using the StorageService from Chapter 25.

### Step 6: Handle Edge Cases

- If the uploaded image is smaller than 800px wide, the medium variant should be the same as the original (do not upscale)
- If the image is smaller than 200px, the thumbnail is the same as the original
- Convert PNGs and JPEGs to WebP for the variants, but keep the original in its uploaded format (never destroy source data)

## Expected Outcome
- Uploading a page image creates 3 files in S3 (visible in MinIO console)
- The Page record in the database has all three S3 keys, dimensions, and a blurhash string
- `GET /chapters/{id}/pages` returns presigned URLs for all three variants plus dimensions and blurhash
- The original image is preserved as-is; variants are WebP
- Images smaller than the target width are not upscaled

## Hints
- `Image.open()` accepts a `BytesIO` object, so wrap your raw bytes: `Image.open(BytesIO(file_bytes))`
- Remember to seek back to 0 on a BytesIO buffer after writing: `buffer.seek(0)` before reading `.getvalue()`
- For blurhash, resize the image to something tiny first (32x32 or 64x64) -- computing blurhash on a full-res image is extremely slow
- Pillow's `Image.open()` is lazy -- it does not read pixel data until you access it. Call `.load()` explicitly if you need to validate the image before processing

## What I'll Look For In Review
- The ImageProcessor is a clean, testable service with no S3 or database dependencies (pure image logic)
- All three variants are uploaded to S3 with a consistent key naming convention
- The blurhash is computed on a downscaled image for performance, not the full-resolution original
- The original upload is never modified or re-encoded -- variants are derived copies
- Alembic migration adds the new columns cleanly and is reversible
