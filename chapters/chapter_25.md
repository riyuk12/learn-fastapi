# Chapter 25 — MinIO/S3 Object Storage

## Concepts You'll Learn
- Object storage concepts: buckets, keys, presigned URLs vs public URLs
- MinIO as a local S3-compatible storage engine
- Using aioboto3/boto3 for Python S3 operations
- Why object storage beats filesystem storage for production apps

## Concept Deep Dive

### Object Storage Concepts

Object storage is fundamentally different from a filesystem. In a filesystem, you have directories, subdirectories, and files organized in a hierarchy. Object storage is flat: you have **buckets** (top-level containers, like a hard drive) and **keys** (the full path to an object, like `covers/manga_42/cover.jpg`). The key *looks* like a path, but there are no actual directories -- it is just a string that uniquely identifies an object within a bucket.

Every object has three parts: the key (its name), the data (the bytes), and metadata (content type, size, custom headers). You interact with objects through HTTP APIs rather than filesystem calls. This is why S3-compatible storage can scale to billions of objects across distributed servers -- there is no directory tree to traverse, just a flat key-value lookup backed by distributed hash tables.

**Presigned URLs** are temporary, signed URLs that grant time-limited access to a private object. Instead of making your bucket public (dangerous -- anyone can scrape all your images), you keep it private and generate a presigned URL on-the-fly when a user requests a resource. The URL includes a cryptographic signature and an expiration timestamp. After the expiry, the URL returns 403 Forbidden. This is how most production apps serve private files: your API is the gatekeeper, not S3's access controls alone.

The alternative is **public URLs** -- the bucket or specific objects are publicly readable. This is simpler but means anyone with the URL can access the file forever. For MangaShelf, presigned URLs make sense because you may want to restrict access to authenticated users or implement rate limiting on downloads.

### MinIO as Local S3-Compatible Storage

Amazon S3 is the gold standard for object storage, but you do not want to pay AWS bills during development, and you certainly do not want to depend on network connectivity to run your tests. MinIO is an open-source, high-performance object storage server that implements the S3 API. Every S3 SDK call -- `put_object`, `get_object`, `presign` -- works identically against MinIO.

You run MinIO as a Docker container locally. In production, you swap the endpoint URL to AWS S3 (or DigitalOcean Spaces, or Cloudflare R2 -- they all speak S3). Your code does not change. This is the power of coding against an interface rather than an implementation.

```python
# The only thing that changes between MinIO and AWS S3:
MINIO_CONFIG = {
    "endpoint_url": "http://localhost:9000",  # MinIO
    "aws_access_key_id": "minioadmin",
    "aws_secret_access_key": "minioadmin",
}

AWS_CONFIG = {
    "region_name": "us-east-1",
    # credentials from environment/IAM role
}
```

This is also why you externalize these values into your `app/core/config.py` -- the same codebase runs everywhere.

### aioboto3 for Async S3 Operations

Since your FastAPI app is async, you want async S3 calls. The `aioboto3` library wraps `boto3` (AWS's official Python SDK) with async context managers. The API surface is identical to boto3, but every call is `await`-ed.

```python
import aioboto3

session = aioboto3.Session()
async with session.client("s3", **config) as s3:
    await s3.put_object(Bucket="mangashelf-images", Key="covers/42.jpg", Body=file_bytes)
    url = await s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": "mangashelf-images", "Key": "covers/42.jpg"},
        ExpiresIn=3600,  # 1 hour
    )
```

Key operations you will use: `put_object` (upload), `get_object` (download), `delete_object` (remove), `generate_presigned_url` (create temporary access URL), and `head_object` (check if an object exists without downloading it).

### Why Object Storage Over Filesystem

In Chapter 24, you saved uploaded covers to the local filesystem. This works on a single server, but breaks the moment you scale. If you run two instances of your API behind a load balancer, an upload hitting instance A saves to A's disk. A subsequent request hitting instance B cannot find the file. Object storage solves this because all instances talk to the same centralized store.

Beyond horizontal scaling, object storage gives you: built-in redundancy (data is replicated), no disk space management headaches, HTTP-based access (no NFS mounts), lifecycle policies (auto-delete old objects), and versioning. Your application servers become stateless -- they hold no data, only logic. This is a core principle of the Twelve-Factor App methodology.

## Your Task

### Step 1: Run MinIO via Docker

Start a MinIO container exposing the S3 API on port 9000 and the web console on port 9001. Use `minioadmin` / `minioadmin` as the root credentials. Mount a local volume so data persists between container restarts.

### Step 2: Add S3 Configuration to Settings

In `app/core/config.py`, add these settings: `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_NAME` (default: `mangashelf-images`), `S3_PRESIGNED_URL_EXPIRY` (default: 3600 seconds). Load them from environment variables as you did with database and auth settings.

### Step 3: Create the Storage Service

Create `app/services/storage.py` with a `StorageService` class that has:

- `__init__`: accepts config settings, creates an aioboto3 session
- `upload_file(key: str, file_data: bytes, content_type: str) -> str`: uploads to S3, returns the key
- `get_presigned_url(key: str, expiry: int = None) -> str`: generates a presigned GET URL
- `delete_file(key: str) -> None`: deletes an object from the bucket
- `file_exists(key: str) -> bool`: checks if an object exists using `head_object`

Use an async context manager for the S3 client within each method. Handle `ClientError` exceptions and raise meaningful application errors (e.g., `StorageError` or `FileNotFoundError`).

### Step 4: Create the Bucket on Startup

Add a startup event or lifespan handler that calls `create_bucket` if the bucket does not already exist. Catch the `BucketAlreadyOwnedByYou` error gracefully.

### Step 5: Refactor Cover Upload

Modify the manga cover upload endpoint from Chapter 24. Instead of saving to a local directory:

1. Generate an S3 key like `covers/{manga_id}/{uuid}.{extension}`
2. Upload the file bytes to S3 via `StorageService.upload_file()`
3. Store the S3 key (not a presigned URL) in the `cover_image` column of the Manga model
4. Delete the old cover from S3 if replacing

### Step 6: Generate Presigned URLs on Read

Modify the manga serialization layer. When returning manga data via the API, convert the stored S3 key into a presigned URL using `StorageService.get_presigned_url()`. The URL should expire in 1 hour. Consider creating a response model that has a `cover_url` field populated dynamically rather than storing the URL in the database (URLs expire, keys do not).

### Step 7: Clean Up Local Storage

Remove the local file upload logic from Chapter 24. Delete or deprecate the local upload directory config. Your app should now have zero local file dependencies for cover images.

## Expected Outcome
- MinIO is running in Docker and accessible at `http://localhost:9000`
- The MinIO web console at `http://localhost:9001` shows a `mangashelf-images` bucket
- Uploading a manga cover stores the file in MinIO (visible in web console)
- `GET /manga/{id}` returns a `cover_url` field with a presigned URL
- The presigned URL loads the image in a browser and expires after 1 hour
- Replacing a cover deletes the old file from S3
- No files are stored on the local filesystem

## Hints
- Use `docker run -p 9000:9000 -p 9001:9001 --name minio -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin -v minio_data:/data minio/minio server /data --console-address ":9001"` to start MinIO
- The `generate_presigned_url` method in boto3/aioboto3 takes `ClientMethod`, `Params`, and `ExpiresIn` arguments -- check the boto3 docs for exact parameter names
- If you get `EndpointConnectionError`, make sure your `S3_ENDPOINT_URL` includes the protocol (`http://localhost:9000`, not just `localhost:9000`)
- Use `uuid.uuid4().hex` for unique filenames to avoid collisions when users upload different covers

## What I'll Look For In Review
- S3 configuration is externalized in settings, not hardcoded in the service
- The StorageService is injected as a dependency rather than instantiated directly in route handlers
- S3 keys are stored in the database, never presigned URLs (URLs expire; keys are permanent)
- Error handling covers common S3 failures (object not found, connection error, access denied)
- Old covers are cleaned up when replaced, avoiding orphaned objects in the bucket
